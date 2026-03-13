from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.csrf import csrf_protection
from app.dependencies import AuthRedirect, flash, get_db, now_ist, template_ctx, templates
from app.services.activity_log import log_activity
from app.models.agenda import AgendaItem
from app.models.booking import Booking
from app.models.session import LectureSession
from app.models.session_speaker import SessionSpeaker
from app.models.speaker import Speaker
from app.models.user import User

router = APIRouter(prefix="/speaker", tags=["speaker"], dependencies=[Depends(csrf_protection)])


def _require_speaker(request: Request, db: Session):
    user_id = request.session.get("user_id")
    if not user_id:
        raise AuthRedirect(f"/auth/login?next={request.url.path}")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AuthRedirect("/auth/login")
    speaker = db.query(Speaker).filter(Speaker.user_id == user.id).first()
    if not speaker:
        raise AuthRedirect("/")
    return user, speaker


def _speaker_ctx(request: Request, **kwargs):
    ctx = template_ctx(request)
    ctx.update(kwargs)
    return ctx


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    session_ids_via_assignment = db.query(SessionSpeaker.session_id).filter(
        SessionSpeaker.speaker_id == speaker.id
    )
    session_ids_via_agenda = db.query(AgendaItem.session_id).filter(
        AgendaItem.speaker_id == speaker.id
    )
    sessions = (
        db.query(LectureSession)
        .filter(
            or_(
                LectureSession.speaker_id == speaker.id,
                LectureSession.id.in_(session_ids_via_assignment),
                LectureSession.id.in_(session_ids_via_agenda),
            )
        )
        .order_by(LectureSession.start_time.desc())
        .all()
    )
    now = now_ist()
    enriched = []
    for s in sessions:
        booking_count = db.query(func.count(Booking.id)).filter(
            Booking.session_id == s.id, Booking.payment_status == "paid"
        ).scalar()
        enriched.append({"session": s, "bookings": booking_count})

    total = len(sessions)
    upcoming = sum(1 for s in sessions if s.start_time > now)
    completed = sum(1 for s in sessions if s.status == "completed")

    return templates.TemplateResponse(
        "speaker/dashboard.html",
        _speaker_ctx(
            request,
            speaker=speaker,
            sessions=enriched,
            total=total,
            upcoming=upcoming,
            completed=completed,
        ),
    )


def _speaker_can_access_session(speaker, lecture, db) -> bool:
    """Return True if speaker has any relation to this session."""
    if lecture.speaker_id == speaker.id:
        return True
    in_assignments = db.query(SessionSpeaker).filter(
        SessionSpeaker.session_id == lecture.id,
        SessionSpeaker.speaker_id == speaker.id,
    ).first()
    if in_assignments:
        return True
    in_agenda = db.query(AgendaItem).filter(
        AgendaItem.session_id == lecture.id,
        AgendaItem.speaker_id == speaker.id,
    ).first()
    return in_agenda is not None


@router.get("/sessions/{session_id}/edit")
def session_edit(request: Request, session_id: int, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    lecture = db.query(LectureSession).get(session_id)
    if not lecture or not _speaker_can_access_session(speaker, lecture, db):
        flash(request, "Session not found or access denied.", "danger")
        return RedirectResponse("/speaker/", status_code=303)
    is_primary = lecture.speaker_id == speaker.id
    agenda_items = (
        db.query(AgendaItem)
        .filter(AgendaItem.session_id == session_id)
        .order_by(AgendaItem.order)
        .all()
    )
    all_speakers = db.query(Speaker).order_by(Speaker.name).all()
    return templates.TemplateResponse(
        "speaker/session_edit.html",
        _speaker_ctx(request, speaker=speaker, lecture=lecture, agenda_items=agenda_items, is_primary=is_primary, all_speakers=all_speakers),
    )


@router.post("/sessions/{session_id}/edit")
async def session_update(request: Request, session_id: int, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    lecture = db.query(LectureSession).get(session_id)
    if not lecture or not _speaker_can_access_session(speaker, lecture, db):
        flash(request, "Session not found or access denied.", "danger")
        return RedirectResponse("/speaker/", status_code=303)

    is_primary = lecture.speaker_id == speaker.id
    form = await request.form()

    if is_primary:
        start_str = form.get("start_time", "")
        try:
            start_time = datetime.fromisoformat(start_str)
        except ValueError:
            flash(request, "Invalid date/time.", "danger")
            return RedirectResponse(f"/speaker/sessions/{session_id}/edit", status_code=303)

        lecture.title = form.get("title", lecture.title).strip()
        lecture.description = form.get("description", "").strip()
        lecture.banner_url = form.get("banner_url", "").strip() or None
        lecture.start_time = start_time
        lecture.duration_minutes = int(form.get("duration_minutes", 30))
        lecture.status = form.get("status", lecture.status)

        # Primary speaker replaces all agenda items
        db.query(AgendaItem).filter(AgendaItem.session_id == session_id).delete()
        idx = 0
        while True:
            title = form.get(f"agenda_title_{idx}")
            if title is None:
                break
            title = title.strip()
            if title:
                spk_id_raw = form.get(f"agenda_speaker_id_{idx}", "").strip()
                spk_id = int(spk_id_raw) if spk_id_raw.isdigit() else None
                spk_obj = db.query(Speaker).get(spk_id) if spk_id else None
                item = AgendaItem(
                    session_id=session_id,
                    order=idx,
                    title=title,
                    speaker_id=spk_obj.id if spk_obj else None,
                    speaker_name=spk_obj.name if spk_obj else None,
                    duration_minutes=int(form.get(f"agenda_duration_{idx}", 20) or 20),
                    description=form.get(f"agenda_desc_{idx}", "").strip() or None,
                )
                db.add(item)
            idx += 1
    else:
        # Non-primary: only update their own agenda items by speaker_id
        own_items = db.query(AgendaItem).filter(
            AgendaItem.session_id == session_id,
            AgendaItem.speaker_id == speaker.id,
        ).all()
        for item in own_items:
            idx = item.order
            new_title = form.get(f"agenda_title_{idx}", "").strip()
            if new_title:
                item.title = new_title
                item.duration_minutes = int(form.get(f"agenda_duration_{idx}", item.duration_minutes) or item.duration_minutes)
                item.description = form.get(f"agenda_desc_{idx}", "").strip() or None

    log_activity(db, category="speaker", action="update", description=f"Speaker '{speaker.name}' updated session '{lecture.title}'", request=request, user_id=user.id, target_type="session", target_id=session_id)
    db.commit()
    flash(request, f"Session '{lecture.title}' updated.", "success")
    return RedirectResponse("/speaker/", status_code=303)


@router.get("/profile")
def profile_page(request: Request, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    return templates.TemplateResponse(
        "speaker/profile.html",
        _speaker_ctx(request, speaker=speaker),
    )


@router.post("/profile")
async def profile_update(request: Request, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    form = await request.form()

    speaker.name = form.get("name", speaker.name).strip()
    speaker.title = form.get("title", "").strip() or None
    speaker.bio = form.get("bio", "").strip() or None
    speaker.photo_url = form.get("photo_url", "").strip() or None
    db.commit()

    for s in speaker.sessions:
        s.speaker = speaker.name
    log_activity(db, category="speaker", action="profile_update", description=f"Speaker '{speaker.name}' updated their profile", request=request, user_id=user.id, target_type="speaker", target_id=speaker.id)
    db.commit()

    flash(request, "Speaker profile updated.", "success")
    return RedirectResponse("/speaker/profile", status_code=303)

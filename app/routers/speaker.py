from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dependencies import AuthRedirect, flash, get_db, now_ist, template_ctx, templates
from app.models.agenda import AgendaItem
from app.models.booking import Booking
from app.models.session import LectureSession
from app.models.speaker import Speaker
from app.models.user import User

router = APIRouter(prefix="/speaker", tags=["speaker"])


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
    sessions = (
        db.query(LectureSession)
        .filter(LectureSession.speaker_id == speaker.id)
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


@router.get("/sessions/{session_id}/edit")
def session_edit(request: Request, session_id: int, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    lecture = db.query(LectureSession).get(session_id)
    if not lecture or lecture.speaker_id != speaker.id:
        flash(request, "Session not found or access denied.", "danger")
        return RedirectResponse("/speaker/", status_code=303)
    agenda_items = (
        db.query(AgendaItem)
        .filter(AgendaItem.session_id == session_id)
        .order_by(AgendaItem.order)
        .all()
    )
    return templates.TemplateResponse(
        "speaker/session_edit.html",
        _speaker_ctx(request, speaker=speaker, lecture=lecture, agenda_items=agenda_items),
    )


@router.post("/sessions/{session_id}/edit")
async def session_update(request: Request, session_id: int, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    lecture = db.query(LectureSession).get(session_id)
    if not lecture or lecture.speaker_id != speaker.id:
        flash(request, "Session not found or access denied.", "danger")
        return RedirectResponse("/speaker/", status_code=303)

    form = await request.form()

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

    # Update agenda items
    db.query(AgendaItem).filter(AgendaItem.session_id == session_id).delete()
    idx = 0
    while True:
        title = form.get(f"agenda_title_{idx}")
        if title is None:
            break
        title = title.strip()
        if title:
            item = AgendaItem(
                session_id=session_id,
                order=idx,
                title=title,
                speaker_name=form.get(f"agenda_speaker_{idx}", "").strip() or None,
                duration_minutes=int(form.get(f"agenda_duration_{idx}", 20) or 20),
                description=form.get(f"agenda_desc_{idx}", "").strip() or None,
            )
            db.add(item)
        idx += 1

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

    # Also update the display name on sessions
    for s in speaker.sessions:
        s.speaker = speaker.name
    db.commit()

    flash(request, "Speaker profile updated.", "success")
    return RedirectResponse("/speaker/profile", status_code=303)

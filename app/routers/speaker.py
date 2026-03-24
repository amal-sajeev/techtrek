import calendar as _calendar
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.csrf import csrf_protection
from app.dependencies import AuthRedirect, flash, get_db, now_ist, template_ctx, templates
from app.services.activity_log import log_activity
from app.models.agenda import AgendaItem
from app.models.auditorium import Auditorium
from app.models.booking import Booking
from app.models.event import Event
from app.models.session import Session as SessionModel
from app.models.session_speaker import SessionSpeaker
from app.models.speaker import Speaker
from app.models.gallery_image import GalleryImage
from app.models.uploaded_image import UploadedImage
from app.models.user import User
from app.models.poll import Poll, PollOption, PollVote

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


def _speaker_sessions(speaker, db):
    """Return all sessions linked to this speaker and computed stats."""
    session_ids_via_assignment = db.query(SessionSpeaker.session_id).filter(
        SessionSpeaker.speaker_id == speaker.id
    )
    session_ids_via_agenda = db.query(AgendaItem.session_id).filter(
        AgendaItem.speaker_id == speaker.id
    )
    sessions = (
        db.query(SessionModel)
        .filter(
            or_(
                SessionModel.speaker_id == speaker.id,
                SessionModel.id.in_(session_ids_via_assignment),
                SessionModel.id.in_(session_ids_via_agenda),
            )
        )
        .all()
    )
    from app.models.event_session import EventSession
    now = now_ist()
    today = now.date()
    enriched = []
    for s in sessions:
        es = db.query(EventSession).filter(EventSession.session_id == s.id).first()
        event = es.event if es else None
        booking_count = (
            db.query(func.count(Booking.id)).filter(
                Booking.event_id == event.id, Booking.payment_status == "paid",
                Booking.is_shared_ticket == False,
            ).scalar()
            if event else 0
        )
        enriched.append({
            "session": s,
            "event": event,
            "event_session": es,
            "bookings": booking_count,
        })

    total = len(sessions)
    upcoming = sum(
        1 for item in enriched
        if item["event"] and item["event"].start_date and item["event"].start_date >= today and item["event"].status == "published"
    )
    completed = sum(
        1 for item in enriched
        if item["event"] and item["event"].status == "completed"
    )
    return sessions, enriched, total, upcoming, completed


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    _sessions, _enriched, total, upcoming, completed = _speaker_sessions(speaker, db)
    return templates.TemplateResponse(
        "speaker/dashboard.html",
        _speaker_ctx(
            request,
            speaker=speaker,
            total=total,
            upcoming=upcoming,
            completed=completed,
        ),
    )


@router.get("/sessions")
def sessions_list(request: Request, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    _sessions, enriched, total, upcoming, completed = _speaker_sessions(speaker, db)
    return templates.TemplateResponse(
        "speaker/sessions.html",
        _speaker_ctx(
            request,
            speaker=speaker,
            sessions=enriched,
            total=total,
            upcoming=upcoming,
            completed=completed,
        ),
    )


@router.get("/schedule")
def schedule(
    request: Request,
    db: Session = Depends(get_db),
    view: str = Query("month", alias="view"),
    year: int | None = Query(None, alias="year"),
    month: int | None = Query(None, alias="month"),
    week: int | None = Query(None, alias="week"),
):
    user, speaker = _require_speaker(request, db)
    raw_sessions, _enriched, _t, _u, _c = _speaker_sessions(speaker, db)

    now = now_ist()
    if year is None:
        year = now.year
    if month is None:
        month = now.month
    if view not in ("month", "week"):
        view = "month"

    from app.models.event_session import EventSession as ES_cal
    all_events = []
    seen_es_ids = set()
    for s in raw_sessions:
        es_list = db.query(ES_cal).filter(ES_cal.session_id == s.id).all()
        for es in es_list:
            if es.id in seen_es_ids:
                continue
            seen_es_ids.add(es.id)
            ev = es.event
            if not ev:
                continue
            aud = db.query(Auditorium).get(ev.auditorium_id) if ev.auditorium_id else None
            college_obj = aud.college if aud else None
            city = college_obj.city if college_obj else None
            bcount = (
                db.query(func.count(Booking.id))
                .filter(Booking.event_id == ev.id, Booking.payment_status == "paid")
                .scalar()
            )
            all_events.append({
                "id": ev.id,
                "session_id": s.id,
                "session_title": s.title,
                "start_date": ev.start_date,
                "start_time": es.start_time or (datetime.combine(ev.start_date, datetime.min.time()) if ev.start_date else None),
                "end_date": ev.end_date,
                "duration": s.duration_minutes or 30,
                "status": ev.status,
                "auditorium": aud.name if aud else "TBD",
                "location": aud.location if aud else "",
                "college": college_obj.name if college_obj else "",
                "city": city.name if city else "",
                "price": float(ev.price or 0),
                "bookings": bcount,
            })

    if view == "month":
        cal = _calendar.Calendar(firstweekday=0)
        month_days = cal.monthdatescalendar(year, month)

        events_by_date = defaultdict(list)
        for ev_data in all_events:
            if ev_data["start_date"]:
                events_by_date[ev_data["start_date"]].append(ev_data)

        weeks = []
        for week_dates in month_days:
            week_row = []
            for d in week_dates:
                week_row.append({
                    "date": d,
                    "day": d.day,
                    "is_today": d == now.date(),
                    "is_other_month": d.month != month,
                    "events": events_by_date.get(d, []),
                })
            weeks.append(week_row)

        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1

        month_label = datetime(year, month, 1).strftime("%B %Y")

        return templates.TemplateResponse(
            "speaker/schedule.html",
            _speaker_ctx(
                request,
                speaker=speaker,
                view=view,
                weeks=weeks,
                month_label=month_label,
                year=year,
                month_num=month,
                prev_year=prev_year,
                prev_month=prev_month,
                next_year=next_year,
                next_month=next_month,
                today=now.date(),
            ),
        )
    else:
        if week is not None:
            jan4 = datetime(year, 1, 4).date()
            start_of_year_week1 = jan4 - timedelta(days=jan4.weekday())
            week_start = start_of_year_week1 + timedelta(weeks=week - 1)
        else:
            week_start = now.date() - timedelta(days=now.weekday())
            week = week_start.isocalendar()[1]

        week_end = week_start + timedelta(days=6)
        week_dates = [week_start + timedelta(days=i) for i in range(7)]

        events_by_date = defaultdict(list)
        for ev_data in all_events:
            if ev_data["start_date"]:
                d = ev_data["start_date"]
                if week_start <= d <= week_end:
                    events_by_date[d].append(ev_data)

        days = []
        for d in week_dates:
            days.append({
                "date": d,
                "day": d.day,
                "weekday": d.strftime("%a"),
                "is_today": d == now.date(),
                "events": events_by_date.get(d, []),
            })

        prev_week_start = week_start - timedelta(weeks=1)
        next_week_start = week_start + timedelta(weeks=1)
        prev_iso = prev_week_start.isocalendar()
        next_iso = next_week_start.isocalendar()

        week_label = f"{week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}"

        return templates.TemplateResponse(
            "speaker/schedule.html",
            _speaker_ctx(
                request,
                speaker=speaker,
                view=view,
                days=days,
                week_label=week_label,
                week_num=week,
                year=year,
                prev_week=prev_iso[1],
                prev_week_year=prev_iso[0],
                next_week=next_iso[1],
                next_week_year=next_iso[0],
                today=now.date(),
            ),
        )


def _speaker_can_access_session(speaker, session_obj, db) -> bool:
    """Return True if speaker has any relation to this session."""
    if session_obj.speaker_id == speaker.id:
        return True
    in_assignments = db.query(SessionSpeaker).filter(
        SessionSpeaker.session_id == session_obj.id,
        SessionSpeaker.speaker_id == speaker.id,
    ).first()
    if in_assignments:
        return True
    in_agenda = db.query(AgendaItem).filter(
        AgendaItem.session_id == session_obj.id,
        AgendaItem.speaker_id == speaker.id,
    ).first()
    return in_agenda is not None


@router.get("/sessions/{session_id}/edit")
def session_edit(request: Request, session_id: int, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    session_obj = db.query(SessionModel).get(session_id)
    if not session_obj or not _speaker_can_access_session(speaker, session_obj, db):
        flash(request, "Session not found or access denied.", "danger")
        return RedirectResponse("/speaker/", status_code=303)
    is_primary = session_obj.speaker_id == speaker.id
    agenda_items = (
        db.query(AgendaItem)
        .filter(AgendaItem.session_id == session_id)
        .order_by(AgendaItem.order)
        .all()
    )
    all_speakers = db.query(Speaker).order_by(Speaker.name).all()
    from app.models.event_session import EventSession as ES_edit
    es = db.query(ES_edit).filter(ES_edit.session_id == session_id).first()
    event = es.event if es else None
    gallery = db.query(GalleryImage).filter(
        GalleryImage.owner_type == "session", GalleryImage.owner_id == session_id
    ).order_by(GalleryImage.position).all()
    return templates.TemplateResponse(
        "speaker/session_edit.html",
        _speaker_ctx(request, speaker=speaker, lecture=session_obj, session=session_obj, event=event, agenda_items=agenda_items, is_primary=is_primary, all_speakers=all_speakers, gallery_images=gallery),
    )


@router.post("/sessions/{session_id}/edit")
async def session_update(request: Request, session_id: int, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    session_obj = db.query(SessionModel).get(session_id)
    if not session_obj or not _speaker_can_access_session(speaker, session_obj, db):
        flash(request, "Session not found or access denied.", "danger")
        return RedirectResponse("/speaker/", status_code=303)

    is_primary = session_obj.speaker_id == speaker.id
    form = await request.form()

    if is_primary:
        session_obj.title = form.get("title", session_obj.title).strip()
        session_obj.abstract = form.get("abstract", "").strip() or form.get("description", "").strip()
        session_obj.key_learning_outcomes = form.get("key_learning_outcomes", "").strip()
        session_obj.description = session_obj.abstract
        session_obj.banner_url = form.get("banner_url", "").strip() or None
        session_obj.duration_minutes = int(form.get("duration_minutes", 30))

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

    raw_gallery = form.get("gallery_image_ids", "").strip()
    if raw_gallery:
        db.query(GalleryImage).filter(
            GalleryImage.owner_type == "session", GalleryImage.owner_id == session_id
        ).delete()
        for pos, img_id_str in enumerate(raw_gallery.split(",")):
            img_id_str = img_id_str.strip()
            if img_id_str and img_id_str.isdigit():
                db.add(GalleryImage(owner_type="session", owner_id=session_id, image_id=int(img_id_str), position=pos))

    log_activity(db, category="speaker", action="update", description=f"Speaker '{speaker.name}' updated session '{session_obj.title}'", request=request, user_id=user.id, target_type="session", target_id=session_id)
    db.commit()
    flash(request, f"Session '{session_obj.title}' updated.", "success")
    return RedirectResponse("/speaker/sessions", status_code=303)


@router.get("/sessions/{session_id}/polls")
def session_polls(request: Request, session_id: int, event_id: int = Query(default=0), db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    session_obj = db.query(SessionModel).get(session_id)
    if not session_obj or not _speaker_can_access_session(speaker, session_obj, db):
        flash(request, "Session not found or access denied.", "danger")
        return RedirectResponse("/speaker/", status_code=303)
    from app.models.event_session import EventSession as ES_poll
    es_poll = db.query(ES_poll).filter(ES_poll.session_id == session_id).first()
    eid = event_id or (es_poll.event_id if es_poll else 0)
    filters = [Poll.session_id == session_id]
    if eid:
        filters.append(Poll.event_id == eid)
    polls = db.query(Poll).filter(*filters).order_by(Poll.created_at.desc()).all()
    polls_enriched = []
    for p in polls:
        enriched: dict = {"poll": p}
        if p.poll_type in ("multiple_choice", "yes_no"):
            total = sum(len(o.votes) for o in p.options)
            opts = []
            for o in p.options:
                count = len(o.votes)
                opts.append({"option": o, "votes": count, "pct": round(count / total * 100, 1) if total else 0})
            enriched.update(total_votes=total, options=opts)
        elif p.poll_type == "rating":
            votes = [v for v in p.votes if v.rating_value is not None]
            total = len(votes)
            avg = round(sum(v.rating_value for v in votes) / total, 1) if total else 0
            dist = {s: 0 for s in range(1, 6)}
            for v in votes:
                dist[v.rating_value] = dist.get(v.rating_value, 0) + 1
            enriched.update(total_votes=total, average=avg, distribution=dist)
        elif p.poll_type == "text":
            votes = [v for v in p.votes if v.text_answer]
            enriched.update(total_votes=len(votes), text_responses=[v.text_answer for v in votes])
        else:
            enriched.update(total_votes=0, options=[])
        polls_enriched.append(enriched)
    return templates.TemplateResponse(
        "speaker/session_polls.html",
        _speaker_ctx(request, speaker=speaker, session=session_obj, polls=polls_enriched, poll_event_id=eid),
    )


@router.post("/sessions/{session_id}/polls")
async def create_poll(request: Request, session_id: int, event_id: int = Query(default=0), db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    session_obj = db.query(SessionModel).get(session_id)
    if not session_obj or not _speaker_can_access_session(speaker, session_obj, db):
        return JSONResponse({"ok": False, "error": "Access denied."}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid request."}, status_code=400)
    question = (body.get("question") or "").strip()
    poll_type = body.get("poll_type", "multiple_choice")
    if poll_type not in ("multiple_choice", "yes_no", "rating", "text"):
        poll_type = "multiple_choice"
    options_list = body.get("options", [])
    if not question:
        return JSONResponse({"ok": False, "error": "Provide a question."}, status_code=400)
    if poll_type == "multiple_choice" and len(options_list) < 2:
        return JSONResponse({"ok": False, "error": "Provide at least 2 options."}, status_code=400)

    from app.models.event_session import EventSession as ES_poll2
    es_poll2 = db.query(ES_poll2).filter(ES_poll2.session_id == session_id).first()
    eid = event_id or (es_poll2.event_id if es_poll2 else 0)
    if not eid:
        return JSONResponse({"ok": False, "error": "No event associated with this session."}, status_code=400)
    poll = Poll(
        session_id=session_id,
        event_id=eid,
        question=question,
        poll_type=poll_type,
        allow_multiple=bool(body.get("allow_multiple")),
        created_by=user.id,
        is_active=False,
    )
    db.add(poll)
    db.flush()
    if poll_type == "yes_no":
        db.add(PollOption(poll_id=poll.id, option_text="Yes", order=0))
        db.add(PollOption(poll_id=poll.id, option_text="No", order=1))
    elif poll_type == "multiple_choice":
        for i, opt_text in enumerate(options_list):
            opt_text = (opt_text or "").strip()
            if opt_text:
                db.add(PollOption(poll_id=poll.id, option_text=opt_text, order=i))

    log_activity(db, category="speaker", action="create", description=f"Speaker '{speaker.name}' created poll for session '{session_obj.title}'", request=request, user_id=user.id, target_type="poll", target_id=poll.id)
    db.commit()
    return JSONResponse({"ok": True, "poll_id": poll.id})


@router.post("/polls/{poll_id}/toggle")
async def toggle_poll(request: Request, poll_id: int, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    poll = db.query(Poll).get(poll_id)
    if not poll:
        return JSONResponse({"ok": False, "error": "Poll not found."}, status_code=404)
    session_obj = db.query(SessionModel).get(poll.session_id)
    if not session_obj or not _speaker_can_access_session(speaker, session_obj, db):
        return JSONResponse({"ok": False, "error": "Access denied."}, status_code=403)

    if not poll.is_active:
        db.query(Poll).filter(
            Poll.session_id == poll.session_id, Poll.event_id == poll.event_id, Poll.is_active == True
        ).update({Poll.is_active: False})
        poll.is_active = True
    else:
        poll.is_active = False

    db.commit()

    from app.services.poll_events import publish
    if poll.is_active:
        from app.routers.public import _poll_results, _notify_event_attendees_of_poll
        results = _poll_results(db, poll)
        await publish(poll.session_id, poll.event_id, results)
        _notify_event_attendees_of_poll(db, poll, results)
    else:
        from app.routers.public import _notify_event_attendees_poll_closed
        await publish(poll.session_id, poll.event_id, {"poll_id": poll.id, "is_active": False, "closed": True})
        _notify_event_attendees_poll_closed(db, poll)

    return JSONResponse({"ok": True, "is_active": poll.is_active})


@router.post("/polls/{poll_id}/close")
async def close_poll(request: Request, poll_id: int, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    poll = db.query(Poll).get(poll_id)
    if not poll:
        return JSONResponse({"ok": False, "error": "Poll not found."}, status_code=404)
    session_obj = db.query(SessionModel).get(poll.session_id)
    if not session_obj or not _speaker_can_access_session(speaker, session_obj, db):
        return JSONResponse({"ok": False, "error": "Access denied."}, status_code=403)

    poll.is_active = False
    poll.closed_at = now_ist()
    db.commit()

    from app.services.poll_events import publish
    from app.routers.public import _notify_event_attendees_poll_closed
    await publish(poll.session_id, poll.event_id, {"poll_id": poll.id, "is_active": False, "closed": True})
    _notify_event_attendees_poll_closed(db, poll)
    return JSONResponse({"ok": True})


@router.post("/polls/{poll_id}/delete")
def delete_poll(request: Request, poll_id: int, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    poll = db.query(Poll).get(poll_id)
    if not poll:
        flash(request, "Poll not found.", "danger")
        return RedirectResponse("/speaker/", status_code=303)
    session_obj = db.query(SessionModel).get(poll.session_id)
    if not session_obj or not _speaker_can_access_session(speaker, session_obj, db):
        flash(request, "Access denied.", "danger")
        return RedirectResponse("/speaker/", status_code=303)
    sid = poll.session_id
    eid = poll.event_id
    db.delete(poll)
    db.commit()
    flash(request, "Poll deleted.", "success")
    return RedirectResponse(f"/speaker/sessions/{sid}/polls?event_id={eid}", status_code=303)


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
        s.speaker_name = speaker.name
    log_activity(db, category="speaker", action="profile_update", description=f"Speaker '{speaker.name}' updated their profile", request=request, user_id=user.id, target_type="speaker", target_id=speaker.id)
    db.commit()

    flash(request, "Speaker profile updated.", "success")
    return RedirectResponse("/speaker/profile", status_code=303)


@router.post("/upload-image")
async def speaker_upload_image(request: Request, db: Session = Depends(get_db)):
    from app.models.uploaded_image import UploadedImage

    _require_speaker(request, db)

    form = await request.form()
    file = form.get("image")
    if not file or not hasattr(file, "filename"):
        return JSONResponse({"error": "No file uploaded"}, status_code=400)

    allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if file.content_type not in allowed:
        return JSONResponse({"error": "Invalid file type. Allowed: JPEG, PNG, GIF, WebP"}, status_code=400)

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        return JSONResponse({"error": "File too large (max 5MB)"}, status_code=400)

    img = UploadedImage(
        filename=file.filename or "upload",
        content_type=file.content_type,
        data=content,
    )
    db.add(img)
    db.commit()
    db.refresh(img)

    return JSONResponse({"url": f"/uploads/{img.id}"})

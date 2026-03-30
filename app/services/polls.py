"""Shared poll helpers used by public, admin, and speaker routers."""

import re
from urllib.parse import urlparse, parse_qs

from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.models.booking import Booking
from app.models.poll import Poll, PollOption, PollVote
from app.models.session import Session


def poll_results(db: DbSession, poll) -> dict:
    base = {
        "poll_id": poll.id,
        "question": poll.question,
        "poll_type": poll.poll_type or "multiple_choice",
        "is_active": poll.is_active,
        "allow_multiple": poll.allow_multiple,
    }
    ptype = poll.poll_type or "multiple_choice"

    if ptype in ("multiple_choice", "yes_no"):
        total_votes = db.query(func.count(PollVote.id)).filter(
            PollVote.poll_id == poll.id, PollVote.option_id.isnot(None)
        ).scalar() or 0
        options = []
        for opt in poll.options:
            count = db.query(func.count(PollVote.id)).filter(PollVote.option_id == opt.id).scalar() or 0
            options.append({
                "id": opt.id, "text": opt.option_text,
                "votes": count, "pct": round(count / total_votes * 100, 1) if total_votes else 0,
            })
        base.update(total_votes=total_votes, options=options)

    elif ptype == "rating":
        votes = db.query(PollVote).filter(
            PollVote.poll_id == poll.id, PollVote.rating_value.isnot(None)
        ).all()
        total = len(votes)
        avg = round(sum(v.rating_value for v in votes) / total, 1) if total else 0
        dist = {s: 0 for s in range(1, 6)}
        for v in votes:
            dist[v.rating_value] = dist.get(v.rating_value, 0) + 1
        base.update(total_votes=total, average=avg, distribution=dist)

    elif ptype == "text":
        total = db.query(func.count(PollVote.id)).filter(
            PollVote.poll_id == poll.id, PollVote.text_answer.isnot(None)
        ).scalar() or 0
        responses = db.query(PollVote.text_answer).filter(
            PollVote.poll_id == poll.id, PollVote.text_answer.isnot(None)
        ).order_by(PollVote.voted_at.desc()).limit(50).all()
        base.update(total_votes=total, responses=[r[0] for r in responses])

    return base


def _event_attendee_user_ids(db: DbSession, poll) -> list:
    """Return user_ids with a paid ticket for the poll's event."""
    if not poll.event_id:
        return []
    return [
        r[0] for r in
        db.query(Booking.user_id).filter(
            Booking.event_id == poll.event_id,
            Booking.payment_status == "paid",
        ).distinct().all()
    ]


def notify_event_attendees_of_poll(db: DbSession, poll, results: dict):
    """Notify all users with a paid ticket that a live poll is open."""
    from app.services.poll_events import publish_to_users
    user_ids = _event_attendee_user_ids(db, poll)
    if not user_ids:
        return
    session_obj = poll.session if hasattr(poll, "session") and poll.session else db.query(Session).get(poll.session_id)
    payload = {
        **results,
        "session_id": poll.session_id,
        "session_title": session_obj.title if session_obj else "",
        "event_id": poll.event_id,
    }
    publish_to_users(user_ids, payload)


def notify_event_attendees_poll_closed(db: DbSession, poll):
    """Notify attendees that the poll was closed so the popup can dismiss."""
    from app.services.poll_events import publish_to_users
    user_ids = _event_attendee_user_ids(db, poll)
    if not user_ids:
        return
    publish_to_users(user_ids, {"poll_id": poll.id, "is_active": False, "closed": True})


def build_embed_url(recording_url: str | None) -> str | None:
    """Convert a supported hosted-video URL into its embeddable iframe src."""
    if not recording_url:
        return None
    parsed = urlparse(recording_url)
    host = (parsed.hostname or "").lower()

    if host in ("youtube.com", "www.youtube.com"):
        qs = parse_qs(parsed.query)
        vid = qs.get("v", [None])[0]
        if vid:
            return f"https://www.youtube.com/embed/{vid}"
    if host == "youtu.be":
        vid = parsed.path.lstrip("/").split("/")[0]
        if vid:
            return f"https://www.youtube.com/embed/{vid}"
    if host in ("vimeo.com", "player.vimeo.com"):
        parts = [p for p in parsed.path.split("/") if p]
        vid = parts[-1] if parts else None
        if vid and vid.isdigit():
            return f"https://player.vimeo.com/video/{vid}"
    if host in ("dailymotion.com", "www.dailymotion.com"):
        m = re.search(r"/video/([a-zA-Z0-9]+)", parsed.path)
        if m:
            return f"https://www.dailymotion.com/embed/video/{m.group(1)}"
    if host == "dai.ly":
        vid = parsed.path.lstrip("/").split("/")[0]
        if vid:
            return f"https://www.dailymotion.com/embed/video/{vid}"
    if host in ("twitch.tv", "www.twitch.tv"):
        twitch_parent = urlparse(settings.base_url).hostname or "localhost"
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "videos":
            return f"https://player.twitch.tv/?video={parts[1]}&parent={twitch_parent}"
        if parts:
            return f"https://player.twitch.tv/?channel={parts[0]}&parent={twitch_parent}"
    if host == "clips.twitch.tv":
        twitch_parent = urlparse(settings.base_url).hostname or "localhost"
        slug = parsed.path.lstrip("/").split("/")[0]
        if slug:
            return f"https://clips.twitch.tv/embed?clip={slug}&parent={twitch_parent}"
    if host in ("facebook.com", "www.facebook.com", "fb.watch"):
        from urllib.parse import quote_plus
        return f"https://www.facebook.com/plugins/video.php?href={quote_plus(recording_url)}"
    if host == "streamable.com":
        vid = parsed.path.lstrip("/").split("/")[0]
        if vid:
            return f"https://streamable.com/e/{vid}"
    if host in ("wistia.com", "fast.wistia.com"):
        parts = [p for p in parsed.path.split("/") if p]
        if "medias" in parts:
            idx = parts.index("medias")
            if idx + 1 < len(parts):
                return f"https://fast.wistia.com/embed/medias/{parts[idx + 1]}"
    if host in ("loom.com", "www.loom.com"):
        m = re.search(r"/share/([a-f0-9]+)", parsed.path)
        if m:
            return f"https://www.loom.com/embed/{m.group(1)}"
    if host == "drive.google.com":
        m = re.search(r"/d/([a-zA-Z0-9_-]+)", parsed.path)
        if m:
            return f"https://drive.google.com/file/d/{m.group(1)}/preview"
    return None

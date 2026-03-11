import json

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog


def log_activity(
    db: Session,
    *,
    category: str,
    action: str,
    description: str,
    request: Request | None = None,
    user_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    extra: dict | None = None,
):
    ip = None
    if request and request.client:
        ip = request.client.host

    entry = ActivityLog(
        category=category,
        action=action,
        description=description,
        user_id=user_id,
        target_type=target_type,
        target_id=target_id,
        ip_address=ip,
        extra=json.dumps(extra) if extra else None,
    )
    db.add(entry)
    db.flush()

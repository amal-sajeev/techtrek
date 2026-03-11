import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session as DBSession

from app.database import SessionLocal
from app.models.booking import Booking
from app.models.webhook_log import WebhookLog
from app.services.razorpay import verify_webhook_signature
from app.config import settings
from app.utils import now_ist

log = logging.getLogger(__name__)

router = APIRouter(tags=["webhook"])


@router.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if settings.razorpay_key_secret and signature:
        if not verify_webhook_signature(body, signature, settings.razorpay_key_secret):
            return JSONResponse({"error": "Invalid signature"}, status_code=400)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    event_type = payload.get("event", "")
    event_id = payload.get("id", "")

    db: DBSession = SessionLocal()
    try:
        wl = WebhookLog(
            event_type=event_type,
            razorpay_event_id=event_id,
            payload=body.decode("utf-8", errors="replace"),
            received_at=now_ist(),
            processed=False,
        )
        db.add(wl)
        db.flush()

        entity = payload.get("payload", {}).get("refund", {}).get("entity", {})
        payment_id = entity.get("payment_id", "")
        refund_id = entity.get("id", "")

        if event_type == "refund.processed" and payment_id:
            booking = db.query(Booking).filter(
                Booking.razorpay_payment_id == payment_id
            ).first()
            if booking:
                booking.refund_id = refund_id
                booking.refund_status = "completed"
                booking.refund_processed_at = now_ist()
                wl.processed = True
                log.info("Refund completed for booking %s", booking.booking_ref)

        elif event_type == "refund.failed" and payment_id:
            booking = db.query(Booking).filter(
                Booking.razorpay_payment_id == payment_id
            ).first()
            if booking:
                booking.refund_status = "failed"
                wl.processed = True
                log.warning("Refund failed for booking %s", booking.booking_ref)

        elif event_type == "refund.created" and payment_id:
            booking = db.query(Booking).filter(
                Booking.razorpay_payment_id == payment_id
            ).first()
            if booking:
                booking.refund_id = refund_id
                booking.refund_status = "processing"
                wl.processed = True

        db.commit()
    except Exception:
        db.rollback()
        log.exception("Error processing Razorpay webhook")
        return JSONResponse({"error": "Internal error"}, status_code=500)
    finally:
        db.close()

    return JSONResponse({"status": "ok"})

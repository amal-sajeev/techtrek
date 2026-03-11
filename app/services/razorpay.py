import hmac
import hashlib
import logging

import razorpay

from app.config import settings

log = logging.getLogger(__name__)

client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


def create_order(amount_paise: int, receipt: str) -> dict:
    """Create a Razorpay order. Returns the full order dict from Razorpay."""
    data = {
        "amount": amount_paise,
        "currency": "INR",
        "receipt": receipt,
        "payment_capture": 1,
    }
    order = client.order.create(data=data)
    log.info("Razorpay order created: %s for %d paise", order["id"], amount_paise)
    return order


def verify_payment(order_id: str, payment_id: str, signature: str) -> bool:
    """Verify the Razorpay payment signature using HMAC SHA256."""
    message = f"{order_id}|{payment_id}"
    expected = hmac.new(
        settings.razorpay_key_secret.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify the Razorpay webhook signature using HMAC SHA256."""
    expected = hmac.new(
        secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def process_refund(payment_id: str, amount_paise: int) -> dict | None:
    """Issue a partial refund via Razorpay. Returns refund data or None on failure."""
    try:
        refund = client.payment.refund(payment_id, {"amount": amount_paise, "speed": "normal"})
        log.info("Razorpay refund issued: %s for %d paise", refund.get("id"), amount_paise)
        return refund
    except Exception:
        log.exception("Razorpay refund failed for payment %s", payment_id)
        return None

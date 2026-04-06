"""Validate uploaded image content by inspecting magic bytes, not just Content-Type."""
import io

_MAGIC_SIGNATURES = {
    b'\xff\xd8\xff': 'image/jpeg',
    b'\x89PNG\r\n\x1a\n': 'image/png',
    b'GIF87a': 'image/gif',
    b'GIF89a': 'image/gif',
    b'RIFF': 'image/webp',  # WebP starts with RIFF....WEBP
}

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def detect_image_type(data: bytes) -> str | None:
    """Return the MIME type based on file magic bytes, or None if not a recognized image."""
    if len(data) < 8:
        return None
    for sig, mime in _MAGIC_SIGNATURES.items():
        if data[:len(sig)] == sig:
            if mime == 'image/webp' and data[8:12] != b'WEBP':
                continue
            return mime
    return None


def validate_image_upload(data: bytes) -> str | None:
    """Validate image data and return the detected MIME type, or None if invalid."""
    if len(data) > MAX_UPLOAD_BYTES:
        return None
    detected = detect_image_type(data)
    if detected not in ALLOWED_IMAGE_TYPES:
        return None
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.verify()
    except Exception:
        return None
    return detected

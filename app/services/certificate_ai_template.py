"""
AI-assisted certificate template generation: (1) image model → decorative PNG;
(2) vision model → freeform layer JSON. Server validates/clamps; vision failures
fall back to default_freeform_cert_style_dict() layers while keeping the new background.

Costs two billable OpenAI calls per run; latency is roughly both round-trips sequential.
"""
from __future__ import annotations

import base64
import io
import json
import math
import re
import secrets
from typing import Any

import httpx
from openai import OpenAI
from PIL import Image
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.uploaded_image import UploadedImage
from app.services.certificate import default_freeform_cert_style_dict, should_render_certificate_as_freeform

# Mirrors _build_cert_variable_context keys + static (see certificate.py).
FREEFORM_VARIABLE_ALLOWLIST = frozenset(
    {
        "static",
        "attendee_name",
        "event_name",
        "event_date",
        "venue",
        "cert_id",
        "booking_ref",
        "title_text",
        "subtitle_text",
        "footer_text",
        "signer_name",
        "signer_designation",
        "event_session_title",
        "attending_line",
        "brand_text",
        "details_line",
        "venue_line",
        "cert_id_line",
        "speaker_name",
    }
)

ALLOWED_FONTS = frozenset({
    "arial", "georgia", "times", "verdana", "calibri", "courier",
    "trebuchet", "comic", "palatino", "candara", "tahoma",
    "impact", "garamond", "lucida", "bookantiqua",
})
ALLOWED_ALIGN = frozenset({"left", "center", "right"})
MIN_BOX_PT = 8.0
FONT_SIZE_MIN = 6.0
FONT_SIZE_MAX = 72.0
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
IMAGE_SIZE = "1536x1024"  # landscape, closest common size to A4 landscape aspect


class CertificateAiImageError(Exception):
    """Step 1 (image generation) failed."""


def _finite_float(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def _hex_color(x: Any) -> str | None:
    if x is None:
        return None
    s = str(x).strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", s):
        return s.lower()
    return None


def extract_json_object_from_text(text: str) -> dict[str, Any] | None:
    """Parse model output: optional ```json fences, then json.loads."""
    if not text or not str(text).strip():
        return None
    s = str(text).strip()
    if s.startswith("```"):
        lines = s.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def clamp_layer_box(x_pt: float, y_pt: float, w_pt: float, h_pt: float, W: float, H: float) -> tuple[float, float, float, float]:
    w_pt = max(MIN_BOX_PT, min(w_pt, W))
    h_pt = max(MIN_BOX_PT, min(h_pt, H))
    x_pt = min(max(0.0, x_pt), max(0.0, W - w_pt))
    y_pt = min(max(0.0, y_pt), max(0.0, H - h_pt))
    return x_pt, y_pt, w_pt, h_pt


def validate_and_normalize_layers(raw_layers: Any, page_w: float, page_h: float) -> list[dict[str, Any]]:
    if not isinstance(raw_layers, list):
        return []
    W, H = float(page_w), float(page_h)
    out: list[dict[str, Any]] = []
    for item in raw_layers:
        if not isinstance(item, dict):
            continue
        t = str(item.get("type") or "").lower()
        if t not in ("text", "qr"):
            continue

        x_pt = _finite_float(item.get("xPt"))
        y_pt = _finite_float(item.get("yPt"))
        w_pt = _finite_float(item.get("widthPt"))
        h_pt = _finite_float(item.get("heightPt"))
        rot = _finite_float(item.get("rotation"))
        if x_pt is None or y_pt is None or w_pt is None or h_pt is None:
            continue
        if rot is None:
            rot = 0.0
        x_pt, y_pt, w_pt, h_pt = clamp_layer_box(x_pt, y_pt, w_pt, h_pt, W, H)

        z = item.get("zIndex")
        try:
            z_index = int(z) if z is not None else len(out) + 10
        except (TypeError, ValueError):
            z_index = len(out) + 10

        lid = item.get("id")
        if not lid or not str(lid).strip():
            lid = "L" + secrets.token_hex(4)

        if t == "qr":
            out.append(
                {
                    "id": str(lid),
                    "type": "qr",
                    "zIndex": z_index,
                    "xPt": x_pt,
                    "yPt": y_pt,
                    "widthPt": w_pt,
                    "heightPt": h_pt,
                    "rotation": rot,
                    "showCaption": bool(item.get("showCaption", True)),
                }
            )
            continue

        # text
        var = str(item.get("variable") or "static").strip().lower().replace("-", "_")
        static_text = item.get("text")
        if static_text is None:
            static_text = ""
        static_text = str(static_text)
        if var in ("", "none"):
            var = "static"
        if var == "static":
            if not static_text.strip():
                continue
        elif var not in FREEFORM_VARIABLE_ALLOWLIST:
            continue

        fs = _finite_float(item.get("fontSize"))
        if fs is None:
            fs = 14.0
        fs = min(FONT_SIZE_MAX, max(FONT_SIZE_MIN, fs))

        font = str(item.get("font") or "arial").lower().strip()
        if font not in ALLOWED_FONTS:
            font = "arial"

        color = _hex_color(item.get("color")) or "#0a1628"
        align = str(item.get("align") or "center").lower().strip()
        if align not in ALLOWED_ALIGN:
            align = "center"

        out.append(
            {
                "id": str(lid),
                "type": "text",
                "zIndex": z_index,
                "variable": var,
                "text": static_text if var == "static" else "",
                "xPt": x_pt,
                "yPt": y_pt,
                "widthPt": w_pt,
                "heightPt": h_pt,
                "font": font,
                "fontSize": fs,
                "color": color,
                "bold": bool(item.get("bold", False)),
                "italic": bool(item.get("italic", False)),
                "align": align,
                "underline": bool(item.get("underline", False)),
                "rotation": rot,
            }
        )

    out.sort(key=lambda L: int(L.get("zIndex", 0) or 0))
    for i, L in enumerate(out):
        L["zIndex"] = (i + 1) * 10
    return out


def _fit_to_a4_landscape(data: bytes) -> bytes:
    """Resize the image to exact A4 landscape proportions (842:595) without cropping."""
    try:
        im = Image.open(io.BytesIO(data))
    except Exception:
        return data
    w, h = im.size
    target_ratio = 842.0 / 595.0
    if abs((w / h) - target_ratio) < 0.01:
        return data
    new_w = max(w, int(h * target_ratio))
    new_h = int(new_w / target_ratio)
    im = im.resize((new_w, new_h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _png_bytes_under_limit(data: bytes) -> tuple[bytes, str]:
    """Return (bytes, content_type) within MAX_UPLOAD_BYTES; may re-encode as JPEG."""
    if len(data) <= MAX_UPLOAD_BYTES:
        return data, "image/png"
    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        raise CertificateAiImageError("Generated image could not be processed for size limits.") from None
    for q in (88, 78, 68, 58):
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=q, optimize=True)
        out = buf.getvalue()
        if len(out) <= MAX_UPLOAD_BYTES:
            return out, "image/jpeg"
    raise CertificateAiImageError("Generated image exceeds 5MB after compression.")


def store_upload(db: Session, png_or_jpeg: bytes, content_type: str) -> tuple[int, str]:
    ext = "png" if content_type == "image/png" else "jpg"
    img = UploadedImage(
        filename=f"ai-cert-bg.{ext}",
        content_type=content_type,
        data=png_or_jpeg,
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return img.id, f"/uploads/{img.id}"


def generate_decorated_background(client: OpenAI, settings: Settings, prompt_hint: str) -> bytes:
    base_prompt = (
        "Professional certificate background, landscape orientation, elegant decorative borders and "
        "ornamentation fully inside the frame. Leave generous clear negative space for typography: "
        "a top band for a title, a large central area for a recipient name, lower areas for date and "
        "venue lines, and a clean corner for a QR code. Do not render any real person's name, dates, "
        "certificate numbers, or a QR code in the image — only abstract decoration and empty regions. "
        "Sophisticated but readable; high contrast areas for dark text overlays."
    )
    hint = (prompt_hint or "").strip()
    if hint:
        base_prompt = f"{base_prompt} Additional direction: {hint}"

    try:
        resp = client.images.generate(
            model=settings.openai_cert_image_model,
            prompt=base_prompt,
            size=IMAGE_SIZE,
            quality=settings.openai_cert_image_quality,
            n=1,
            output_format="png",
        )
    except Exception as exc:
        msg = str(exc)
        if "api_key" in msg.lower() or "401" in msg or "unauthorized" in msg.lower():
            raise CertificateAiImageError(
                "OpenAI API key is invalid or expired. Check OPENAI_API_KEY in your .env file."
            ) from exc
        if "rate_limit" in msg.lower() or "429" in msg:
            raise CertificateAiImageError(
                "OpenAI rate limit reached. Please wait a moment and try again."
            ) from exc
        raise CertificateAiImageError(f"Image generation failed: {exc}") from exc

    if not resp.data:
        raise CertificateAiImageError("Image generation returned no data.")

    item = resp.data[0]
    if getattr(item, "b64_json", None):
        return base64.standard_b64decode(item.b64_json)
    url = getattr(item, "url", None)
    if url:
        try:
            r = httpx.get(url, timeout=120.0)
            r.raise_for_status()
            return r.content
        except Exception as exc:
            raise CertificateAiImageError(f"Could not download generated image: {exc}") from exc
    raise CertificateAiImageError("Image response had neither b64_json nor url.")


def _summarize_existing_layers(existing_layers: list[dict[str, Any]]) -> str:
    """Build a short textual summary of existing layers for the AI prompt."""
    if not existing_layers:
        return ""
    parts: list[str] = []
    for L in existing_layers:
        t = str(L.get("type", "")).lower()
        if t == "qr":
            parts.append(
                f"  - QR code at xPt={L.get('xPt')}, yPt={L.get('yPt')}, "
                f"widthPt={L.get('widthPt')}, heightPt={L.get('heightPt')}"
            )
        elif t == "text":
            var = L.get("variable", "static")
            parts.append(
                f"  - Text ({var}) at xPt={L.get('xPt')}, yPt={L.get('yPt')}, "
                f"widthPt={L.get('widthPt')}, heightPt={L.get('heightPt')}"
            )
    if not parts:
        return ""
    return (
        "\n\nExisting layers on the canvas (preserve their positions and avoid overlapping them):\n"
        + "\n".join(parts)
    )


def _layout_system_user_parts(
    page_w: float,
    page_h: float,
    existing_layers: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    vars_sorted = ", ".join(sorted(FREEFORM_VARIABLE_ALLOWLIST - {"static"}))
    system = (
        "You output only valid JSON for a certificate overlay editor. "
        "Coordinate system: ReportLab PDF points, origin at bottom-left of the page. "
        "xPt and yPt are the lower-left corner of each layer's box; y increases upward. "
        "rotation is in degrees, positive = counterclockwise (same as PDF typical usage in this app). "
        "The page size is fixed — do not use pixel coordinates from the image; map visually to this page."
    )

    has_qr = any(
        str(L.get("type", "")).lower() == "qr" for L in (existing_layers or [])
    )
    qr_instruction = (
        "IMPORTANT: The canvas already has a QR code. You MUST include a QR layer in your response "
        "at the same position and size as the existing one. Do NOT omit it.\n"
        if has_qr
        else ""
    )

    existing_summary = _summarize_existing_layers(existing_layers or [])

    user = (
        f"Page size: {page_w} points wide × {page_h} points tall (landscape certificate).\n"
        + qr_instruction
        + "Analyze the attached certificate background image and propose text and QR overlay layers.\n"
        "Return a single JSON object with top-level key \"layers\" (array). Each element:\n"
        '- type \"text\": variable (one of: static, '
        + vars_sorted
        + '), for static text also include non-empty "text"; '
        "xPt, yPt, widthPt, heightPt, fontSize (6–72), optional font (arial|georgia|times|verdana|calibri|courier|trebuchet|palatino|garamond|tahoma|impact|lucida|bookantiqua|candara|comic), "
        'color as #RRGGBB, align (left|center|right), optional bold/italic/underline booleans, rotation.\n'
        '- type \"qr\": xPt, yPt, widthPt, heightPt (square recommended), rotation, optional showCaption boolean.\n'
        "Use only these types. Prefer variable bindings over static text except for minor labels. "
        "Example: {\"layers\":[{\"type\":\"text\",\"variable\":\"title_text\",\"xPt\":121,\"yPt\":388,\"widthPt\":600,\"heightPt\":40,\"fontSize\":28,\"color\":\"#0a1628\",\"bold\":true,\"align\":\"center\",\"rotation\":0}]}"
        + existing_summary
    )
    return system, user


def _ensure_existing_qr_preserved(
    ai_layers: list[dict[str, Any]],
    existing_layers: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """If the original canvas had QR codes but the AI didn't return any, carry them over."""
    if not existing_layers:
        return ai_layers
    old_qrs = [L for L in existing_layers if str(L.get("type", "")).lower() == "qr"]
    if not old_qrs:
        return ai_layers
    new_has_qr = any(L.get("type") == "qr" for L in ai_layers)
    if new_has_qr:
        return ai_layers
    for qr in old_qrs:
        ai_layers.append({
            "id": qr.get("id") or "L" + secrets.token_hex(4),
            "type": "qr",
            "zIndex": (len(ai_layers) + 1) * 10,
            "xPt": float(qr.get("xPt", 0)),
            "yPt": float(qr.get("yPt", 0)),
            "widthPt": float(qr.get("widthPt", 80)),
            "heightPt": float(qr.get("heightPt", 80)),
            "rotation": float(qr.get("rotation", 0)),
            "showCaption": bool(qr.get("showCaption", True)),
        })
    return ai_layers


def propose_layers_from_image(
    client: OpenAI,
    settings: Settings,
    image_bytes: bytes,
    page_w: float,
    page_h: float,
    image_content_type: str = "image/png",
    existing_layers: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """
    Vision call → validated layers. Returns (layers, used_fallback).
    used_fallback True when parsing/validation yielded no valid freeform doc and defaults were applied.
    """
    defaults = default_freeform_cert_style_dict()
    fallback_layers = list(defaults.get("layers") or [])

    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    mime = "image/png" if image_content_type == "image/png" else "image/jpeg"
    system, user_text = _layout_system_user_parts(page_w, page_h, existing_layers=existing_layers)
    content: list[dict[str, Any]] = [
        {"type": "text", "text": user_text},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]

    base_kwargs: dict[str, Any] = {
        "model": settings.openai_cert_layout_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
    }
    try:
        comp = client.chat.completions.create(**base_kwargs, response_format={"type": "json_object"})
    except Exception:
        try:
            comp = client.chat.completions.create(**base_kwargs)
        except Exception:
            return fallback_layers, True

    msg = comp.choices[0].message if comp.choices else None
    raw_text = (getattr(msg, "content", None) or "").strip()
    parsed = extract_json_object_from_text(raw_text)
    if not parsed:
        return fallback_layers, True
    raw_layers = parsed.get("layers")
    validated = validate_and_normalize_layers(raw_layers, page_w, page_h)
    if not validated:
        return fallback_layers, True

    validated = _ensure_existing_qr_preserved(validated, existing_layers)
    return validated, False


def build_full_cert_style(upload_url: str, layers: list[dict[str, Any]], page_w: float, page_h: float) -> dict[str, Any]:
    defaults = default_freeform_cert_style_dict()
    style: dict[str, Any] = {
        "version": defaults["version"],
        "layout": "freeform",
        "page": {"widthPt": float(page_w), "heightPt": float(page_h)},
        "border_style": "none",
        "border_width": 0.25,
        "border_color_primary": "",
        "border_color_secondary": "",
        "border_color_tertiary": "",
        "bg_size": "cover",
        "bg_offset_x": 0.0,
        "bg_offset_y": 0.0,
        "background_image_url": upload_url,
        "layers": layers,
    }
    if not should_render_certificate_as_freeform(style):
        style["layers"] = list(defaults.get("layers") or [])
    return style


def run_ai_certificate_template_pipeline(
    db: Session,
    settings: Settings,
    prompt_hint: str = "",
    existing_layers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not (settings.openai_api_key or "").strip():
        raise CertificateAiImageError("OPENAI_API_KEY is not configured.")

    client = OpenAI(api_key=settings.openai_api_key)
    png_bytes = generate_decorated_background(client, settings, prompt_hint)
    png_bytes = _fit_to_a4_landscape(png_bytes)
    sized, ctype = _png_bytes_under_limit(png_bytes)
    _upload_id, upload_url = store_upload(db, sized, ctype)

    defaults = default_freeform_cert_style_dict()
    page = defaults.get("page") or {}
    pw = float(page.get("widthPt", 842))
    ph = float(page.get("heightPt", 595))

    layers, layout_fallback = propose_layers_from_image(
        client, settings, sized, pw, ph, image_content_type=ctype,
        existing_layers=existing_layers,
    )
    cert_style = build_full_cert_style(upload_url, layers, pw, ph)

    return {
        "cert_style": cert_style,
        "upload_url": upload_url,
        "layout_fallback": layout_fallback,
    }

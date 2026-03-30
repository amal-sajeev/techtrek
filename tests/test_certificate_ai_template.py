"""Unit tests for certificate AI template JSON parsing and layer validation."""

from app.services.certificate import should_render_certificate_as_freeform
from app.services.certificate_ai_template import (
    build_full_cert_style,
    extract_json_object_from_text,
    validate_and_normalize_layers,
)

PW, PH = 842.0, 595.0


def test_extract_json_strips_fences():
    raw = '```json\n{"layers": [{"type": "text", "variable": "title_text", "xPt": 0, "yPt": 0, "widthPt": 100, "heightPt": 20, "fontSize": 12}]}\n```'
    obj = extract_json_object_from_text(raw)
    assert obj is not None
    assert "layers" in obj


def test_extract_json_invalid_returns_none():
    assert extract_json_object_from_text("not json") is None
    assert extract_json_object_from_text("") is None


def test_validate_clamps_negative_and_oversize():
    layers = [
        {
            "type": "text",
            "variable": "title_text",
            "xPt": -50,
            "yPt": -20,
            "widthPt": 9000,
            "heightPt": 9000,
            "fontSize": 12,
            "color": "#FF00AA",
        }
    ]
    out = validate_and_normalize_layers(layers, PW, PH)
    assert len(out) == 1
    L = out[0]
    assert L["xPt"] >= 0
    assert L["yPt"] >= 0
    assert L["widthPt"] <= PW
    assert L["heightPt"] <= PH
    assert L["xPt"] + L["widthPt"] <= PW + 0.001
    assert L["yPt"] + L["heightPt"] <= PH + 0.001


def test_validate_drops_unknown_variable():
    layers = [
        {
            "type": "text",
            "variable": "made_up_field",
            "xPt": 10,
            "yPt": 10,
            "widthPt": 100,
            "heightPt": 30,
            "fontSize": 14,
        }
    ]
    assert validate_and_normalize_layers(layers, PW, PH) == []


def test_validate_font_size_clamped():
    layers = [
        {
            "type": "text",
            "variable": "title_text",
            "xPt": 10,
            "yPt": 10,
            "widthPt": 200,
            "heightPt": 40,
            "fontSize": 200,
        }
    ]
    out = validate_and_normalize_layers(layers, PW, PH)
    assert out[0]["fontSize"] == 72


def test_validate_qr_layer():
    layers = [
        {
            "type": "qr",
            "xPt": 700,
            "yPt": 50,
            "widthPt": 70,
            "heightPt": 70,
            "rotation": 0,
        }
    ]
    out = validate_and_normalize_layers(layers, PW, PH)
    assert len(out) == 1
    assert out[0]["type"] == "qr"


def test_build_full_cert_style_empty_layers_uses_defaults():
    style = build_full_cert_style("/uploads/99", [], PW, PH)
    assert style["background_image_url"] == "/uploads/99"
    assert should_render_certificate_as_freeform(style)
    assert len(style["layers"]) > 0

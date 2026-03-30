"""Tests for platform metrics PDF + AI narrative helpers."""

from unittest.mock import MagicMock, patch

from app.services.admin_metrics_bundle import metrics_report_kind_from_params
from app.services.metrics_report_ai import (
    build_fallback_narrative,
    finalize_metrics_narrative,
    metrics_numbers_digest,
    normalize_narrative,
    run_metrics_report_ai,
)
from app.services.metrics_report_pdf import generate_platform_metrics_report_pdf


def _minimal_bundle():
    return {
        "generated_at": "2026-03-30T12:00:00",
        "filter_summary": ["Event: All events", "College: All colleges"],
        "total_users": 42,
        "total_revenue": 1000.0,
        "total_bookings": 5,
        "checkin_rate": 20.0,
        "avg_rating": 4.2,
        "total_feedback": 3,
        "event_statuses": {"published": 2, "draft": 1},
        "booking_trend": [{"label": "Jan 2026", "count": 2}],
        "revenue_trend": [{"label": "Jan 2026", "value": 500.0}],
        "booking_statuses": {"paid": 5},
        "rating_dist": {5: 2, 4: 1},
        "reg_trend": [],
        "top_specializations": [],
        "yos_dist": [],
        "auth_counts": {"oauth": 10, "password": 32},
        "role_counts": {"active": 42, "admins": 1, "supervisors": 0, "deleted": 0},
        "top_user_colleges": [],
        "seat_distribution": {"segments": [], "unsold": 0, "total_capacity": 0},
        "sessions_per_event": [],
        "events_by_city": [],
        "top_cities": [],
        "top_colleges": [],
        "top_events_by_bookings": [],
        "top_events_by_waitlist": [],
        "revenue_by_event": [],
        "revenue_by_seat_type": [],
        "refund_stats": {"count": 0, "total": 0.0, "cancel_fees": 0.0, "shared": 0},
        "coupon_stats": {"total": 0, "active": 0, "redeemed": 0, "pct": 0},
        "best_sessions": [],
        "best_speakers": [],
        "feedback_stats": {"submitted": 3, "rate": 10.0, "with_comments": 1, "featured": 0},
        "feedback_disp": {},
        "poll_stats": {},
        "checkin_hours": [],
        "waitlist_by_event": [],
        "waitlist_stats": {},
        "speaker_stats": {},
        "recording_stats": {},
        "venue_stats": {},
        "subscriber_trend": [],
        "activity_by_cat": [],
        "newsletter_stats": {},
        "webhook_stats": {},
        "alert_stats": {},
        "single_event_selected": False,
        "report_kind": "quarterly_brief",
        "filter_params": {
            "date_from": "",
            "date_to": "",
            "event_id": "",
            "college_id": "",
        },
    }


def test_metrics_numbers_digest_keys():
    d = metrics_numbers_digest(_minimal_bundle())
    assert d["total_users"] == 42
    assert d["rating_dist"]["5"] == 2
    assert d["report_kind"] == "quarterly_brief"
    assert d["filter_params"]["event_id"] == ""


def test_metrics_report_kind_from_params():
    assert metrics_report_kind_from_params() == "quarterly_brief"
    assert metrics_report_kind_from_params(event_id="1") == "focused_report"
    assert metrics_report_kind_from_params(date_from="2026-01-01") == "focused_report"
    assert metrics_report_kind_from_params(college_id=" 2 ") == "focused_report"


def test_fallback_quarterly_brief_executive_mentions_full_history():
    b = _minimal_bundle()
    n = build_fallback_narrative(b)
    es = (n.get("executive_summary") or "").lower()
    assert "headlines" in es
    assert "full historical activity" in es
    assert "calendar quarter" in es


def test_fallback_focused_report_scope_and_within_scope():
    b = _minimal_bundle()
    b["report_kind"] = "focused_report"
    b["filter_summary"] = ["Event: Workshop A", "College: Test College"]
    b["filter_params"] = {"date_from": "", "date_to": "", "event_id": "3", "college_id": ""}
    n = build_fallback_narrative(b)
    assert "scope" in (n.get("executive_summary") or "").lower()
    assert "workshop a" in (n.get("executive_summary") or "").lower()
    overview = next(s for s in n["sections"] if s.get("tab") == "overview")
    assert "within this scope" in (overview.get("body_markdown") or "").lower()


def test_pdf_without_narrative_starts_with_pdf_magic():
    pdf = generate_platform_metrics_report_pdf(_minimal_bundle(), None)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 5000


def test_finalize_fallback_includes_analysis_and_pdf_still_valid():
    bundle = _minimal_bundle()
    n = finalize_metrics_narrative(bundle, None)
    assert n["narrative_source"] == "fallback"
    assert "registered users" in (n.get("executive_summary") or "").lower()
    assert any((s.get("body_markdown") or "").strip() for s in n.get("sections") or [])
    pdf = generate_platform_metrics_report_pdf(bundle, n)
    assert pdf.startswith(b"%PDF")


def test_normalize_narrative_accepts_body_alias():
    raw = {"executive_summary": "x", "sections": [{"tab": "overview", "title": "O", "body": "Hello."}]}
    n = normalize_narrative(raw)
    assert n and n["sections"][0]["body_markdown"] == "Hello."


def test_finalize_uses_fallback_when_ai_empty():
    bundle = _minimal_bundle()
    n = finalize_metrics_narrative(bundle, {"executive_summary": "   ", "sections": []})
    assert n["narrative_source"] == "fallback"
    assert "42" in n["executive_summary"]
    assert n.get("ai_diagnostic")


def test_finalize_fallback_includes_ai_failure_reason():
    bundle = _minimal_bundle()
    n = finalize_metrics_narrative(bundle, None, ai_failure_reason="Model not found")
    assert n["narrative_source"] == "fallback"
    assert n.get("ai_diagnostic") == "Model not found"


def test_finalize_prefers_openai_when_substance():
    bundle = _minimal_bundle()
    ai = {"executive_summary": "We have **42** users.", "sections": [{"tab": "overview", "title": "O", "body_markdown": "Ok."}]}
    n = finalize_metrics_narrative(bundle, ai)
    assert n["narrative_source"] == "openai"
    assert "42" in n["executive_summary"]


def test_run_metrics_report_ai_returns_none_without_key():
    s = MagicMock()
    s.openai_api_key = ""
    s.openai_metrics_report_model = "gpt-5.4-mini"
    out = run_metrics_report_ai(s, _minimal_bundle())
    assert out.narrative is None
    assert out.failure_reason and "OPENAI_API_KEY" in out.failure_reason


def test_run_metrics_report_ai_with_mocked_openai():
    draft = {
        "executive_summary": "Total **users** is 42.",
        "sections": [{"tab": "overview", "title": "Overview", "body_markdown": "Test."}],
        "figure_notes": {},
    }
    verify = {"approved": True, "issues": [], "revised": draft}

    mock_msg = MagicMock()
    mock_msg.content = "{}"  # non-empty so _call_json_model calls extract_json_object_from_text (patched)

    def fake_create(**kwargs):
        comp = MagicMock()
        comp.choices = [MagicMock(message=mock_msg)]
        return comp

    s = MagicMock()
    s.openai_api_key = "sk-test"
    s.openai_metrics_report_model = "gpt-5.4-mini"

    with patch("app.services.metrics_report_ai.OpenAI") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = fake_create
        with patch(
            "app.services.metrics_report_ai.extract_json_object_from_text",
            side_effect=[draft, verify],
        ):
            out = run_metrics_report_ai(s, _minimal_bundle())
    assert out.narrative is not None
    assert out.failure_reason is None
    assert out.narrative.get("executive_summary")

"""Two-pass OpenAI narrative for platform metrics PDF (draft + verification)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from app.config import Settings
from app.services.certificate_ai_template import extract_json_object_from_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetricsReportAiResult:
    """OpenAI metrics narrative run; check failure_reason when narrative is None."""

    narrative: dict[str, Any] | None
    failure_reason: str | None = None


def _compact_bundle_json(bundle: dict) -> str:
    """Serialize bundle for the model; include filter_params so the model knows applied scope."""
    return json.dumps(bundle, default=str, separators=(",", ":"))


def metrics_numbers_digest(bundle: dict) -> dict[str, Any]:
    """Small factual snapshot for pass-2 verification."""
    return {
        "total_users": bundle.get("total_users"),
        "total_revenue": bundle.get("total_revenue"),
        "total_bookings": bundle.get("total_bookings"),
        "checkin_rate": bundle.get("checkin_rate"),
        "avg_rating": bundle.get("avg_rating"),
        "total_feedback": bundle.get("total_feedback"),
        "event_statuses": bundle.get("event_statuses"),
        "booking_statuses": bundle.get("booking_statuses"),
        "rating_dist": {str(k): v for k, v in (bundle.get("rating_dist") or {}).items()},
        "revenue_by_event": bundle.get("revenue_by_event"),
        "top_events_by_bookings": bundle.get("top_events_by_bookings"),
        "seat_distribution": bundle.get("seat_distribution"),
        "refund_stats": bundle.get("refund_stats"),
        "coupon_stats": bundle.get("coupon_stats"),
        "feedback_stats": bundle.get("feedback_stats"),
        "waitlist_stats": bundle.get("waitlist_stats"),
        "venue_stats": bundle.get("venue_stats"),
        "filter_summary": bundle.get("filter_summary"),
        "filter_params": bundle.get("filter_params"),
        "report_kind": bundle.get("report_kind"),
        "generated_at": bundle.get("generated_at"),
        "single_event_selected": bundle.get("single_event_selected"),
    }


def _call_json_model(
    client: OpenAI, model: str, system: str, user: str
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Try chat completion without then with json_object mode.
    Returns (parsed_dict, None) on success, or (None, error_detail).
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    last_detail: str | None = None
    for use_json_object in (False, True):
        try:
            call_kw = dict(kwargs)
            if use_json_object:
                call_kw["response_format"] = {"type": "json_object"}
            comp = client.chat.completions.create(**call_kw)
        except Exception as e:
            last_detail = str(e)
            logger.warning(
                "metrics_report_ai: OpenAI chat.completions.create failed "
                "(model=%r, json_object_mode=%s): %s",
                model,
                use_json_object,
                e,
                exc_info=logger.isEnabledFor(logging.DEBUG),
            )
            continue
        msg = comp.choices[0].message if comp.choices else None
        raw = (getattr(msg, "content", None) or "").strip()
        if not raw:
            last_detail = "Assistant returned empty message content"
            logger.warning(
                "metrics_report_ai: empty content (model=%r, json_object_mode=%s)",
                model,
                use_json_object,
            )
            continue
        parsed = extract_json_object_from_text(raw)
        if parsed:
            return parsed, None
        last_detail = f"No JSON object in model output (response length {len(raw)} chars)"
        logger.warning(
            "metrics_report_ai: %s; preview=%r",
            last_detail,
            raw[:280],
        )
    return None, last_detail or "OpenAI metrics narrative: all attempts failed"


PASS1_SYSTEM = """You are an analytics report writer for an event ticketing platform (TechTrek).
You MUST only use quantitative facts that appear in the provided JSON metrics bundle.
Do not invent KPIs, counts, or percentages. Use Indian English; currency is INR (use Rs. or INR in text).
Output a single JSON object with this shape:
{
  "executive_summary": "2-4 sentences markdown",
  "sections": [
    {"tab": "overview", "title": "string", "body_markdown": "string"},
    {"tab": "users", "title": "string", "body_markdown": "string"},
    {"tab": "events", "title": "string", "body_markdown": "string"},
    {"tab": "revenue", "title": "string", "body_markdown": "string"},
    {"tab": "feedback", "title": "string", "body_markdown": "string"},
    {"tab": "sessions", "title": "string", "body_markdown": "string"},
    {"tab": "system", "title": "string", "body_markdown": "string"}
  ],
  "figure_notes": {
    "overview_bookings_trend": "one short caption",
    "overview_revenue_trend": "one short caption",
    "overview_booking_status": "one short caption",
    "overview_event_status": "one short caption"
  }
}
You may add more keys to figure_notes for other figures if helpful. Keep body_markdown under ~250 words per section."""


PASS2_SYSTEM = """You verify an analytics draft against authoritative metrics JSON.
Compare every number, percentage, and count mentioned in the draft to the digest.
Return JSON only:
{
  "approved": true or false,
  "issues": ["brief issue strings"],
  "revised": { same shape as draft: executive_summary, sections, figure_notes }
}
If approved is true, revised should repeat the draft unchanged or with trivial wording fixes.
If false, revised must correct all numerical inaccuracies using ONLY the digest; remove unverifiable claims."""


def _pass1_user_instructions(bundle: dict) -> str:
    rk = bundle.get("report_kind") or "quarterly_brief"
    if rk == "focused_report":
        return (
            "\n\nREPORT_MODE:\n"
            "focused_report — Write a focused analytical report. Open the executive summary with the applied "
            "filter scope (use filter_summary / filter_params). In each section, interpret figures only within "
            "that scope; do not claim platform-wide totals unless the filters imply it.\n"
        )
    return (
        "\n\nREPORT_MODE:\n"
        "quarterly_brief — Write as a leadership quarterly brief (concise, headline KPIs, risks where data "
        "supports it). The bundle is full-platform, all historical periods: do **not** imply numbers are only "
        "for one calendar quarter. Say clearly that scope is all-time / full platform when you mention time.\n"
    )


def normalize_narrative(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Map alternate JSON keys and coerce types so PDF rendering sees consistent fields."""
    if not isinstance(raw, dict):
        return None
    es = raw.get("executive_summary") or raw.get("executiveSummary") or ""
    if not isinstance(es, str):
        es = str(es) if es is not None else ""
    secs_in = raw.get("sections")
    if not isinstance(secs_in, list):
        secs_in = []
    out_sections: list[dict[str, str]] = []
    for s in secs_in:
        if not isinstance(s, dict):
            continue
        tab = (s.get("tab") or s.get("Tab") or "").strip()
        title = (s.get("title") or s.get("Title") or "").strip() or (tab.title() if tab else "Section")
        body = (
            s.get("body_markdown")
            or s.get("bodyMarkdown")
            or s.get("body")
            or s.get("markdown")
            or s.get("analysis")
            or s.get("content")
            or ""
        )
        if not isinstance(body, str):
            body = str(body) if body else ""
        out_sections.append({"tab": tab, "title": title, "body_markdown": body})
    fn = raw.get("figure_notes")
    if not isinstance(fn, dict):
        fn = {}
    return {"executive_summary": es, "sections": out_sections, "figure_notes": fn}


def _narrative_has_substance(n: dict[str, Any]) -> bool:
    if (n.get("executive_summary") or "").strip():
        return True
    for sec in n.get("sections") or []:
        if isinstance(sec, dict) and (sec.get("body_markdown") or "").strip():
            return True
    return False


def build_fallback_narrative(bundle: dict[str, Any]) -> dict[str, Any]:
    """Deterministic commentary from bundle KPIs so PDFs always include analysis without OpenAI."""
    kind = bundle.get("report_kind") or "quarterly_brief"
    is_focused = kind == "focused_report"
    fs = "; ".join(str(x) for x in (bundle.get("filter_summary") or []))[:800]
    tu = int(bundle.get("total_users") or 0)
    tr = float(bundle.get("total_revenue") or 0)
    tb = int(bundle.get("total_bookings") or 0)
    cr = bundle.get("checkin_rate")
    cr_s = f"{float(cr):.1f}" if cr is not None else "0"
    ar = bundle.get("avg_rating")
    ar_s = f"{float(ar):.2f}" if ar is not None else "0"
    tf = int(bundle.get("total_feedback") or 0)

    kpi_block = (
        f"There are **{tu:,}** registered users, **Rs. {tr:,.0f}** total paid-booking revenue, "
        f"**{tb:,}** paid bookings, a **{cr_s}%** check-in rate, and average rating **{ar_s}**/5 "
        f"from **{tf}** feedback row(s) in scope."
    )

    if is_focused:
        exec_bits = [f"**Scope:** {fs}", kpi_block]
    else:
        exec_bits = [
            f"**Headlines:** {kpi_block}",
        ]
    if bundle.get("single_event_selected"):
        exec_bits.append(
            "Filters target a **single event**; platform-wide revenue trend may be replaced by seat mix."
        )
    executive_summary = "\n\n".join(exec_bits)

    es = bundle.get("event_statuses") or {}
    bs = bundle.get("booking_statuses") or {}
    bt = bundle.get("booking_trend") or []
    rt = bundle.get("revenue_trend") or []

    if not is_focused:
        mom: list[str] = []
        if len(bt) >= 2:
            mom.append(
                f"**Booking momentum (by labelled period):** **{bt[0].get('label')}** "
                f"({int(bt[0].get('count') or 0)}) → **{bt[-1].get('label')}** ({int(bt[-1].get('count') or 0)})."
            )
        elif bt:
            mom.append(
                f"**Latest booking period:** **{bt[-1].get('label')}** with **{int(bt[-1].get('count') or 0)}** bookings."
            )
        if len(rt) >= 2:
            mom.append(
                f"**Revenue momentum:** **{rt[0].get('label')}** (Rs. {float(rt[0].get('value') or 0):,.0f}) → "
                f"**{rt[-1].get('label')}** (Rs. {float(rt[-1].get('value') or 0):,.0f})."
            )
        if mom:
            executive_summary += "\n\n" + "\n\n".join(mom)
        executive_summary += (
            "\n\n**Time scope:** This document uses a **quarterly-brief format** for leadership reading, but "
            "all figures aggregate **full historical activity** in the product (platform-wide), **not** a single "
            "calendar quarter. Apply date, event, or college filters on the Metrics page to narrow the slice."
        )
    overview_parts: list[str] = []
    if len(bt) >= 2:
        overview_parts.append(
            f"Bookings move from **{bt[0].get('label')}** ({int(bt[0].get('count') or 0)}) "
            f"to **{bt[-1].get('label')}** ({int(bt[-1].get('count') or 0)})."
        )
    elif bt:
        overview_parts.append(
            f"Latest labelled period: **{bt[-1].get('label')}** with **{int(bt[-1].get('count') or 0)}** bookings."
        )
    if len(rt) >= 2:
        overview_parts.append(
            f"Revenue from **{rt[0].get('label')}** (Rs. {float(rt[0].get('value') or 0):,.0f}) "
            f"to **{rt[-1].get('label')}** (Rs. {float(rt[-1].get('value') or 0):,.0f})."
        )
    elif rt:
        overview_parts.append(
            f"Latest revenue period **{rt[-1].get('label')}**: Rs. {float(rt[-1].get('value') or 0):,.0f}."
        )
    if es:
        overview_parts.append(
            "Event statuses: " + ", ".join(f"**{k}** ({int(v)})" for k, v in es.items()) + "."
        )
    if bs:
        overview_parts.append(
            "Booking payment statuses: " + ", ".join(f"**{k}** ({int(v)})" for k, v in bs.items()) + "."
        )
    overview_body = "\n\n".join(overview_parts) or "Interpret booking and revenue trends using the figures below."

    ac = bundle.get("auth_counts") or {}
    rc = bundle.get("role_counts") or {}
    reg = bundle.get("reg_trend") or []
    users_parts: list[str] = []
    if ac:
        users_parts.append(
            f"Auth: **OAuth {int(ac.get('oauth') or 0)}**, **password {int(ac.get('password') or 0)}**."
        )
    if rc:
        users_parts.append(
            f"Roles — active **{int(rc.get('active') or 0)}**, admins **{int(rc.get('admins') or 0)}**, "
            f"supervisors **{int(rc.get('supervisors') or 0)}**, deleted **{int(rc.get('deleted') or 0)}**."
        )
    if len(reg) >= 2:
        users_parts.append(
            f"Registrations **{reg[0].get('label')}** ({int(reg[0].get('count') or 0)}) → "
            f"**{reg[-1].get('label')}** ({int(reg[-1].get('count') or 0)})."
        )
    users_body = "\n\n".join(users_parts) or "See registration, year-of-study, auth, and role visuals."

    ebc = bundle.get("events_by_city") or []
    teb = bundle.get("top_events_by_bookings") or []
    spe = bundle.get("sessions_per_event") or []
    events_parts: list[str] = []
    if ebc:
        topc = ebc[0]
        events_parts.append(
            f"Top city by events listed: **{topc.get('name')}** ({int(topc.get('count') or 0)})."
        )
    if teb:
        top_ev = teb[0]
        events_parts.append(
            f"Most paid bookings: **{str(top_ev.get('name', ''))[:70]}** ({int(top_ev.get('count') or 0)})."
        )
    if spe:
        top_s = max(spe, key=lambda x: int(x.get("count") or 0))
        events_parts.append(
            f"Most sessions on one event: **{str(top_s.get('name', ''))[:60]}** "
            f"({int(top_s.get('count') or 0)} sessions)."
        )
    events_body = "\n\n".join(events_parts) or "Geography and demand tables summarise event activity."

    rev_parts: list[str] = []
    if bundle.get("single_event_selected"):
        sd = bundle.get("seat_distribution") or {}
        rev_parts.append(
            f"Seat view: **{int(sd.get('unsold') or 0)}** seats marked unsold in the bundle; see donut for mix."
        )
    rbe = bundle.get("revenue_by_event") or []
    if rbe:
        top = rbe[0]
        rev_parts.append(
            f"Top event revenue: **{str(top.get('name', ''))[:55]}** — "
            f"Rs. **{float(top.get('revenue') or 0):,.0f}** ({int(top.get('bookings') or 0)} bookings)."
        )
    rbs = bundle.get("revenue_by_seat_type") or []
    if rbs:
        top_st = max(rbs, key=lambda x: float(x.get("revenue") or 0))
        rev_parts.append(
            f"Strongest seat type by revenue: **{top_st.get('display_label') or top_st.get('type', '')}**."
        )
    rs = bundle.get("refund_stats") or {}
    if int(rs.get("count") or 0):
        rev_parts.append(
            f"Refunds: **{int(rs.get('count') or 0)}** for Rs. **{float(rs.get('total') or 0):,.0f}**."
        )
    revenue_body = "\n\n".join(rev_parts) or "Revenue tables and trend chart carry the detail."

    fbs = bundle.get("feedback_stats") or {}
    feedback_parts: list[str] = []
    if fbs:
        feedback_parts.append(
            f"**{int(fbs.get('submitted') or 0)}** submissions, **{fbs.get('rate', 0)}%** response rate, "
            f"**{int(fbs.get('with_comments') or 0)}** with comments."
        )
    bsess = bundle.get("best_sessions") or []
    if bsess:
        b = bsess[0]
        feedback_parts.append(
            f"Top session by average: **{str(b.get('title', ''))[:50]}** "
            f"(avg **{b.get('avg')}**, n={b.get('count')})."
        )
    feedback_body = "\n\n".join(feedback_parts) or "Feedback counts and best sessions are tabulated below."

    ch = bundle.get("checkin_hours") or []
    vs = bundle.get("venue_stats") or {}
    sess_parts: list[str] = []
    if ch:
        peak = max(ch, key=lambda x: int(x.get("count") or 0))
        sess_parts.append(
            f"Busiest check-in hour: **{peak.get('hour')}**:00 ({int(peak.get('count') or 0)} check-ins)."
        )
    if vs:
        sess_parts.append(
            f"Seats: **{int(vs.get('total_seats') or 0)}** total, **{int(vs.get('bookable') or 0)}** bookable, "
            f"**{int(vs.get('booked') or 0)}** booked — **{vs.get('occupancy', 0)}%** occupancy."
        )
    sessions_body = "\n\n".join(sess_parts) or "Check-in hourly chart and venue table explain operations load."

    ns = bundle.get("newsletter_stats") or {}
    wh = bundle.get("webhook_stats") or {}
    abc = bundle.get("activity_by_cat") or []
    st = bundle.get("subscriber_trend") or []
    sys_parts: list[str] = []
    if ns:
        sys_parts.append(
            f"Newsletter: **{int(ns.get('subscribers') or 0)}** subscribers, **{int(ns.get('sent') or 0)}** sends."
        )
    if wh and int(wh.get("total") or 0):
        sys_parts.append(
            f"Webhooks: **{int(wh.get('processed') or 0)}** / **{int(wh.get('total') or 0)}** processed "
            f"({wh.get('rate', 0)}%)."
        )
    if abc:
        top_a = abc[0]
        sys_parts.append(
            f"Top activity category: **{top_a.get('category')}** ({int(top_a.get('count') or 0)} log rows)."
        )
    if len(st) >= 2:
        sys_parts.append(f"Subscribers **{st[0].get('label')}** → **{st[-1].get('label')}** in the trend chart.")
    system_body = "\n\n".join(sys_parts) or "Subscriber and activity charts summarise background traffic."

    if is_focused:
        def _within_scope(text: str, default: str) -> str:
            t = text.strip() if (text or "").strip() else default
            return f"**Within this scope:** {t}"

        overview_body = _within_scope(
            overview_body, "Interpret booking and revenue trends using the figures below."
        )
        users_body = _within_scope(users_body, "See registration, year-of-study, auth, and role visuals.")
        events_body = _within_scope(events_body, "Geography and demand tables summarise event activity.")
        revenue_body = _within_scope(revenue_body, "Revenue tables and trend chart carry the detail.")
        feedback_body = _within_scope(feedback_body, "Feedback counts and best sessions are tabulated below.")
        sessions_body = _within_scope(sessions_body, "Check-in hourly chart and venue table explain operations load.")
        system_body = _within_scope(system_body, "Subscriber and activity charts summarise background traffic.")

    sections = [
        {"tab": "overview", "title": "Overview", "body_markdown": overview_body},
        {"tab": "users", "title": "Users", "body_markdown": users_body},
        {"tab": "events", "title": "Events", "body_markdown": events_body},
        {"tab": "revenue", "title": "Revenue", "body_markdown": revenue_body},
        {"tab": "feedback", "title": "Feedback", "body_markdown": feedback_body},
        {"tab": "sessions", "title": "Sessions & operations", "body_markdown": sessions_body},
        {"tab": "system", "title": "System", "body_markdown": system_body},
    ]
    return {"executive_summary": executive_summary, "sections": sections, "figure_notes": {}}


def finalize_metrics_narrative(
    bundle: dict[str, Any],
    ai_result: dict[str, Any] | None,
    *,
    ai_failure_reason: str | None = None,
) -> dict[str, Any]:
    """
    Prefer normalized OpenAI output when it contains real prose; otherwise use bundle-derived commentary.
    Sets narrative_source for PDF cover note: 'openai' | 'fallback'.
    When using fallback after an AI attempt failed, ai_failure_reason is copied to ai_diagnostic for the PDF.
    """
    norm = normalize_narrative(ai_result) if ai_result else None
    if norm and _narrative_has_substance(norm):
        norm["narrative_source"] = "openai"
        return norm
    fb = build_fallback_narrative(bundle)
    fb["narrative_source"] = "fallback"
    if ai_failure_reason:
        fb["ai_diagnostic"] = ai_failure_reason[:800]
    elif ai_result is not None:
        fb["ai_diagnostic"] = (
            "OpenAI returned JSON but executive summary and section bodies were empty "
            "or could not be normalised."
        )
    return fb


def run_metrics_report_ai(settings: Settings, bundle: dict) -> MetricsReportAiResult:
    """
    Two-pass narrative. On failure, narrative is None and failure_reason explains why (also logged).
    """
    if not (settings.openai_api_key or "").strip():
        logger.info("metrics_report_ai: skipped — OPENAI_API_KEY is not set")
        return MetricsReportAiResult(None, "OPENAI_API_KEY is not set")

    model = (settings.openai_metrics_report_model or "gpt-5.4-mini").strip()
    client = OpenAI(api_key=settings.openai_api_key)
    payload = _compact_bundle_json(bundle)

    draft, err = _call_json_model(
        client,
        model,
        PASS1_SYSTEM,
        "Metrics bundle (JSON):\n" + payload + _pass1_user_instructions(bundle),
    )
    if not draft or not isinstance(draft.get("sections"), list):
        reason = err or "Pass 1 did not return a JSON object with a sections array"
        logger.warning("metrics_report_ai: pass 1 failed — %s", reason)
        return MetricsReportAiResult(None, reason)

    digest = json.dumps(metrics_numbers_digest(bundle), default=str, separators=(",", ":"))
    draft_txt = json.dumps(draft, default=str, separators=(",", ":"))[:120000]

    verified, err2 = _call_json_model(
        client,
        model,
        PASS2_SYSTEM,
        "AUTHORITATIVE_DIGEST_JSON:\n"
        + digest
        + "\n\nDRAFT_JSON:\n"
        + draft_txt,
    )
    if not verified:
        logger.warning(
            "metrics_report_ai: pass 2 failed (%s); using pass 1 draft only",
            err2 or "unknown",
        )
        return MetricsReportAiResult(draft, None)

    revised = verified.get("revised")
    if isinstance(revised, dict) and isinstance(revised.get("sections"), list) and len(revised["sections"]) > 0:
        return MetricsReportAiResult(revised, None)
    if verified.get("approved"):
        return MetricsReportAiResult(draft, None)
    return MetricsReportAiResult(draft, None)

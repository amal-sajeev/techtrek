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


PASS1_SYSTEM = """You are a senior analytics consultant writing a professional report for an event ticketing platform (TechTrek).
You MUST only use quantitative facts that appear in the provided JSON metrics bundle.
Do not invent KPIs, counts, or percentages. Use Indian English; currency is INR (use Rs. or INR in text).

CRITICAL INSTRUCTIONS — produce GENUINE ANALYSIS, not a restatement of numbers:
- DO NOT just list numbers from the bundle. The reader can already see the charts and tables.
- INTERPRET what the numbers mean: what's healthy, what's concerning, what's an opportunity.
- COMPARE metrics against each other (e.g. check-in rate vs bookings, refund rate vs total revenue).
- IDENTIFY patterns: concentration risk, growth/decline trends, engagement gaps.
- PROVIDE actionable recommendations: what the team should do next.
- When data is sparse (e.g. 0 feedback, few users), explain WHY that matters and recommend steps.
- Each section body MUST be 80-200 words of substantive prose, not bullet lists of raw figures.

Output a single JSON object with this shape:
{
  "executive_summary": "3-5 sentences of strategic-level markdown: lead with the single most important insight, then key risks or opportunities, then a forward-looking recommendation",
  "sections": [
    {"tab": "overview", "title": "string", "body_markdown": "Interpret booking and revenue trajectories. Flag momentum or stagnation. Note event pipeline health."},
    {"tab": "users", "title": "string", "body_markdown": "Analyse user acquisition rate, auth method mix, year-of-study distribution. Identify which cohorts dominate and what that implies."},
    {"tab": "events", "title": "string", "body_markdown": "Assess event portfolio diversity, geographic spread, demand concentration. Flag if one event drives most bookings."},
    {"tab": "revenue", "title": "string", "body_markdown": "Analyse revenue per booking, seat-type performance, refund ratio, coupon effectiveness. Flag revenue risks."},
    {"tab": "feedback", "title": "string", "body_markdown": "Evaluate feedback coverage and rating quality. If sparse, explain the gap and recommend a strategy."},
    {"tab": "sessions", "title": "string", "body_markdown": "Analyse check-in patterns, venue utilisation, occupancy. Identify peak hours and capacity planning implications."},
    {"tab": "system", "title": "string", "body_markdown": "Summarise newsletter and subscriber engagement, activity log patterns, webhook health. Identify operational signals."}
  ],
  "figure_notes": {
    "overview_bookings_trend": "one short caption",
    "overview_revenue_trend": "one short caption",
    "overview_booking_status": "one short caption",
    "overview_event_status": "one short caption"
  }
}
The body_markdown strings shown above are just guidance for what to cover — replace them with actual analysis.
You may add more keys to figure_notes for other figures if helpful. Keep body_markdown 80-250 words per section."""


PASS2_SYSTEM = """You verify an analytics draft against authoritative metrics JSON and improve analytical depth.
Compare every number, percentage, and count mentioned in the draft to the digest.
Also check: does each section contain genuine analysis (80+ words of interpretive prose) or just restate numbers?
Return JSON only:
{
  "approved": true or false,
  "issues": ["brief issue strings"],
  "revised": { same shape as draft: executive_summary, sections, figure_notes }
}
If approved is true, revised should repeat the draft unchanged or with trivial wording fixes.
If false, revised must:
1. Correct all numerical inaccuracies using ONLY the digest; remove unverifiable claims.
2. Expand any section with fewer than 80 words of body text — add interpretation, implications, and recommendations derived from the digest numbers.
3. Never leave a section body_markdown empty or with only one sentence."""


def _pass1_user_instructions(bundle: dict) -> str:
    rk = bundle.get("report_kind") or "quarterly_brief"
    common = (
        "\n\nREMINDER: Every section must contain genuine analytical paragraphs (80-200 words). "
        "Do NOT produce one-line summaries or bullet-point lists of raw numbers. "
        "Explain what the data MEANS, identify risks, and give recommendations.\n"
    )
    if rk == "focused_report":
        return (
            "\n\nREPORT_MODE:\n"
            "focused_report — Write a focused analytical report. Open the executive summary with the applied "
            "filter scope (use filter_summary / filter_params). In each section, interpret figures only within "
            "that scope; do not claim platform-wide totals unless the filters imply it.\n"
        ) + common
    return (
        "\n\nREPORT_MODE:\n"
        "quarterly_brief — Write as a leadership quarterly brief (concise, headline KPIs, risks where data "
        "supports it). The bundle is full-platform, all historical periods: do **not** imply numbers are only "
        "for one calendar quarter. Say clearly that scope is all-time / full platform when you mention time.\n"
    ) + common


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
    """Check that the narrative has genuine analytical content, not just a few words."""
    es = (n.get("executive_summary") or "").strip()
    sections = n.get("sections") or []
    body_words = 0
    for sec in sections:
        if isinstance(sec, dict):
            body_words += len((sec.get("body_markdown") or "").split())
    if len(es.split()) < 15 and body_words < 100:
        return False
    if not es and body_words < 50:
        return False
    return bool(es) or body_words >= 50


def build_fallback_narrative(bundle: dict[str, Any]) -> dict[str, Any]:
    """Deterministic commentary from bundle KPIs so PDFs always include analysis without OpenAI."""
    kind = bundle.get("report_kind") or "quarterly_brief"
    is_focused = kind == "focused_report"
    fs = "; ".join(str(x) for x in (bundle.get("filter_summary") or []))[:800]
    tu = int(bundle.get("total_users") or 0)
    tr = float(bundle.get("total_revenue") or 0)
    tb = int(bundle.get("total_bookings") or 0)
    cr = bundle.get("checkin_rate")
    cr_f = float(cr) if cr is not None else 0.0
    cr_s = f"{cr_f:.1f}"
    ar = bundle.get("avg_rating")
    ar_f = float(ar) if ar is not None else 0.0
    ar_s = f"{ar_f:.2f}"
    tf = int(bundle.get("total_feedback") or 0)
    es = bundle.get("event_statuses") or {}
    bs = bundle.get("booking_statuses") or {}
    bt = bundle.get("booking_trend") or []
    rt = bundle.get("revenue_trend") or []
    rs = bundle.get("refund_stats") or {}
    vs = bundle.get("venue_stats") or {}
    ac = bundle.get("auth_counts") or {}
    rc = bundle.get("role_counts") or {}
    fbs = bundle.get("feedback_stats") or {}
    teb = bundle.get("top_events_by_bookings") or []
    rbe = bundle.get("revenue_by_event") or []
    ch = bundle.get("checkin_hours") or []

    total_events = sum(int(v) for v in es.values()) if es else 0
    refund_count = int(rs.get("count") or 0)
    refund_total = float(rs.get("total") or 0)
    refund_pct = (refund_count / tb * 100) if tb > 0 else 0
    rev_per_booking = tr / tb if tb > 0 else 0
    total_seats = int(vs.get("total_seats") or 0)
    booked_seats = int(vs.get("booked") or 0)
    occupancy = float(vs.get("occupancy") or 0)
    oauth_count = int(ac.get("oauth") or 0)
    pw_count = int(ac.get("password") or 0)
    oauth_pct = (oauth_count / tu * 100) if tu > 0 else 0

    # ── Executive Summary ──
    exec_parts: list[str] = []
    if is_focused:
        exec_parts.append(f"**Scope:** {fs}")

    if tb == 0:
        exec_parts.append(
            f"The platform has **{tu:,}** registered users but **zero paid bookings** to date. "
            "This indicates the platform is in a pre-launch or early onboarding phase. "
            "Priority should be driving first conversions through promotional events or free-tier offerings."
        )
    elif tb < 10:
        exec_parts.append(
            f"With **{tu:,}** users and only **{tb}** paid bookings generating **Rs. {tr:,.0f}** in revenue, "
            f"the platform is in early traction. Average revenue per booking is **Rs. {rev_per_booking:,.0f}**. "
            f"The check-in rate of **{cr_s}%** {'is encouraging for an early-stage product' if cr_f >= 50 else 'suggests attendance follow-through needs improvement'}."
        )
    else:
        exec_parts.append(
            f"The platform has **{tu:,}** users, **{tb:,}** paid bookings, and **Rs. {tr:,.0f}** total revenue. "
            f"Average revenue per booking is **Rs. {rev_per_booking:,.0f}** with a **{cr_s}%** check-in rate."
        )

    if tf == 0 and tb > 0:
        exec_parts.append(
            "**Key gap:** No feedback has been collected yet. Without attendee sentiment data, it is impossible "
            "to measure event quality or speaker effectiveness. Enabling post-event feedback collection should be an immediate priority."
        )
    elif tf > 0 and ar_f < 3.0:
        exec_parts.append(
            f"**Risk:** Average rating is **{ar_s}/5** from **{tf}** responses — below the 3.0 threshold, "
            "suggesting attendee dissatisfaction that needs investigation."
        )

    if refund_count > 0 and refund_pct > 15:
        exec_parts.append(
            f"**Concern:** Refund rate is **{refund_pct:.1f}%** ({refund_count} refund(s), Rs. {refund_total:,.0f}), "
            "which is above a healthy threshold. Investigate whether pricing, scheduling, or event quality is the driver."
        )

    if not is_focused:
        exec_parts.append(
            "**Note:** All figures in this report aggregate **full historical activity** across the platform, "
            "not a single calendar quarter. Use the Metrics page filters to narrow to a specific time window or event."
        )

    executive_summary = "\n\n".join(exec_parts)

    # ── Overview ──
    overview_parts: list[str] = []
    if bt:
        if len(bt) >= 2:
            first_c, last_c = int(bt[0].get("count") or 0), int(bt[-1].get("count") or 0)
            trend_word = "growing" if last_c > first_c else "declining" if last_c < first_c else "flat"
            overview_parts.append(
                f"Booking volume is **{trend_word}**, moving from **{first_c}** in **{bt[0].get('label')}** "
                f"to **{last_c}** in **{bt[-1].get('label')}** over **{len(bt)}** recorded periods."
            )
        else:
            overview_parts.append(
                f"Only one booking period is recorded (**{bt[-1].get('label')}** with "
                f"**{int(bt[-1].get('count') or 0)}** bookings), so trend analysis is not yet possible. "
                "More data points are needed to identify growth patterns."
            )
    if rt and len(rt) >= 2:
        first_r, last_r = float(rt[0].get("value") or 0), float(rt[-1].get("value") or 0)
        rev_trend = "increasing" if last_r > first_r else "decreasing" if last_r < first_r else "stable"
        overview_parts.append(
            f"Revenue is **{rev_trend}**: Rs. **{first_r:,.0f}** in **{rt[0].get('label')}** "
            f"to Rs. **{last_r:,.0f}** in **{rt[-1].get('label')}**."
        )
    if es:
        status_summary = ", ".join(f"**{int(v)}** {k}" for k, v in es.items())
        overview_parts.append(f"The event pipeline has {status_summary} event(s).")
        published = int(es.get("published") or 0)
        if published == 0 and total_events > 0:
            overview_parts.append(
                "**No events are currently published**, meaning new bookings cannot come in. "
                "Publishing upcoming events should be a priority to maintain booking momentum."
            )
    if tb > 0 and total_events > 0:
        bpe = tb / total_events
        overview_parts.append(
            f"Across the event portfolio, the average is **{bpe:.1f}** paid bookings per event. "
            + (
                "This is low and suggests either limited marketing reach or misaligned event offerings."
                if bpe < 5
                else "This suggests healthy demand distribution across events."
            )
        )
    overview_body = "\n\n".join(overview_parts) or "Insufficient data to perform trend analysis. The platform needs more booking history to generate meaningful insights."

    # ── Users ──
    users_parts: list[str] = []
    if tu > 0:
        conversion = (tb / tu * 100) if tu > 0 else 0
        users_parts.append(
            f"Of **{tu:,}** registered users, **{tb}** have made a paid booking — "
            f"a **{conversion:.1f}%** conversion rate. "
            + (
                "This is very low and indicates a large pool of registered-but-inactive users. "
                "Consider targeted email campaigns or promotional pricing to activate dormant accounts."
                if conversion < 20
                else "This is a reasonable conversion rate for an event platform."
                if conversion < 60
                else "This is an exceptionally high conversion rate, indicating strong product-market fit."
            )
        )
    if ac and tu > 0:
        users_parts.append(
            f"**{oauth_pct:.0f}%** of users authenticate via OAuth (Google) and **{100 - oauth_pct:.0f}%** use passwords. "
            + (
                "The high OAuth adoption simplifies onboarding and reduces password-reset support burden."
                if oauth_pct > 50
                else "Password-based sign-ups dominate; promoting Google SSO could reduce sign-up friction."
            )
        )
    if rc:
        active = int(rc.get("active") or 0)
        deleted = int(rc.get("deleted") or 0)
        if deleted > 0 and active > 0:
            churn = deleted / (active + deleted) * 100
            users_parts.append(
                f"Account churn stands at **{churn:.1f}%** ({deleted} deleted out of {active + deleted} total). "
                + ("This is within normal bounds." if churn < 10 else "This is elevated and worth investigating.")
            )
    reg = bundle.get("reg_trend") or []
    if len(reg) >= 2:
        first_reg = int(reg[0].get("count") or 0)
        last_reg = int(reg[-1].get("count") or 0)
        users_parts.append(
            f"Registration activity moved from **{first_reg}** in **{reg[0].get('label')}** to "
            f"**{last_reg}** in **{reg[-1].get('label')}**."
        )
    users_body = "\n\n".join(users_parts) or "User data is too sparse for meaningful cohort analysis. Focus on growing the registered user base through event marketing."

    # ── Events ──
    ebc = bundle.get("events_by_city") or []
    spe = bundle.get("sessions_per_event") or []
    events_parts: list[str] = []
    if teb:
        top_ev = teb[0]
        top_bookings = int(top_ev.get("count") or 0)
        concentration = (top_bookings / tb * 100) if tb > 0 else 0
        events_parts.append(
            f"**{str(top_ev.get('name', ''))[:70]}** leads with **{top_bookings}** bookings, "
            f"accounting for **{concentration:.0f}%** of all paid bookings. "
            + (
                "This heavy concentration on a single event creates **revenue risk** — if this event "
                "underperforms, overall numbers will drop significantly. Diversifying the event portfolio "
                "would build resilience."
                if concentration > 70 and len(teb) > 1
                else ""
            )
        )
        if len(teb) > 1:
            others = teb[1:]
            other_total = sum(int(x.get("count") or 0) for x in others)
            events_parts.append(
                f"The remaining **{len(others)}** event(s) account for **{other_total}** bookings combined."
            )
    if ebc:
        cities = [c.get("name", "") for c in ebc]
        if len(cities) == 1:
            events_parts.append(
                f"All events are concentrated in **{cities[0]}**. Geographic expansion to other cities "
                "could unlock new audiences."
            )
        elif len(cities) >= 2:
            events_parts.append(
                f"Events are spread across **{len(cities)}** cities ({', '.join(str(c)[:20] for c in cities[:4])}), "
                "providing geographic diversity."
            )
    if spe:
        avg_sessions = sum(int(x.get("count") or 0) for x in spe) / len(spe)
        events_parts.append(
            f"Events average **{avg_sessions:.1f}** sessions each. "
            + (
                "Events with more sessions tend to provide richer experiences and can justify higher pricing."
                if avg_sessions >= 3
                else "Consider adding more sessions per event to increase perceived value."
            )
        )
    events_body = "\n\n".join(events_parts) or "No events have bookings yet. Create and publish events to begin generating demand data."

    # ── Revenue ──
    rev_parts: list[str] = []
    if bundle.get("single_event_selected"):
        sd = bundle.get("seat_distribution") or {}
        unsold = int(sd.get("unsold") or 0)
        total_cap = int(sd.get("total_capacity") or 0)
        if total_cap > 0:
            sell_through = ((total_cap - unsold) / total_cap * 100) if total_cap > 0 else 0
            rev_parts.append(
                f"Sell-through rate is **{sell_through:.0f}%** with **{unsold}** unsold seats "
                f"out of **{total_cap}** total capacity."
            )
    if tb > 0:
        rev_parts.append(
            f"Total revenue stands at **Rs. {tr:,.0f}** from **{tb}** bookings, "
            f"yielding an average ticket value of **Rs. {rev_per_booking:,.0f}**."
        )
    rbs = bundle.get("revenue_by_seat_type") or []
    if rbs and len(rbs) > 1:
        top_st = max(rbs, key=lambda x: float(x.get("revenue") or 0))
        rev_parts.append(
            f"The **{top_st.get('display_label') or top_st.get('type', '')}** seat type generates the most "
            f"revenue. Consider premium seating strategies to maximise yield per event."
        )
    if refund_count > 0:
        cancel_fees = float(rs.get("cancel_fees") or 0)
        net_refund = refund_total - cancel_fees
        rev_parts.append(
            f"**{refund_count}** refund(s) totalling **Rs. {refund_total:,.0f}** have been processed "
            f"(cancellation fees recovered: Rs. {cancel_fees:,.0f}, net loss: Rs. {net_refund:,.0f}). "
            f"The refund rate is **{refund_pct:.1f}%** of bookings"
            + (", which is healthy." if refund_pct < 10 else " — monitor for a rising trend.")
        )
    elif tb > 0:
        rev_parts.append("No refunds have been issued, indicating strong booking-to-attendance commitment.")
    cs = bundle.get("coupon_stats") or {}
    if int(cs.get("total") or 0) > 0:
        redeemed = int(cs.get("redeemed") or 0)
        total_coupons = int(cs.get("total") or 0)
        rev_parts.append(
            f"**{redeemed}** of **{total_coupons}** coupon(s) have been redeemed. "
            + ("Coupon adoption is low; consider promoting codes through newsletters." if redeemed == 0 else "")
        )
    revenue_body = "\n\n".join(rev_parts) or "No revenue data available. Revenue analysis will become meaningful once paid bookings begin."

    # ── Feedback ──
    feedback_parts: list[str] = []
    submitted = int(fbs.get("submitted") or 0)
    fb_rate = float(fbs.get("rate") or 0)
    if submitted == 0:
        feedback_parts.append(
            "**No feedback has been submitted** across any events. This is a significant blind spot — without "
            "attendee sentiment data, the team cannot measure session quality, identify underperforming speakers, "
            "or quantify attendee satisfaction. Recommendations: (1) enable automated post-event feedback "
            "emails, (2) consider in-app prompts immediately after check-in, (3) offer incentives such as "
            "certificate downloads gated behind feedback submission."
        )
    else:
        feedback_parts.append(
            f"**{submitted}** feedback submissions at a **{fb_rate}%** response rate. "
            + (
                "This response rate is below the **20%** benchmark typical for event platforms. "
                "Automated reminder emails and simplified rating flows could help."
                if fb_rate < 20
                else "This is a solid response rate. Maintaining this level will provide reliable quality signals."
            )
        )
        if ar_f > 0:
            feedback_parts.append(
                f"The average rating is **{ar_s}/5**. "
                + (
                    "Ratings are strong, suggesting attendees find events valuable."
                    if ar_f >= 4.0
                    else "Ratings are moderate — review session feedback comments for improvement areas."
                    if ar_f >= 3.0
                    else "Ratings are concerning. Deep-dive into comment-level feedback to identify root causes."
                )
            )
    bsess = bundle.get("best_sessions") or []
    if bsess:
        b = bsess[0]
        feedback_parts.append(
            f"Top-rated session: **{str(b.get('title', ''))[:50]}** (avg **{b.get('avg')}**/5, n=**{b.get('count')}**). "
            "Study this session's format and speaker for replicable best practices."
        )
    feedback_body = "\n\n".join(feedback_parts)

    # ── Sessions & Operations ──
    sess_parts: list[str] = []
    if ch:
        peak = max(ch, key=lambda x: int(x.get("count") or 0))
        total_checkins = sum(int(x.get("count") or 0) for x in ch)
        peak_count = int(peak.get("count") or 0)
        peak_pct = (peak_count / total_checkins * 100) if total_checkins > 0 else 0
        sess_parts.append(
            f"Peak check-in activity occurs at **{peak.get('hour')}:00** with **{peak_count}** check-ins "
            f"(**{peak_pct:.0f}%** of all check-ins). "
            "Staff scheduling should align with this peak to ensure smooth entry."
        )
    if total_seats > 0:
        sess_parts.append(
            f"Venue capacity is **{total_seats}** total seats with **{booked_seats}** booked, "
            f"yielding **{occupancy}%** occupancy. "
            + (
                "Occupancy is very low, suggesting either overcapacity or insufficient marketing. "
                "Consider using smaller venues or running more targeted promotions to fill seats."
                if occupancy < 20
                else "Occupancy is moderate. There is room to grow attendance without capacity constraints."
                if occupancy < 70
                else "Occupancy is high, approaching capacity. Plan for overflow management or larger venues."
            )
        )
    elif tb > 0:
        sess_parts.append("No venue capacity data is available. Linking events to venues enables occupancy tracking.")
    if cr_f > 0 and tb > 0:
        no_shows = 100 - cr_f
        sess_parts.append(
            f"The overall check-in rate is **{cr_s}%**, implying a **{no_shows:.1f}%** no-show rate. "
            + (
                "Consider day-before reminder emails to reduce no-shows."
                if no_shows > 30
                else "This is within an acceptable range for event attendance."
            )
        )
    sessions_body = "\n\n".join(sess_parts) or "No check-in or venue data recorded. Sessions analysis will be available once events with venue assignments have been held."

    # ── System ──
    ns = bundle.get("newsletter_stats") or {}
    wh = bundle.get("webhook_stats") or {}
    abc = bundle.get("activity_by_cat") or []
    st = bundle.get("subscriber_trend") or []
    sys_parts: list[str] = []
    subs = int(ns.get("subscribers") or 0)
    sends = int(ns.get("sent") or 0)
    if subs > 0 or sends > 0:
        sys_parts.append(
            f"The newsletter has **{subs}** subscriber(s) with **{sends}** email(s) sent. "
            + (
                "Newsletter reach is limited. Growing the subscriber list through sign-up incentives "
                "and event-page prompts would expand the marketing channel."
                if subs < 50
                else "The subscriber base provides a meaningful audience for event announcements."
            )
        )
    if wh and int(wh.get("total") or 0):
        wh_rate = float(wh.get("rate") or 0)
        sys_parts.append(
            f"Webhook processing stands at **{wh_rate}%** "
            f"(**{int(wh.get('processed') or 0)}** / **{int(wh.get('total') or 0)}**). "
            + ("All webhooks are being processed successfully." if wh_rate >= 99 else "Some webhooks are failing — investigate the error logs.")
        )
    if abc:
        top_a = abc[0]
        sys_parts.append(
            f"The most active system category is **{top_a.get('category')}** with **{int(top_a.get('count') or 0)}** "
            f"log entries, providing visibility into platform usage patterns."
        )
    if not sys_parts:
        sys_parts.append(
            "System telemetry is minimal. As the platform scales, monitoring webhook processing rates, "
            "newsletter engagement, and activity log volumes will be important for operational health."
        )

    if is_focused:
        def _within_scope(text: str, default: str) -> str:
            t = text.strip() if (text or "").strip() else default
            return f"**Within this scope:** {t}"

        overview_body = _within_scope(overview_body, "Insufficient data for trend analysis within this scope.")
        users_body = _within_scope(users_body, "User data is too sparse for cohort analysis within this scope.")
        events_body = _within_scope(events_body, "No event booking data within this scope.")
        revenue_body = _within_scope(revenue_body, "No revenue data within this scope.")
        feedback_body = _within_scope(feedback_body, "No feedback within this scope.")
        sessions_body = _within_scope(sessions_body, "No check-in or venue data within this scope.")
        system_body = "\n\n".join(sys_parts) if sys_parts else "No system data within this scope."

    sections = [
        {"tab": "overview", "title": "Overview", "body_markdown": overview_body},
        {"tab": "users", "title": "Users", "body_markdown": users_body},
        {"tab": "events", "title": "Events", "body_markdown": events_body},
        {"tab": "revenue", "title": "Revenue", "body_markdown": revenue_body},
        {"tab": "feedback", "title": "Feedback", "body_markdown": feedback_body},
        {"tab": "sessions", "title": "Sessions & operations", "body_markdown": sessions_body},
        {"tab": "system", "title": "System", "body_markdown": "\n\n".join(sys_parts) if not is_focused else system_body},
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

# Session/Showing Model Split — Template Audit Report

**Date:** March 13, 2025  
**Scope:** All `.html` templates in `app/templates/` (all subdirectories)

---

## Summary

| Severity | Count |
|----------|-------|
| **BUG** (would cause crash or wrong behavior) | 8 |
| **Cosmetic** (wrong data displayed) | 0 |

---

## BUGS (Would Cause Crash or Wrong Behavior)

### 1. `app/templates/booking/select_seat.html`

**Line 78** — Form action uses session ID instead of showing ID:
```html
<form method="post" action="/booking/hold/{{ lecture.id }}" id="seat-form">
```
- **Problem:** The `/booking/hold/{showing_id}` route expects a **showing_id**, but `lecture.id` is the session ID.
- **Fix:** Change to `action="/booking/hold/{{ showing.id }}"`
- **Impact:** BUG — Hold would fail or target wrong showing; booking flow broken.

---

**Line 119** — SeatPicker.init receives session ID instead of showing ID:
```javascript
SeatPicker.init(seatData, pricing, {{ lecture.id }}, gapData, stageOpts, entryExitConfig, customTypes);
```
- **Problem:** The third parameter is used as the ID for the hold form/API; it must be **showing_id**.
- **Fix:** Change to `{{ showing.id }}`
- **Impact:** BUG — Same as above; seat hold would use wrong ID.

---

### 2. `app/templates/booking/checkout.html`

**Line 140** — JavaScript uses session ID for payment APIs:
```javascript
var sessionId = {{ lecture.id }};
```
- **Problem:** Used for `/booking/create-order/{showing_id}` and `/booking/verify-payment/{showing_id}`; both expect **showing_id**.
- **Fix:** Change to `var sessionId = {{ showing.id }};` (or rename variable to `showingId` for clarity)
- **Impact:** BUG — Payment creation and verification would fail or use wrong showing.

---

### 3. `app/templates/public/recordings.html`

**Line 37** — Session has no `speaker` attribute:
```html
<p class="card-meta">{{ s.speaker }}</p>
```
- **Problem:** `Session` has `speaker_name` and `speaker_rel`, not `speaker`. Would raise `AttributeError`.
- **Fix:** Change to `{{ s.speaker_name }}` or `{{ (s.speaker_rel.name if s.speaker_rel else s.speaker_name) }}`
- **Impact:** BUG — Page would crash when viewing recordings.

---

**Lines 38–39** — Session has no `start_time`:
```html
<span class="card-detail">&#128197; {{ s.start_time.strftime('%b %d, %Y') }}</span>
```
- **Problem:** `start_time` is on **Showing**, not Session. Router passes `{"session": s, "auditorium": aud}` but not the showing.
- **Fix (router):** In `app/routers/public.py` `recordings_page`, add `"showing": latest_showing` to enriched:  
  `enriched.append({"session": s, "auditorium": aud, "showing": latest_showing})`
- **Fix (template):** Change to `{{ item.showing.start_time.strftime('%b %d, %Y') if item.showing else '—' }}`
- **Impact:** BUG — Page would crash with `AttributeError`.

---

### 4. `app/templates/supervisor/checkin.html`

**Line 18** — Showing has no `title`:
```html
<option value="{{ s.id }}" ...>{{ s.title }} ({{ s.start_time.strftime('%b %d') }})</option>
```
- **Problem:** `s` is a **Showing** (router passes `sessions=showings`). Showing has no `title`; it has `session` with `title`.
- **Fix:** Change to `{{ s.session.title if s.session else '—' }} ({{ s.start_time.strftime('%b %d') }})`
- **Impact:** BUG — Page would crash with `AttributeError`.

---

### 5. `app/templates/speaker/dashboard.html`

**Lines 48–50** — Session has no `start_time` or `status`:
```html
<td>{{ s.start_time.strftime('%d %b %Y, %I:%M %p') }}</td>
<td>{{ s.duration_minutes }} min</td>
<td>
  <span class="badge ...">{{ s.status|replace('_',' ')|title }}</span>
</td>
```
- **Problem:** `s` is `item.session` (Session). `start_time` and `status` are on **Showing**, not Session. `duration_minutes` is on Session.
- **Fix (router):** In `app/routers/speaker.py` `dashboard`, enrich each item with a representative showing (e.g. next or first):  
  `enriched.append({"session": s, "bookings": booking_count, "showing": first_showing})`
- **Fix (template):** Use `{{ item.showing.start_time.strftime(...) if item.showing else '—' }}` and `{{ item.showing.status|... if item.showing else '—' }}`
- **Impact:** BUG — Page would crash with `AttributeError`.

---

### 6. `app/templates/booking/event_select_seats.html`

**Line 362** — Fallback uses session ID incorrectly:
```javascript
var mapId = sd.showing ? ('seat-map-ps-' + sd.showing.id) : ('seat-map-ps-' + sd.session.id);
```
- **Problem:** If `sd.showing` is missing, fallback uses `sd.session.id` (session ID). Seat map IDs are keyed by `showing.id`, so this would be wrong.
- **Fix:** Prefer `sd.showing.id` always when possible. If `sd.showing` can be absent, ensure the router always provides it; otherwise use a safe fallback or omit the block.
- **Impact:** BUG (edge case) — Wrong element IDs or map lookup if `sd.showing` is missing.

---

## Templates Verified as Correct

| Template | Notes |
|----------|-------|
| `public/session_detail.html` | Uses `lecture` (session), `primary_showing` (showing); `ss.speaker` is SessionSpeaker→Speaker relation |
| `admin/checkin.html` | Uses `s.session.title`, `s.start_time`; `s` is Showing |
| `admin/sessions.html` | Uses `item.session`, `next_showing` from `item.showings` |
| `admin/schedule_admin.html` | Uses `item.showing`, `item.auditorium` |
| `admin/session_form.html` | Uses `lecture` (session), `showing` (showing) for scheduling fields |
| `admin/event_form.html` | Uses `s` (Showing) with `s.session.title`, `s.start_time`, `s.auditorium` |
| `public/schedule.html` | Uses `item.session`, `item.showing` |
| `public/sessions.html` | Uses `item.session`, `item.showing` |
| `public/home.html` | Uses `item.session`, `item.showing` |
| `public/event_detail.html` | Uses `item.session`, `item.showing` |
| `public/feedback_form.html` | Uses `showing` |
| `public/ticket.html` | Uses `lecture` (session), `showing` (showing) |
| `public/ticket_group.html` | Uses `lecture` (session), `showing` (showing) |
| `booking/confirmation.html` | Uses `lecture` (session), `showing` (showing) |
| `booking/booking_detail.html` | Uses `lecture` (session), `showing` (showing) |
| `booking/my_bookings.html` | Uses `g.lecture` (session), `g.showing` (showing) |
| `booking/checkout.html` | Uses `lecture` (session), `showing` (showing) for display; only JS `sessionId` is wrong |
| `booking/event_checkout.html` | Uses `info.showing` |
| `booking/event_confirmation.html` | Uses `info.showing` |
| `speaker/session_edit.html` | Uses `lecture` (session), `first_showing` (showing) |
| `admin/feedback.html` | Uses `showing` |
| `admin/waitlist.html` | Uses `s.session`, `s.start_time`; `s` is Showing |
| `base.html` | Uses `pf.showing_id` for feedback modal |

---

## Recommended Fix Order

1. **Critical (booking flow):** `select_seat.html`, `checkout.html` — fix form action and JS IDs.
2. **User-facing:**
   - `recordings.html` — fix speaker and start_time (router + template).
   - `supervisor/checkin.html` — fix title.
3. **Speaker dashboard:** `speaker/dashboard.html` — fix start_time and status (router + template).
4. **Edge case:** `event_select_seats.html` — ensure `sd.showing` is always present or handle fallback safely.

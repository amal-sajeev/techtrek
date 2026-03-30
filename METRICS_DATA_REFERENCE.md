# Metrics Page — Data Reference

Complete inventory of data available for the admin metrics page, derived from the ORM models in `app/models/`. Each metric lists its source query pattern, return type, and whether it already exists in the codebase.

**Legend:** (E) = already exists in `admin.py` dashboard/metrics/event-report handlers. Unmarked = available in the schema but not yet surfaced.

---

## 1. Users

| Metric | Source | Type | Status |
|--------|--------|------|--------|
| Total registered users | `COUNT(User.id) WHERE deleted_at IS NULL` | `int` | (E) |
| New registrations over time | `User.created_at` grouped by month/week/day | `[{label: str, count: int}]` | (E) last 12mo |
| Users by specialization/domain | `User.domain` counter | `[{name: str, count: int}]` | (E) top 10 |
| Users by discipline | `User.discipline` counter | `[{name: str, count: int}]` | |
| Users by year of study | `User.year_of_study` grouped | `[{year: int, count: int}]` | |
| Users by college (self-reported) | `User.college` counter | `[{name: str, count: int}]` | Free-text `String(300)` |
| Admin count | `COUNT(User.id) WHERE is_admin=True` | `int` | |
| Supervisor count | `COUNT(User.id) WHERE is_supervisor=True` | `int` | |
| OAuth vs password users | `User.oauth_provider IS NOT NULL` vs `IS NULL` | `{oauth: int, password: int}` | |
| Deleted/deactivated users | `COUNT WHERE deleted_at IS NOT NULL` | `int` | |

---

## 2. Events

| Metric | Source | Type | Status |
|--------|--------|------|--------|
| Events by status | `Event.status` grouped | `{draft: int, published: int, completed: int, cancelled: int}` | (E) |
| Events by college | `Event.college_id` -> `College.name` | `[{name: str, count: int}]` | (E) as "top colleges" |
| Events by city | `College.city_id` -> `City.name` | `[{name: str, count: int}]` | Derivable |
| Events over time | `Event.start_date` grouped by month | `[{label: str, count: int}]` | |
| Free vs paid events | `Event.price == 0` vs `> 0` | `{free: int, paid: int}` | `Numeric(10,2)` |
| Average ticket price | `AVG(Event.price) WHERE price > 0` | `float` | |
| Events with VIP pricing | `COUNT WHERE price_vip IS NOT NULL` | `int` | |
| Events with custom pricing | `COUNT WHERE custom_prices IS NOT NULL` | `int` | JSON field |
| Events with feedback templates | `COUNT WHERE feedback_template_id IS NOT NULL` | `int` | |
| Events with certificates configured | `COUNT WHERE cert_title IS NOT NULL` | `int` | |
| Sessions per event | `COUNT(EventSession.id) GROUP BY event_id` | `[{event: str, count: int}]` | Via `event_sessions` relationship |

---

## 3. Bookings & Revenue

| Metric | Source | Type | Status |
|--------|--------|------|--------|
| Total paid bookings | `COUNT(Booking.id) WHERE payment_status='paid' AND is_shared_ticket=False` | `int` | (E) |
| Total revenue | `SUM(Booking.amount_paid)` (same filter) | `float` | (E) |
| Average revenue per booking | `AVG(Booking.amount_paid)` | `float` | |
| Bookings by payment status | `Booking.payment_status` grouped | `{hold: int, paid: int, cancelled: int, refunded: int}` | (E) event report |
| Bookings over time (monthly) | `Booking.booked_at` grouped by month | `[{label: str, count: int}]` | (E) last 12mo |
| Bookings over time (daily) | `Booking.booked_at` grouped by day | `[{date: str, count: int}]` | (E) event report |
| Revenue over time (monthly) | `SUM(amount_paid)` grouped by month | `[{label: str, revenue: float}]` | |
| Revenue by seat type | `Seat.seat_type` grouped | `[{type: str, count: int, revenue: float}]` | (E) event report |
| Revenue by event | per `event_id` | `[{event: str, revenue: float, bookings: int}]` | |
| Revenue by college | via `Event.college_id` | `[{college: str, revenue: float}]` | |
| Revenue by city | via `College.city_id` | `[{city: str, revenue: float}]` | |
| Refund count | `COUNT WHERE payment_status='refunded'` | `int` | (E) |
| Refund total amount | `SUM(Booking.refund_amount)` | `float` | Column exists |
| Cancellation fee total | `SUM(Booking.cancellation_fee)` | `float` | Column exists |
| Shared tickets count | `COUNT WHERE is_shared_ticket=True` | `int` | |
| Ticket shares claimed vs unclaimed | `TicketShare.claimed_at IS NOT NULL` | `{claimed: int, unclaimed: int}` | |

---

## 4. Check-in

| Metric | Source | Type | Status |
|--------|--------|------|--------|
| Total check-ins (all time) | `COUNT(Booking.id) WHERE checked_in=True` | `int` | (E) |
| Check-in rate per event | `checked_in_count / total_paid * 100` | `float` (%) | (E) event overview |
| Check-in time distribution | `Booking.checked_in_at` grouped by hour | `[{hour: int, count: int}]` | |

---

## 5. Waitlist

| Metric | Source | Type | Status |
|--------|--------|------|--------|
| Total waitlist entries | `COUNT(Waitlist.id)` | `int` | |
| Waitlist per event | `GROUP BY event_id` | `[{event: str, count: int}]` | (E) dashboard/overview |
| Notified waitlisters | `COUNT WHERE notified=True` | `int` | |
| Priority conversion rate | `Waitlist.notified=True` -> check if user has booking for same event | `float` (%) | Requires join |
| Waitlist entries over time | `Waitlist.joined_at` grouped by month | `[{label: str, count: int}]` | |

---

## 6. Coupons

| Metric | Source | Type | Status |
|--------|--------|------|--------|
| Total coupons | `COUNT(Coupon.id)` | `int` | |
| Active vs expired | `is_active` + `valid_until` check | `{active: int, expired: int}` | |
| Total redeemed | `SUM(Coupon.used_count)` | `int` | |
| Per-coupon usage | `Coupon.code, used_count, max_uses` | `[{code: str, used: int, max: int}]` | (E) event report |
| Discount type split | `discount_pct IS NOT NULL` vs `discount_amount IS NOT NULL` | `{percentage: int, fixed: int}` | |
| Revenue impact estimate | join `Booking.coupon_id` -> compare `amount_paid` vs base price | `float` | Requires calculation |

---

## 7. Feedback & Ratings

| Metric | Source | Type | Status |
|--------|--------|------|--------|
| Total feedback submissions | `COUNT(Feedback.id) WHERE submitted_at IS NOT NULL` | `int` | |
| Overall avg rating | `AVG(Feedback.rating)` | `float` | |
| Rating distribution (1-5) | `GROUP BY Feedback.rating` | `{1: int, 2: int, 3: int, 4: int, 5: int}` | (E) event report |
| Feedback with comments | `COUNT WHERE comment IS NOT NULL AND comment != ''` | `int` | |
| Featured feedback count | `COUNT WHERE is_featured=True` | `int` | |
| Public feedback count | `COUNT WHERE allow_public=True` | `int` | |
| Feedback response rate | submissions / eligible paid bookings | `float` (%) | |
| Dismissed without submitting | `COUNT WHERE dismissed=True AND submitted_at IS NULL` | `int` | |
| Best sessions by avg rating | `AVG(SessionFeedback.rating) GROUP BY session_id` | `[{title: str, avg: float, count: int}]` | (E) |
| Best speakers by avg rating | via `Session.speaker_id` joined to `SessionFeedback` | `[{name: str, avg: float, count: int}]` | (E) |
| Responses per template | `FeedbackResponse GROUP BY template_id` | `[{template: str, count: int}]` | |
| Per-question answer aggregates | `QuestionResponse.answer_text` grouped by `question_id` | varies by `question_type` | Types: `text`, `rating`, `multiple_choice` |

### Feedback model notes

Two feedback systems coexist:

- **Legacy:** `Feedback` (overall event rating + comment) and `SessionRating` (per-session star rating within a `Feedback`)
- **Template-based:** `FeedbackTemplate` -> `TemplateQuestion` -> `FeedbackResponse` -> `QuestionResponse`

Both should be aggregated for completeness.

---

## 8. Polls

| Metric | Source | Type | Status |
|--------|--------|------|--------|
| Total polls created | `COUNT(Poll.id)` | `int` | |
| Polls by type | `Poll.poll_type` grouped | `{multiple_choice: int, yes_no: int, rating: int, text: int}` | |
| Active vs closed polls | `Poll.is_active` | `{active: int, closed: int}` | |
| Total votes cast | `COUNT(PollVote.id)` | `int` | |
| Votes per poll | `GROUP BY poll_id` | `[{question: str, votes: int}]` | (E) event report |
| Poll participation rate | votes / eligible attendees | `float` (%) | |
| Per-option vote counts | `PollOption` + `COUNT(PollVote)` | `[{option: str, votes: int, pct: float}]` | (E) in `app/services/polls.py` |
| Rating poll averages | `AVG(PollVote.rating_value)` | `float` | |
| Text responses | `PollVote.text_answer` list | `[str]` | |

---

## 9. Speakers & Sessions

| Metric | Source | Type | Status |
|--------|--------|------|--------|
| Total speakers | `COUNT(Speaker.id)` | `int` | |
| Speakers with user accounts | `COUNT WHERE user_id IS NOT NULL` | `int` | |
| Speakers with pending invites | `COUNT WHERE invite_token IS NOT NULL AND invite_token_expires > now` | `int` | |
| Total sessions | `COUNT(Session.id)` | `int` | |
| Sessions with recordings | `COUNT WHERE recording_url IS NOT NULL` or via `SessionRecording` | `int` | |
| Public recordings | `COUNT(SessionRecording) WHERE is_public=True` | `int` | |
| Sessions per speaker | `GROUP BY speaker_id` | `[{name: str, count: int}]` | |
| Multi-speaker sessions | `SessionSpeaker` count > 1 per `session_id` | `int` | Via `session_speakers` table |

---

## 10. Venues (Colleges, Auditoriums, Seats)

| Metric | Source | Type | Status |
|--------|--------|------|--------|
| Total cities | `COUNT(City.id)` | `int` | |
| Total colleges | `COUNT(College.id)` | `int` | |
| Active colleges | `COUNT WHERE is_active=True` | `int` | |
| Total auditoriums | `COUNT(Auditorium.id)` | `int` | |
| Total seat capacity (raw) | `SUM(Auditorium.total_rows * Auditorium.total_cols)` | `int` | |
| Bookable seats | `COUNT(Seat.id) WHERE is_active=True AND seat_type NOT IN ('aisle', 'reserved')` | `int` | |
| Seat type distribution | `Seat.seat_type` grouped | `[{type: str, count: int}]` | |
| Occupancy rate per event | booked seats / bookable seats for event's auditorium | `float` (%) | |

---

## 11. Newsletters & Subscribers

| Metric | Source | Type | Status |
|--------|--------|------|--------|
| Total subscribers | `COUNT(NewsletterSubscriber.id)` | `int` | |
| Subscriber growth over time | `NewsletterSubscriber.subscribed_at` grouped by month | `[{label: str, count: int}]` | |
| Total newsletters sent | `COUNT(Newsletter.id) WHERE status='sent'` | `int` | |
| Newsletter delivery stats | `Newsletter.sent_count`, `Newsletter.failed_count` | `{sent: int, failed: int}` per newsletter | |
| Avg recipients per newsletter | `AVG(Newsletter.total_recipients)` | `float` | |

---

## 12. Add-ons

| Metric | Source | Type | Status |
|--------|--------|------|--------|
| Total add-ons defined | `COUNT(EventAddOn.id)` | `int` | |
| Add-on revenue | `SUM(EventAddOn.price * BookingAddOn.quantity)` | `float` | (E) event report |
| Most popular add-ons | `GROUP BY addon_id ORDER BY SUM(quantity) DESC` | `[{title: str, qty: int, revenue: float}]` | (E) event report |

---

## 13. Activity & System

| Metric | Source | Type | Status |
|--------|--------|------|--------|
| Activity log entries | `COUNT(ActivityLog.id)` | `int` | |
| Activity by category | `ActivityLog.category` grouped | `[{category: str, count: int}]` | Categories: `booking`, `event`, `session`, `user`, etc. |
| Activity by action | `ActivityLog.action` grouped | `[{action: str, count: int}]` | |
| Activity over time | `ActivityLog.timestamp` grouped by day | `[{date: str, count: int}]` | |
| Webhook log count | `COUNT(WebhookLog.id)` | `int` | |
| Processed vs unprocessed webhooks | `WebhookLog.processed` grouped | `{processed: int, pending: int}` | |
| Alerts sent | `COUNT(EventAlert.id)` | `int` | |
| Alerts by type | `EventAlert.alert_type` grouped | `{info: int, warning: int, urgent: int}` | |
| Active testimonials | `COUNT(Testimonial.id) WHERE is_active=True` | `int` | |

---

## Existing Filter Parameters

The current `/admin/metrics` route accepts these query parameters that should be preserved:

| Parameter | Type | Description |
|-----------|------|-------------|
| `date_from` | `str` (ISO date) | Start date filter |
| `date_to` | `str` (ISO date) | End date filter |
| `event_id` | `str` (int) | Filter to specific event |
| `college_id` | `str` (int) | Filter to specific college |

Filter dropdown data passed to template: `all_events` (all events, sorted by `start_date` desc) and `all_colleges` (active colleges, sorted by name).

---

## Key Model Relationships for Joins

```
User -< Booking >- Event >- College >- City
                   Event >- Auditorium >- Seat
                   Event -< EventSession >- Session >- Speaker
                   Event -< Waitlist
                   Event -< Coupon -< Booking
                   Event -< EventAddOn -< BookingAddOn
                   Event -< Poll -< PollOption -< PollVote
                   Event -< EventAlert
                   Event -< Feedback -< SessionRating
                   Event -< FeedbackResponse -< QuestionResponse
                   Session -< SessionFeedback
                   Session -< SessionRecording
                   Session -< SessionSpeaker >- Speaker
```

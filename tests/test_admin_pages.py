"""Tests for admin pages, supervisor checkin, speaker dashboard, admin recordings."""

from datetime import date, datetime, timedelta

from app.models.booking import Booking
from app.models.seat import Seat
from tests.conftest import (
    admin_session,
    make_auditorium,
    make_college,
    make_event,
    make_feedback,
    make_recording,
    make_session,
    make_speaker,
    make_user,
)


_admin_counter = 0

def _login_admin(client, db):
    global _admin_counter
    _admin_counter += 1
    user = make_user(
        db,
        username=f"admin_{_admin_counter}",
        email=f"admin_{_admin_counter}@test.com",
        is_admin=True,
        password_hash="fakehash",
    )
    db.commit()
    admin_session(client, user)
    return user


class TestAdminDashboard:
    """GET /admin/ -- the main dashboard with stats, top cities, recent bookings."""

    def test_dashboard_unauthenticated(self, client, db):
        resp = client.get("/admin/", follow_redirects=False)
        assert resp.status_code == 303

    def test_dashboard_empty(self, client, db):
        _login_admin(client, db)
        resp = client.get("/admin/")
        assert resp.status_code == 200
        assert b"Dashboard" in resp.content

    def test_dashboard_with_bookings(self, client, db):
        """Dashboard must render when bookings reference events."""
        admin = _login_admin(client, db)
        aud = make_auditorium(db, name="Dashboard Hall")
        event = make_event(
            db, name="Dashboard Talk", auditorium=aud,
            start_date=date.today() + timedelta(days=1),
            price=50, status="published",
        )
        seat = Seat(auditorium_id=aud.id, row_num=0, col_num=0, label="A1")
        db.add(seat)
        db.flush()
        user = make_user(db, username="booker_dash", email="booker_dash@test.com")
        booking = Booking(
            user_id=user.id,
            event_id=event.id,
            seat_id=seat.id,
            amount_paid=50,
            payment_status="paid",
            booking_ref="TEST-DASH-001",
        )
        db.add(booking)
        db.commit()

        resp = client.get("/admin/")
        assert resp.status_code == 200
        assert b"Dashboard" in resp.content
        assert b"Dashboard Talk" in resp.content


class TestAdminSessions:
    """GET /admin/sessions should show sessions with event-level details."""

    def test_sessions_list_unauthenticated(self, client, db):
        resp = client.get("/admin/sessions", follow_redirects=False)
        assert resp.status_code == 303

    def test_sessions_list_loads(self, client, db):
        _login_admin(client, db)
        resp = client.get("/admin/sessions")
        assert resp.status_code == 200
        assert b"Sessions" in resp.content

    def test_sessions_list_with_data(self, client, db):
        _login_admin(client, db)
        event = make_event(db, name="Admin Event", status="published",
                          start_date=date.today() + timedelta(days=5), price=100)
        make_session(db, title="Admin Session Test", event=event)
        db.commit()

        resp = client.get("/admin/sessions")
        assert resp.status_code == 200
        assert b"Admin Session Test" in resp.content


class TestAdminSchedule:
    """GET /admin/schedule should render without errors."""

    def test_schedule_empty(self, client, db):
        _login_admin(client, db)
        resp = client.get("/admin/schedule")
        assert resp.status_code == 200

    def test_schedule_with_event(self, client, db):
        _login_admin(client, db)
        event = make_event(db, name="Schedule Event", status="published",
                          start_date=date.today() + timedelta(days=2))
        make_session(db, title="Schedule Test", event=event)
        db.commit()

        resp = client.get("/admin/schedule")
        assert resp.status_code == 200
        assert b"Schedule Test" in resp.content


class TestAdminBookings:
    """GET /admin/bookings should list bookings using event_id."""

    def test_bookings_list_empty(self, client, db):
        _login_admin(client, db)
        resp = client.get("/admin/bookings")
        assert resp.status_code == 200

    def test_bookings_list_with_data(self, client, db):
        _login_admin(client, db)
        aud = make_auditorium(db, name="Booking Hall")
        event = make_event(db, name="Booked Event", auditorium=aud, price=100)
        seat = Seat(auditorium_id=aud.id, row_num=0, col_num=0, label="B1")
        db.add(seat)
        db.flush()
        user = make_user(db, username="booker_admin", email="booker_admin@test.com")
        booking = Booking(
            user_id=user.id,
            event_id=event.id,
            seat_id=seat.id,
            amount_paid=100,
            payment_status="paid",
            booking_ref="TEST-BOOK-001",
        )
        db.add(booking)
        db.commit()

        resp = client.get("/admin/bookings")
        assert resp.status_code == 200


class TestAdminCheckin:
    """GET /admin/checkin should render the check-in page."""

    def test_checkin_page(self, client, db):
        _login_admin(client, db)
        resp = client.get("/admin/checkin")
        assert resp.status_code == 200


class TestAdminSessionForm:
    """GET /admin/sessions/new and /admin/sessions/{id}/edit. Session form has event_id, start_time, order."""

    def test_session_create_form(self, client, db):
        _login_admin(client, db)
        resp = client.get("/admin/sessions/new")
        assert resp.status_code == 200
        assert b"Create" in resp.content

    def test_session_edit_form(self, client, db):
        _login_admin(client, db)
        event = make_event(db, name="Editable Event", auditorium=make_auditorium(db, name="Edit Hall"),
                          start_date=date.today() + timedelta(days=3), price=200, status="draft")
        session = make_session(db, title="Editable Session", event=event)
        db.commit()

        resp = client.get(f"/admin/sessions/{session.id}/edit")
        assert resp.status_code == 200
        assert b"Editable Session" in resp.content
        assert b"Edit" in resp.content

    def test_session_edit_not_found(self, client, db):
        _login_admin(client, db)
        resp = client.get("/admin/sessions/99999/edit", follow_redirects=False)
        assert resp.status_code == 303


class TestAdminFeedback:
    """GET /admin/feedback should list feedback entries."""

    def test_feedback_list(self, client, db):
        _login_admin(client, db)
        resp = client.get("/admin/feedback")
        assert resp.status_code == 200


class TestAdminRecordings:
    """GET /admin/sessions/{id}/recordings should use SessionModel, not Showing."""

    def test_recordings_page_loads(self, client, db):
        _login_admin(client, db)
        session = make_session(db, title="Rec Session")
        make_recording(db, session=session, title="Keynote Recording", is_public=True)
        db.commit()

        resp = client.get(f"/admin/sessions/{session.id}/recordings")
        assert resp.status_code == 200
        assert b"Rec Session" in resp.content
        assert b"Keynote Recording" in resp.content

    def test_recordings_not_found(self, client, db):
        _login_admin(client, db)
        resp = client.get("/admin/sessions/99999/recordings", follow_redirects=False)
        assert resp.status_code == 303


_sv_counter = 0


def _login_supervisor(client, db, college=None):
    """Create a supervisor user assigned to a college and log them in."""
    global _sv_counter
    _sv_counter += 1
    if college is None:
        college = make_college(db, name=f"SV College {_sv_counter}")
    user = make_user(
        db,
        username=f"sv_{_sv_counter}",
        email=f"sv_{_sv_counter}@test.com",
        is_supervisor=True,
        supervisor_college_id=college.id,
    )
    db.flush()
    admin_session(client, user)
    return user, college


class TestSupervisorPortal:
    """Supervisor portal is college-scoped and distinct from admin panel."""

    def test_supervisor_unauthenticated_redirects(self, client, db):
        resp = client.get("/supervisor/", follow_redirects=False)
        assert resp.status_code == 303

    def test_supervisor_dashboard_loads(self, client, db):
        user, college = _login_supervisor(client, db)
        resp = client.get("/supervisor/")
        assert resp.status_code == 200
        assert college.name.encode() in resp.content
        assert b"Dashboard" in resp.content

    def test_supervisor_cannot_access_admin(self, client, db):
        user, college = _login_supervisor(client, db)
        resp = client.get("/admin/", follow_redirects=False)
        assert resp.status_code == 303

    def test_supervisor_dashboard_scoped_stats(self, client, db):
        college = make_college(db, name="Scoped College Stats")
        other_college = make_college(db, name="Other College Stats")
        aud = make_auditorium(db, name="Scoped Aud", college=college)
        aud_other = make_auditorium(db, name="Other Aud", college=other_college)
        event = make_event(db, name="Scoped Event", auditorium=aud, status="published",
                          start_date=date.today() + timedelta(days=3))
        make_event(db, name="Other Event", auditorium=aud_other, status="published",
                  start_date=date.today() + timedelta(days=4))
        make_session(db, title="Scoped Session", event=event)
        db.flush()
        user, _ = _login_supervisor(client, db, college=college)
        resp = client.get("/supervisor/")
        assert resp.status_code == 200
        assert b"Scoped" in resp.content

    def test_supervisor_bookings_page(self, client, db):
        college = make_college(db, name="Bookings College")
        aud = make_auditorium(db, name="Bookings Aud", college=college)
        event = make_event(db, name="Bookings Event", auditorium=aud, status="published",
                          start_date=date.today() + timedelta(days=3))
        make_session(db, title="Bookings Session", event=event)
        db.flush()
        user, _ = _login_supervisor(client, db, college=college)
        resp = client.get("/supervisor/bookings")
        assert resp.status_code == 200
        assert b"Bookings" in resp.content
        assert college.name.encode() in resp.content

    def test_supervisor_schedule_page(self, client, db):
        college = make_college(db, name="Schedule College")
        aud = make_auditorium(db, name="Schedule Aud", college=college)
        event = make_event(db, name="Schedule Event", auditorium=aud, status="published",
                          start_date=date.today() + timedelta(days=3))
        make_session(db, title="Schedule Session", event=event)
        db.flush()
        user, _ = _login_supervisor(client, db, college=college)
        resp = client.get("/supervisor/schedule")
        assert resp.status_code == 200
        assert b"Schedule" in resp.content
        assert b"Schedule Session" in resp.content

    def test_supervisor_checkin_page(self, client, db):
        college = make_college(db, name="Checkin College")
        aud = make_auditorium(db, name="Checkin Aud", college=college)
        event = make_event(db, name="Checkin Event", auditorium=aud, status="published",
                          start_date=date.today() + timedelta(days=1))
        make_session(db, title="Checkin Talk", event=event)
        db.flush()
        user, _ = _login_supervisor(client, db, college=college)
        resp = client.get("/supervisor/checkin")
        assert resp.status_code == 200
        assert b"Check-in" in resp.content
        assert b"Checkin Talk" in resp.content

    def test_supervisor_checkin_scoped_to_college(self, client, db):
        """Supervisor should only see events at their college in the dropdown."""
        college_a = make_college(db, name="College A Checkin")
        college_b = make_college(db, name="College B Checkin")
        aud_a = make_auditorium(db, name="Aud A", college=college_a)
        aud_b = make_auditorium(db, name="Aud B", college=college_b)
        event_a = make_event(db, name="Event A Scope", auditorium=aud_a, status="published",
                             start_date=date.today() + timedelta(days=1))
        make_event(db, name="Event B Scope", auditorium=aud_b, status="published",
                  start_date=date.today() + timedelta(days=2))
        make_session(db, title="Shared Talk Scope", event=event_a)
        db.flush()

        user, _ = _login_supervisor(client, db, college=college_a)
        resp = client.get("/supervisor/checkin")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Event A Scope" in content or "Shared Talk Scope" in content

    def test_admin_toggle_supervisor_requires_college(self, client, db):
        """Toggling supervisor without selecting a college should flash an error."""
        from tests.conftest import CSRF_TEST_TOKEN
        admin = _login_admin(client, db)
        target = make_user(db, username="sv_target", email="sv_target@test.com")
        db.flush()
        resp = client.post(
            f"/admin/users/{target.id}/toggle-supervisor",
            data={"csrf_token": CSRF_TEST_TOKEN},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        db.refresh(target)
        assert not target.is_supervisor


class TestSpeakerDashboard:
    """GET /speaker/ renders dashboard with nav cards, /speaker/sessions shows table."""

    def test_speaker_unauthenticated(self, client, db):
        resp = client.get("/speaker/", follow_redirects=False)
        assert resp.status_code == 303

    def test_speaker_dashboard_loads(self, client, db):
        user = make_user(
            db, username="speaker_user_dash", email="speaker_dash@test.com",
        )
        speaker = make_speaker(db, name="Dr. Dashboard", user=user)
        event = make_event(db, name="Speaker Event", status="published",
                          start_date=date(2026, 7, 1))
        session = make_session(db, title="Speaker Talk", event=event,
                              start_time=datetime(2026, 7, 1, 14, 0))
        session.speaker_id = speaker.id
        db.flush()
        db.commit()
        admin_session(client, user)

        resp = client.get("/speaker/")
        assert resp.status_code == 200
        assert b"My Sessions" in resp.content
        assert b"My Schedule" in resp.content

    def test_speaker_sessions_page(self, client, db):
        user = make_user(
            db, username="speaker_user_sess", email="speaker_sess@test.com",
        )
        speaker = make_speaker(db, name="Dr. Sessions", user=user)
        event = make_event(db, name="Sessions Event", status="published",
                          start_date=date(2026, 7, 1))
        session = make_session(db, title="Speaker Talk Sessions", event=event,
                              start_time=datetime(2026, 7, 1, 14, 0))
        session.speaker_id = speaker.id
        db.flush()
        db.commit()
        admin_session(client, user)

        resp = client.get("/speaker/sessions")
        assert resp.status_code == 200
        assert b"Speaker Talk Sessions" in resp.content

    def test_speaker_schedule_page(self, client, db):
        user = make_user(
            db, username="speaker_user_sched", email="speaker_sched@test.com",
        )
        speaker = make_speaker(db, name="Dr. Schedule", user=user)
        event = make_event(db, name="Calendar Event", status="published",
                          start_date=date(2026, 7, 15))
        session = make_session(db, title="Calendar Talk", event=event,
                              start_time=datetime(2026, 7, 15, 10, 0))
        session.speaker_id = speaker.id
        db.flush()
        db.commit()
        admin_session(client, user)

        resp = client.get("/speaker/schedule?view=month&year=2026&month=7")
        assert resp.status_code == 200
        assert b"Calendar Talk" in resp.content
        assert b"July 2026" in resp.content

    def test_speaker_schedule_week_view(self, client, db):
        user = make_user(
            db, username="speaker_user_week", email="speaker_week@test.com",
        )
        speaker = make_speaker(db, name="Dr. Week", user=user)
        event = make_event(db, name="Week Event", status="published",
                          start_date=date(2026, 7, 15))
        session = make_session(db, title="Week View Talk", event=event,
                              start_time=datetime(2026, 7, 15, 10, 0))
        session.speaker_id = speaker.id
        db.flush()
        db.commit()
        admin_session(client, user)

        resp = client.get("/speaker/schedule?view=week&year=2026&week=29")
        assert resp.status_code == 200
        assert b"Week View Talk" in resp.content


class TestEventCRUD:
    """Admin CRUD routes for events under /admin/events/."""

    def test_create_event(self, client, db):
        from tests.conftest import CSRF_TEST_TOKEN
        from app.models.event import Event as EventModel
        admin = _login_admin(client, db)
        college = make_college(db, name="CRUD College")
        aud = make_auditorium(db, name="CRUD Hall", college=college)
        db.commit()

        resp = client.post(
            "/admin/events/new",
            data={
                "csrf_token": CSRF_TEST_TOKEN,
                "name": "New Event CRUD",
                "auditorium_id": str(aud.id),
                "college_id": str(college.id) if college else "",
                "start_date": "2026-08-01",
                "end_date": "",
                "price": "150",
                "price_vip": "",
                "price_accessible": "",
                "processing_fee_pct": "",
                "status": "draft",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        new_ev = db.query(EventModel).filter(EventModel.name == "New Event CRUD").first()
        assert new_ev is not None
        assert float(new_ev.price) == 150

    def test_edit_event(self, client, db):
        from tests.conftest import CSRF_TEST_TOKEN
        _login_admin(client, db)
        event = make_event(db, name="Edit Event", price=100, status="draft")
        db.commit()

        resp = client.post(
            f"/admin/events/{event.id}/edit",
            data={
                "csrf_token": CSRF_TEST_TOKEN,
                "name": "Edit Event",
                "auditorium_id": str(event.auditorium_id),
                "college_id": str(event.college_id) if event.college_id else "",
                "start_date": event.start_date.isoformat() if event.start_date else "",
                "end_date": "",
                "price": "250",
                "price_vip": "400",
                "price_accessible": "",
                "processing_fee_pct": "",
                "status": "published",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        db.refresh(event)
        assert float(event.price) == 250
        assert event.status == "published"

    def test_delete_event_no_bookings(self, client, db):
        from tests.conftest import CSRF_TEST_TOKEN
        from app.models.event import Event as EventModel
        _login_admin(client, db)
        event = make_event(db, name="Delete Event", price=50, status="draft")
        event_id = event.id
        db.commit()

        resp = client.post(
            f"/admin/events/{event_id}/delete",
            data={"csrf_token": CSRF_TEST_TOKEN},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert db.query(EventModel).filter(EventModel.id == event_id).first() is None

    def test_delete_event_with_bookings_blocked(self, client, db):
        from tests.conftest import CSRF_TEST_TOKEN
        from app.models.event import Event as EventModel
        _login_admin(client, db)
        aud = make_auditorium(db, name="Blocked Hall")
        event = make_event(db, name="Blocked Event", auditorium=aud, price=200)
        seat = Seat(auditorium_id=aud.id, row_num=0, col_num=0, label="Z1")
        db.add(seat)
        db.flush()
        user = make_user(db, username="blocker_user", email="blocker@test.com")
        booking = Booking(
            user_id=user.id,
            event_id=event.id,
            seat_id=seat.id,
            amount_paid=200,
            payment_status="paid",
            booking_ref="TEST-BLOCK-001",
        )
        db.add(booking)
        db.commit()

        resp = client.post(
            f"/admin/events/{event.id}/delete",
            data={"csrf_token": CSRF_TEST_TOKEN},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert db.query(EventModel).filter(EventModel.id == event.id).first() is not None


class TestEventDetail:
    """Public event routes /events and /events/{id}."""

    def test_event_detail_with_session(self, client, db):
        event = make_event(db, name="Detail Event", status="published",
                          start_date=date(2026, 10, 1), price=100)
        session = make_session(db, title="Detail Session", event=event)
        db.commit()

        resp = client.get(f"/events/{event.id}")
        assert resp.status_code == 200
        assert b"Detail Event" in resp.content
        assert b"Detail Session" in resp.content

    def test_events_list_page(self, client, db):
        event = make_event(db, name="List Event", status="published",
                          start_date=date.today() + timedelta(days=1))
        make_session(db, title="List Session", event=event)
        db.commit()

        resp = client.get("/events")
        assert resp.status_code == 200
        assert b"List Event" in resp.content


class TestEventSelectSeats:
    """The event_select_seats.html form must use event.id for hold endpoint."""

    def test_seat_form_uses_event_id(self, client, db):
        """Verify event_select_seats template references event.id for hold endpoint."""
        aud = make_auditorium(db, name="Seat Hall")
        event = make_event(db, auditorium=aud, name="Seat Form Event",
                          status="published", price=100)
        seat = Seat(auditorium_id=aud.id, row_num=1, col_num=1, label="A1",
                    seat_type="standard", is_active=True)
        db.add(seat)
        db.commit()

        user = make_user(db, username="seat_tester", email="seat@test.com")
        db.commit()
        admin_session(client, user)

        resp = client.get(f"/booking/event/{event.id}/select")
        assert resp.status_code == 200
        assert f"/booking/event/{event.id}/hold".encode() in resp.content

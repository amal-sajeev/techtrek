"""Tests for admin pages, supervisor checkin, speaker dashboard, admin recordings."""

from datetime import datetime, timedelta

from app.models.booking import Booking
from app.models.seat import Seat
from tests.conftest import (
    admin_session,
    make_auditorium,
    make_feedback,
    make_recording,
    make_session,
    make_showing,
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
        """Dashboard must render when bookings reference showings (not sessions)."""
        admin = _login_admin(client, db)
        session = make_session(db, title="Dashboard Talk")
        aud = make_auditorium(db, name="Dashboard Hall")
        showing = make_showing(
            db, session=session, auditorium=aud,
            start_time=datetime.now() + timedelta(days=1),
            price=50, status="published",
        )
        seat = Seat(auditorium_id=aud.id, row_num=0, col_num=0, label="A1")
        db.add(seat)
        db.flush()
        user = make_user(db, username="booker_dash", email="booker_dash@test.com")
        booking = Booking(
            user_id=user.id,
            showing_id=showing.id,
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
    """GET /admin/sessions should show sessions with showing-level details."""

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
        session = make_session(db, title="Admin Session Test")
        make_showing(
            db,
            session=session,
            status="published",
            start_time=datetime.now() + timedelta(days=5),
            price=100,
        )
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

    def test_schedule_with_showing(self, client, db):
        _login_admin(client, db)
        session = make_session(db, title="Schedule Test")
        make_showing(
            db,
            session=session,
            status="published",
            start_time=datetime.now() + timedelta(days=2),
        )
        db.commit()

        resp = client.get("/admin/schedule")
        assert resp.status_code == 200
        assert b"Schedule Test" in resp.content


class TestAdminBookings:
    """GET /admin/bookings should list bookings using showing_id."""

    def test_bookings_list_empty(self, client, db):
        _login_admin(client, db)
        resp = client.get("/admin/bookings")
        assert resp.status_code == 200

    def test_bookings_list_with_data(self, client, db):
        _login_admin(client, db)
        session = make_session(db, title="Booked Session")
        aud = make_auditorium(db, name="Booking Hall")
        showing = make_showing(db, session=session, auditorium=aud, price=100)
        seat = Seat(auditorium_id=aud.id, row_num=0, col_num=0, label="B1")
        db.add(seat)
        db.flush()
        user = make_user(db, username="booker_admin", email="booker_admin@test.com")
        booking = Booking(
            user_id=user.id,
            showing_id=showing.id,
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
    """GET /admin/sessions/new and /admin/sessions/{id}/edit."""

    def test_session_create_form(self, client, db):
        _login_admin(client, db)
        resp = client.get("/admin/sessions/new")
        assert resp.status_code == 200
        assert b"Create" in resp.content

    def test_session_edit_form(self, client, db):
        _login_admin(client, db)
        session = make_session(db, title="Editable Session")
        aud = make_auditorium(db, name="Edit Hall")
        showing = make_showing(
            db, session=session, auditorium=aud,
            start_time=datetime.now() + timedelta(days=3),
            price=200, status="draft",
        )
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


class TestSupervisorCheckin:
    """GET /supervisor/ should render with Showing objects (s.session.title)."""

    def test_checkin_unauthenticated(self, client, db):
        resp = client.get("/supervisor/", follow_redirects=False)
        assert resp.status_code == 303

    def test_checkin_page_empty(self, client, db):
        user = _login_admin(client, db)
        resp = client.get("/supervisor/")
        assert resp.status_code == 200
        assert b"Supervisor Check-in" in resp.content

    def test_checkin_page_with_showings(self, client, db):
        """Showing dropdown must display session title via s.session.title."""
        _login_admin(client, db)
        session = make_session(db, title="Checkin Talk")
        make_showing(
            db, session=session, status="published",
            start_time=datetime.now() + timedelta(days=1),
        )
        db.commit()

        resp = client.get("/supervisor/")
        assert resp.status_code == 200
        assert b"Checkin Talk" in resp.content


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
        session = make_session(db, title="Speaker Talk")
        session.speaker_id = speaker.id
        db.flush()
        make_showing(
            db, session=session, status="published",
            start_time=datetime(2026, 7, 1, 14, 0),
        )
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
        session = make_session(db, title="Speaker Talk Sessions")
        session.speaker_id = speaker.id
        db.flush()
        make_showing(
            db, session=session, status="published",
            start_time=datetime(2026, 7, 1, 14, 0),
        )
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
        session = make_session(db, title="Calendar Talk")
        session.speaker_id = speaker.id
        db.flush()
        make_showing(
            db, session=session, status="published",
            start_time=datetime(2026, 7, 15, 10, 0),
        )
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
        session = make_session(db, title="Week View Talk")
        session.speaker_id = speaker.id
        db.flush()
        make_showing(
            db, session=session, status="published",
            start_time=datetime(2026, 7, 15, 10, 0),
        )
        db.commit()
        admin_session(client, user)

        resp = client.get("/speaker/schedule?view=week&year=2026&week=29")
        assert resp.status_code == 200
        assert b"Week View Talk" in resp.content


class TestShowingCRUD:
    """Admin CRUD routes for showings under /admin/sessions/{id}/showings/."""

    def test_create_showing(self, client, db):
        from tests.conftest import CSRF_TEST_TOKEN
        admin = _login_admin(client, db)
        session = make_session(db, title="Showing CRUD Session")
        aud = make_auditorium(db, name="CRUD Hall")
        db.commit()

        resp = client.post(
            f"/admin/sessions/{session.id}/showings/new",
            data={
                "csrf_token": CSRF_TEST_TOKEN,
                "auditorium_id": str(aud.id),
                "start_time": "2026-08-01T10:00",
                "duration_minutes": "45",
                "price": "150",
                "price_vip": "",
                "price_accessible": "",
                "processing_fee_pct": "",
                "status": "draft",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        from app.models.showing import Showing as ShowingModel
        new_sh = db.query(ShowingModel).filter(ShowingModel.session_id == session.id).first()
        assert new_sh is not None
        assert new_sh.price == 150

    def test_edit_showing(self, client, db):
        from tests.conftest import CSRF_TEST_TOKEN
        _login_admin(client, db)
        session = make_session(db, title="Edit Showing Sess")
        showing = make_showing(db, session=session, price=100, status="draft")
        db.commit()

        resp = client.post(
            f"/admin/sessions/{session.id}/showings/{showing.id}/edit",
            data={
                "csrf_token": CSRF_TEST_TOKEN,
                "auditorium_id": str(showing.auditorium_id),
                "start_time": "2026-09-15T14:00",
                "duration_minutes": "60",
                "price": "250",
                "price_vip": "400",
                "price_accessible": "",
                "processing_fee_pct": "",
                "status": "published",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        db.refresh(showing)
        assert showing.price == 250
        assert showing.status == "published"

    def test_delete_showing_no_bookings(self, client, db):
        from tests.conftest import CSRF_TEST_TOKEN
        _login_admin(client, db)
        session = make_session(db, title="Delete Showing Sess")
        showing = make_showing(db, session=session, price=50, status="draft")
        showing_id = showing.id
        db.commit()

        resp = client.post(
            f"/admin/sessions/{session.id}/showings/{showing_id}/delete",
            data={"csrf_token": CSRF_TEST_TOKEN},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        from app.models.showing import Showing as ShowingModel
        assert db.query(ShowingModel).filter(ShowingModel.id == showing_id).first() is None

    def test_delete_showing_with_bookings_blocked(self, client, db):
        from tests.conftest import CSRF_TEST_TOKEN
        _login_admin(client, db)
        session = make_session(db, title="Blocked Delete Sess")
        aud = make_auditorium(db, name="Blocked Hall")
        showing = make_showing(db, session=session, auditorium=aud, price=200)
        seat = Seat(auditorium_id=aud.id, row_num=0, col_num=0, label="Z1")
        db.add(seat)
        db.flush()
        user = make_user(db, username="blocker_user", email="blocker@test.com")
        booking = Booking(
            user_id=user.id,
            showing_id=showing.id,
            seat_id=seat.id,
            amount_paid=200,
            payment_status="paid",
            booking_ref="TEST-BLOCK-001",
        )
        db.add(booking)
        db.commit()

        resp = client.post(
            f"/admin/sessions/{session.id}/showings/{showing.id}/delete",
            data={"csrf_token": CSRF_TEST_TOKEN},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        from app.models.showing import Showing as ShowingModel
        assert db.query(ShowingModel).filter(ShowingModel.id == showing.id).first() is not None


class TestSessionDetailMultiShowing:
    """Session detail page should show a venues card when multiple showings exist."""

    def test_single_showing_no_venues_card(self, client, db):
        session = make_session(db, title="Single Showing Detail")
        make_showing(db, session=session, status="published",
                     start_time=datetime(2026, 10, 1, 10, 0), price=100)
        db.commit()

        resp = client.get(f"/sessions/{session.id}")
        assert resp.status_code == 200
        assert b"Single Showing Detail" in resp.content
        assert b"session-venues-card" not in resp.content

    def test_multi_showing_venues_card(self, client, db):
        session = make_session(db, title="Multi Showing Detail")
        aud1 = make_auditorium(db, name="Venue Alpha")
        aud2 = make_auditorium(db, name="Venue Beta")
        make_showing(db, session=session, auditorium=aud1, status="published",
                     start_time=datetime(2026, 10, 5, 10, 0), price=100)
        make_showing(db, session=session, auditorium=aud2, status="published",
                     start_time=datetime(2026, 10, 12, 14, 0), price=150)
        db.commit()

        resp = client.get(f"/sessions/{session.id}")
        assert resp.status_code == 200
        assert b"Multi Showing Detail" in resp.content
        assert b"session-venues-card" in resp.content
        assert b"Browse 2 Showings" in resp.content
        assert b"Venue Alpha" in resp.content

    def test_showings_browser_page(self, client, db):
        session = make_session(db, title="Browser Test Session")
        aud1 = make_auditorium(db, name="Hall One")
        aud2 = make_auditorium(db, name="Hall Two")
        make_showing(db, session=session, auditorium=aud1, status="published",
                     start_time=datetime(2026, 11, 1, 10, 0), price=200)
        make_showing(db, session=session, auditorium=aud2, status="published",
                     start_time=datetime(2026, 11, 5, 14, 0), price=300)
        db.commit()

        resp = client.get(f"/sessions/{session.id}/showings")
        assert resp.status_code == 200
        assert b"Browser Test Session" in resp.content
        assert b"Hall One" in resp.content
        assert b"Hall Two" in resp.content
        assert b"2 showings" in resp.content


class TestSelectSeatShowingId:
    """The select_seat.html form must use showing.id, not lecture.id."""

    def test_seat_form_uses_showing_id(self, client, db):
        """Verify select_seat template references showing.id for hold endpoint."""
        import re
        session = make_session(db, title="Seat Form Test")
        aud = make_auditorium(db, name="Seat Hall")
        showing = make_showing(db, session=session, auditorium=aud,
                               status="published", price=100,
                               start_time=datetime(2026, 11, 1, 10, 0))
        seat = Seat(auditorium_id=aud.id, row_num=0, col_num=0, label="A1",
                    seat_type="standard", is_active=True)
        db.add(seat)
        db.commit()

        user = make_user(db, username="seat_tester", email="seat@test.com")
        db.commit()
        admin_session(client, user)

        resp = client.get(f"/booking/select/{showing.id}")
        assert resp.status_code == 200
        assert f"/booking/hold/{showing.id}".encode() in resp.content
        assert f"/booking/hold/{session.id}".encode() not in resp.content or session.id == showing.id

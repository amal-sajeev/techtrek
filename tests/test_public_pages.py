"""Tests for public-facing pages (home, sessions, schedule, recordings)."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from app.models.booking import Booking
from app.models.seat import Seat
from tests.conftest import (
    admin_session,
    make_auditorium,
    make_college,
    make_event,
    make_recording,
    make_session,
    make_testimonial,
    make_feedback,
    make_user,
)


class TestHomePage:
    """GET / must return 200 with and without data."""

    def test_home_empty_db(self, client, db):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"TechTrek" in resp.content

    def test_home_with_upcoming_event(self, client, db):
        aud = make_auditorium(db, name="Hall A")
        event = make_event(
            db,
            name="Quantum 101",
            auditorium=aud,
            start_date=date.today() + timedelta(days=3),
            price=99,
            status="published",
        )
        make_session(db, title="Quantum 101", event=event)
        db.commit()

        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Quantum 101" in resp.content

    def test_home_with_testimonials(self, client, db):
        make_testimonial(db, quote="Amazing event!", student_name="Alice")
        db.commit()

        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Amazing event!" in resp.content

    def test_home_with_featured_feedback(self, client, db):
        user = make_user(db, username="fb_user", email="fb@test.com")
        event = make_event(db, name="AI Talk", price=50)
        make_feedback(
            db,
            user=user,
            event=event,
            rating=5,
            comment="Fantastic session!",
            allow_public=True,
            is_featured=True,
        )
        db.commit()

        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Fantastic session!" in resp.content

    def test_home_price_from_event(self, client, db):
        """Price should appear on the events listing page."""
        aud = make_auditorium(db, name="Hall B")
        make_event(
            db,
            name="Price Check",
            auditorium=aud,
            start_date=date.today() + timedelta(days=5),
            price=299,
            status="published",
        )
        db.commit()

        resp = client.get("/events")
        assert resp.status_code == 200
        assert b"299" in resp.content


class TestSessionsList:
    """GET /sessions must list published sessions (sessions within published events)."""

    def test_sessions_empty(self, client, db):
        resp = client.get("/sessions")
        assert resp.status_code == 200

    def test_sessions_with_data(self, client, db):
        event = make_event(db, name="Cloud Event", status="published",
                          start_date=date.today() + timedelta(days=2))
        make_session(db, title="Cloud Computing", event=event)
        db.commit()

        resp = client.get("/sessions")
        assert resp.status_code == 200
        assert b"Cloud Computing" in resp.content


class TestSessionDetail:
    """GET /sessions/{id} must show session details with event."""

    def test_session_detail_not_found(self, client, db):
        resp = client.get("/sessions/99999")
        assert resp.status_code == 404

    def test_session_detail_with_event(self, client, db):
        event = make_event(db, name="Detail Event", status="published",
                          start_date=date.today() + timedelta(days=4), price=199)
        session = make_session(db, title="Detail Test Session", event=event)
        db.commit()

        resp = client.get(f"/sessions/{session.id}")
        assert resp.status_code == 200
        assert b"Detail Test Session" in resp.content


class TestSchedulePage:
    """GET /schedule must group events by date."""

    def test_schedule_empty(self, client, db):
        resp = client.get("/schedule")
        assert resp.status_code == 200

    def test_schedule_with_event(self, client, db):
        event = make_event(db, name="ML Event", status="published",
                          start_date=date.today() + timedelta(days=1))
        make_session(db, title="ML Workshop", event=event)
        db.commit()

        resp = client.get("/schedule")
        assert resp.status_code == 200
        assert b"ML Workshop" in resp.content


class TestRecordingsPage:
    """GET /recordings must list sessions with public recordings."""

    def test_recordings_unauthenticated_redirects(self, client, db):
        resp = client.get("/recordings", follow_redirects=False)
        assert resp.status_code == 303

    def test_recordings_authenticated_no_bookings(self, client, db):
        user = make_user(db, username="rec_user", email="rec@test.com")
        db.commit()
        admin_session(client, user)
        resp = client.get("/recordings")
        assert resp.status_code == 200

    def test_recordings_with_booked_event(self, client, db):
        """Recordings page renders correctly using speaker_name and event/session dates."""
        user = make_user(db, username="rec_booker", email="rec_booker@test.com")
        aud = make_auditorium(db, name="Rec Hall")
        event = make_event(
            db, auditorium=aud, name="Recorded Event",
            start_date=date(2026, 6, 15), price=100, status="completed",
        )
        session = make_session(
            db, title="Recorded Talk", speaker_name="Prof. Rec", event=event,
            start_time=datetime(2026, 6, 15, 10, 0),
        )
        make_recording(db, session=session, is_public=True)
        seat = Seat(auditorium_id=aud.id, row_num=0, col_num=0, label="R1")
        db.add(seat)
        db.flush()
        booking = Booking(
            user_id=user.id,
            event_id=event.id,
            seat_id=seat.id,
            amount_paid=100,
            payment_status="paid",
            booking_ref="TEST-REC-001",
        )
        db.add(booking)
        db.commit()
        admin_session(client, user)

        resp = client.get("/recordings")
        assert resp.status_code == 200
        assert b"Recorded Talk" in resp.content
        assert b"Prof. Rec" in resp.content
        assert b"Jun 15, 2026" in resp.content

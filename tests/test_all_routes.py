"""Comprehensive smoke tests for every frontend and backend route.

Asserts that no route returns a 500 Internal Server Error.  Covers all
routers: auth, public, booking, admin, supervisor, speaker, and webhook.
"""

from datetime import date, timedelta
import json

from app.models.booking import Booking
from app.models.city import City
from app.models.coupon import Coupon
from app.models.certificate_template import CertificateTemplate
from app.models.feedback_template import FeedbackTemplate
from app.models.newsletter import Newsletter
from app.models.poll import Poll
from app.models.seat import Seat
from app.models.seat_type import SeatType
from tests.conftest import (
    admin_session,
    CSRF_TEST_TOKEN,
    make_auditorium,
    make_college,
    make_event,
    make_recording,
    make_session,
    make_speaker,
    make_user,
)

_counter = {"v": 0}


def _uid():
    _counter["v"] += 1
    return _counter["v"]


def _set_csrf(client):
    """Inject a session cookie containing only a CSRF token (no user)."""
    import base64
    import json as _json
    from itsdangerous import TimestampSigner
    from app.config import settings
    data = base64.b64encode(_json.dumps({
        "csrf_token": CSRF_TEST_TOKEN,
    }).encode()).decode()
    signer = TimestampSigner(settings.secret_key)
    client.cookies.set("session", signer.sign(data).decode())


def _login_admin(client, db):
    n = _uid()
    user = make_user(db, username=f"ra{n}", email=f"ra{n}@t.co", is_admin=True)
    db.commit()
    admin_session(client, user)
    return user


def _login_user(client, db, **kw):
    n = _uid()
    user = make_user(
        db,
        username=kw.pop("username", f"ru{n}"),
        email=kw.pop("email", f"ru{n}@t.co"),
        **kw,
    )
    db.commit()
    admin_session(client, user)
    return user


def _login_supervisor(client, db, college=None):
    n = _uid()
    if college is None:
        college = make_college(db, name=f"SvC{n}")
    user = make_user(
        db, username=f"rs{n}", email=f"rs{n}@t.co",
        is_supervisor=True, supervisor_college_id=college.id,
    )
    db.commit()
    admin_session(client, user)
    return user, college


def _login_speaker(client, db):
    n = _uid()
    user = make_user(db, username=f"rk{n}", email=f"rk{n}@t.co")
    speaker = make_speaker(db, name=f"Dr.{n}", user=user)
    db.commit()
    admin_session(client, user)
    return user, speaker


def _evt(db, **kw):
    n = _uid()
    aud = make_auditorium(db, name=f"H{n}")
    event = make_event(
        db, name=kw.pop("name", f"E{n}"), auditorium=aud,
        start_date=kw.pop("start_date", date.today() + timedelta(days=5)),
        price=kw.pop("price", 0), status=kw.pop("status", "published"), **kw,
    )
    seat = Seat(auditorium_id=aud.id, row_num=0, col_num=0,
                label=f"A{n}", seat_type="standard", is_active=True)
    db.add(seat)
    db.flush()
    return event, aud, seat


def _bkg(db, user, event, seat, **kw):
    n = _uid()
    b = Booking(
        user_id=user.id, event_id=event.id, seat_id=seat.id,
        amount_paid=kw.pop("amount_paid", 0),
        payment_status=kw.pop("payment_status", "paid"),
        booking_ref=kw.pop("booking_ref", f"R{n}"),
        ticket_id=kw.pop("ticket_id", f"T{n}"),
        **kw,
    )
    db.add(b)
    db.flush()
    return b


# ── App-level routes ─────────────────────────────────────────────────


class TestAppLevelRoutes:
    def test_service_worker(self, client, db):
        assert client.get("/service-worker.js").status_code == 200

    def test_offline_page(self, client, db):
        assert client.get("/offline").status_code == 200

    def test_404_handler(self, client, db):
        assert client.get("/no-such-page-xyz").status_code == 404


# ── Auth routes ──────────────────────────────────────────────────────


class TestAuthRoutes:
    def test_login_page(self, client, db):
        assert client.get("/auth/login").status_code == 200

    def test_login_post_bad_creds(self, client, db):
        _set_csrf(client)
        r = client.post("/auth/login",
                        data={"username": "nobody", "password": "wrong",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_register_page(self, client, db):
        assert client.get("/auth/register").status_code == 200

    def test_register_post_empty(self, client, db):
        _set_csrf(client)
        r = client.post("/auth/register",
                        data={"username": "", "email": "", "full_name": "",
                              "password": "x", "confirm_password": "y",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_register_post_valid(self, client, db):
        _set_csrf(client)
        n = _uid()
        r = client.post("/auth/register",
                        data={"username": f"new{n}", "email": f"new{n}@t.co",
                              "full_name": f"New {n}", "college": "C",
                              "password": "StrongPass1!", "confirm_password": "StrongPass1!",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_verify_password_unauth(self, client, db):
        assert client.post("/auth/verify-password",
                           json={"password": "x"}).status_code == 401

    def test_verify_password_auth(self, client, db):
        _login_user(client, db)
        r = client.post("/auth/verify-password", json={"password": "wrong"})
        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_profile_page_unauth(self, client, db):
        assert client.get("/auth/profile",
                          follow_redirects=False).status_code == 303

    def test_profile_page_auth(self, client, db):
        _login_user(client, db)
        assert client.get("/auth/profile").status_code == 200

    def test_profile_update(self, client, db):
        _login_user(client, db)
        r = client.post("/auth/profile",
                        data={"full_name": "Up", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_speaker_invite_bad_token(self, client, db):
        assert client.get("/auth/speaker-invite/bad",
                          follow_redirects=False).status_code == 303

    def test_google_login(self, client, db):
        r = client.get("/auth/google", follow_redirects=False)
        assert r.status_code in (302, 303, 307)

    def test_google_callback_no_params(self, client, db):
        r = client.get("/auth/google/callback", follow_redirects=False)
        assert r.status_code in (302, 303, 400)

    def test_forgot_password_page(self, client, db):
        assert client.get("/auth/forgot-password").status_code == 200

    def test_forgot_password_post(self, client, db):
        _set_csrf(client)
        r = client.post("/auth/forgot-password",
                        data={"email": "x@x.com", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_reset_password_page_bad_token(self, client, db):
        assert client.get("/auth/reset-password/bad",
                          follow_redirects=False).status_code == 303

    def test_reset_password_post_bad_token(self, client, db):
        _set_csrf(client)
        r = client.post("/auth/reset-password/bad",
                        data={"password": "A1!aaaaa", "confirm_password": "A1!aaaaa",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_logout(self, client, db):
        assert client.get("/auth/logout",
                          follow_redirects=False).status_code == 303


# ── Public routes ────────────────────────────────────────────────────


class TestPublicRoutes:
    def test_home(self, client, db):
        assert client.get("/").status_code == 200

    def test_events_list(self, client, db):
        assert client.get("/events").status_code == 200

    def test_events_list_params(self, client, db):
        assert client.get("/events?q=x&sort=date&city_id=abc").status_code == 200

    def test_event_detail(self, client, db):
        ev, _, _ = _evt(db); db.commit()
        assert client.get(f"/events/{ev.id}").status_code == 200

    def test_event_detail_404(self, client, db):
        assert client.get("/events/99999").status_code == 404

    def test_sessions_list(self, client, db):
        assert client.get("/sessions").status_code == 200

    def test_session_detail_404(self, client, db):
        assert client.get("/sessions/99999").status_code == 404

    def test_schedule(self, client, db):
        assert client.get("/schedule").status_code == 200

    def test_schedule_export_pdf(self, client, db):
        assert client.get("/schedule/export-pdf").status_code == 200

    def test_api_schedule(self, client, db):
        r = client.get("/api/schedule")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_terms(self, client, db):
        assert client.get("/terms").status_code == 200

    def test_newsletter_subscribe(self, client, db):
        _set_csrf(client)
        n = _uid()
        r = client.post("/newsletter",
                        data={"email": f"ns{n}@x.com", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_newsletter_subscribe_bad(self, client, db):
        _set_csrf(client)
        r = client.post("/newsletter",
                        data={"email": "bad", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_newsletter_unsubscribe_bad_token(self, client, db):
        assert client.get("/newsletter/unsubscribe/bad").status_code == 200

    def test_ticket_not_found(self, client, db):
        r = client.get("/ticket/NONE")
        assert r.status_code in (200, 404)

    def test_ticket_found(self, client, db):
        u = _login_user(client, db)
        ev, _, s = _evt(db)
        bk = _bkg(db, u, ev, s)
        db.commit()
        assert client.get(f"/ticket/{bk.ticket_id}").status_code == 200

    def test_ticket_share_unauth(self, client, db):
        r = client.post("/ticket/X/share", json={"name": "A", "email": "a@b.c"})
        assert r.status_code == 401

    def test_ticket_claim_bad(self, client, db):
        r = client.post("/ticket/X/claim",
                        json={"login_id": "", "password": "", "share_token": ""})
        assert r.status_code in (400, 401, 404)

    def test_ticket_group_not_found(self, client, db):
        r = client.get("/tickets/group/NONE", follow_redirects=False)
        assert r.status_code in (303, 404)

    def test_certificate_verify_not_found(self, client, db):
        assert client.get("/certificate/verify/NONE").status_code == 404

    def test_certificate_verify_found(self, client, db):
        u = _login_user(client, db)
        ev, _, s = _evt(db)
        bk = _bkg(db, u, ev, s)
        db.commit()
        assert client.get(f"/certificate/verify/{bk.ticket_id}").status_code == 200

    def test_polls_display_unauth(self, client, db):
        assert client.get("/polls/1/display",
                          follow_redirects=False).status_code == 303

    def test_polls_display_admin(self, client, db):
        adm = _login_admin(client, db)
        ev, _, _ = _evt(db)
        sess = make_session(db, title=f"PS{_uid()}", event=ev)
        p = Poll(session_id=sess.id, event_id=ev.id,
                 question="?", poll_type="yes_no",
                 is_active=True, created_by=adm.id)
        db.add(p); db.commit()
        assert client.get(f"/polls/{p.id}/display").status_code == 200

    def test_recordings_unauth(self, client, db):
        assert client.get("/recordings",
                          follow_redirects=False).status_code == 303

    def test_recordings_auth(self, client, db):
        _login_user(client, db)
        assert client.get("/recordings").status_code == 200


# ── Booking routes ───────────────────────────────────────────────────


class TestBookingRoutes:
    # -- unauthenticated smoke tests --

    def test_select_seats_unauth(self, client, db):
        assert client.get("/booking/event/1/select",
                          follow_redirects=False).status_code == 303

    def test_checkout_unauth(self, client, db):
        assert client.get("/booking/event/1/checkout",
                          follow_redirects=False).status_code == 303

    def test_confirmation_unauth(self, client, db):
        assert client.get("/booking/event/1/confirmation",
                          follow_redirects=False).status_code == 303

    def test_hold_unauth(self, client, db):
        _set_csrf(client)
        r = client.post("/booking/event/1/hold",
                        data={"seat_ids": "1", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_apply_coupon_unauth(self, client, db):
        assert client.post("/booking/event/1/apply-coupon",
                           json={"code": "X"}).status_code == 401

    def test_toggle_addon_unauth(self, client, db):
        assert client.post("/booking/event/1/toggle-addon",
                           json={"addon_id": 1}).status_code == 401

    def test_create_order_unauth(self, client, db):
        assert client.post("/booking/event/1/create-order",
                           json={}).status_code == 401

    def test_verify_payment_unauth(self, client, db):
        assert client.post("/booking/event/1/verify-payment",
                           json={}).status_code == 401

    def test_pay_free_unauth(self, client, db):
        _set_csrf(client)
        r = client.post("/booking/event/1/pay",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_my_bookings_unauth(self, client, db):
        assert client.get("/booking/my",
                          follow_redirects=False).status_code == 303

    def test_detail_solo_unauth(self, client, db):
        assert client.get("/booking/detail/1",
                          follow_redirects=False).status_code == 303

    def test_detail_group_unauth(self, client, db):
        assert client.get("/booking/detail/group/x",
                          follow_redirects=False).status_code == 303

    def test_cancel_booking_unauth(self, client, db):
        _set_csrf(client)
        r = client.post("/booking/cancel/1",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_cancel_group_unauth(self, client, db):
        _set_csrf(client)
        r = client.post("/booking/cancel-group/x",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_waitlist_join_unauth(self, client, db):
        _set_csrf(client)
        r = client.post("/booking/waitlist/1",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_waitlist_leave_unauth(self, client, db):
        _set_csrf(client)
        r = client.post("/booking/waitlist/1/leave",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_certificate_unauth(self, client, db):
        assert client.get("/booking/certificate/1",
                          follow_redirects=False).status_code == 303

    def test_certificate_download_unauth(self, client, db):
        assert client.get("/booking/certificate/1/download",
                          follow_redirects=False).status_code == 303

    def test_invoice_group_unauth(self, client, db):
        assert client.get("/booking/invoice/group/x",
                          follow_redirects=False).status_code == 303

    def test_invoice_booking_unauth(self, client, db):
        assert client.get("/booking/invoice/booking/1",
                          follow_redirects=False).status_code == 303

    def test_invoice_event_unauth(self, client, db):
        assert client.get("/booking/invoice/1",
                          follow_redirects=False).status_code == 303

    # -- authenticated smoke tests --

    def test_select_seats_auth(self, client, db):
        _login_user(client, db)
        ev, _, _ = _evt(db); db.commit()
        assert client.get(f"/booking/event/{ev.id}/select").status_code == 200

    def test_my_bookings_auth(self, client, db):
        _login_user(client, db)
        assert client.get("/booking/my").status_code == 200

    def test_detail_not_found(self, client, db):
        _login_user(client, db)
        assert client.get("/booking/detail/99999",
                          follow_redirects=False).status_code == 303

    def test_detail_group_not_found(self, client, db):
        _login_user(client, db)
        assert client.get("/booking/detail/group/none",
                          follow_redirects=False).status_code == 303

    def test_checkout_no_hold(self, client, db):
        _login_user(client, db)
        ev, _, _ = _evt(db); db.commit()
        assert client.get(f"/booking/event/{ev.id}/checkout",
                          follow_redirects=False).status_code == 303

    def test_confirmation_no_booking(self, client, db):
        _login_user(client, db)
        ev, _, _ = _evt(db); db.commit()
        assert client.get(f"/booking/event/{ev.id}/confirmation",
                          follow_redirects=False).status_code == 303

    def test_waitlist_join_auth(self, client, db):
        _login_user(client, db)
        ev, _, _ = _evt(db); db.commit()
        r = client.post(f"/booking/waitlist/{ev.id}",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_waitlist_leave_auth(self, client, db):
        _login_user(client, db)
        ev, _, _ = _evt(db); db.commit()
        r = client.post(f"/booking/waitlist/{ev.id}/leave",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_apply_coupon_remove(self, client, db):
        _login_user(client, db)
        ev, _, _ = _evt(db); db.commit()
        r = client.post(f"/booking/event/{ev.id}/apply-coupon", json={"code": ""})
        assert r.status_code == 200

    def test_cancel_booking_auth(self, client, db):
        u = _login_user(client, db)
        ev, _, s = _evt(db)
        bk = _bkg(db, u, ev, s); db.commit()
        r = client.post(f"/booking/cancel/{bk.id}",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_certificate_page_auth(self, client, db):
        u = _login_user(client, db)
        ev, _, s = _evt(db)
        _bkg(db, u, ev, s); db.commit()
        r = client.get(f"/booking/certificate/99999", follow_redirects=False)
        assert r.status_code in (200, 303)


# ── Admin CRUD routes ────────────────────────────────────────────────


class TestAdminCRUDRoutes:
    # -- cities --
    def test_cities_unauth(self, client, db):
        assert client.get("/admin/cities",
                          follow_redirects=False).status_code == 303

    def test_cities_list(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/cities").status_code == 200

    def test_city_new_form(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/cities/new").status_code == 200

    def test_city_create(self, client, db):
        _login_admin(client, db)
        n = _uid()
        r = client.post("/admin/cities/new",
                        data={"name": f"Ci{n}", "state": f"S{n}",
                              "is_active": "on", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_city_edit(self, client, db):
        _login_admin(client, db)
        c = City(name=f"EC{_uid()}", state="S", is_active=True)
        db.add(c); db.commit()
        assert client.get(f"/admin/cities/{c.id}/edit").status_code == 200

    def test_city_update(self, client, db):
        _login_admin(client, db)
        c = City(name=f"UC{_uid()}", state="S", is_active=True)
        db.add(c); db.commit()
        r = client.post(f"/admin/cities/{c.id}/edit",
                        data={"name": c.name, "state": "Up",
                              "is_active": "on", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_city_delete(self, client, db):
        _login_admin(client, db)
        c = City(name=f"DC{_uid()}", state="S", is_active=True)
        db.add(c); db.commit()
        r = client.post(f"/admin/cities/{c.id}/delete",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_city_toggle(self, client, db):
        _login_admin(client, db)
        c = City(name=f"TC{_uid()}", state="S", is_active=True)
        db.add(c); db.commit()
        r = client.post(f"/admin/cities/{c.id}/toggle",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    # -- colleges --
    def test_colleges_list(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/colleges").status_code == 200

    def test_college_new_form(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/colleges/new").status_code == 200

    def test_college_create(self, client, db):
        _login_admin(client, db)
        ci = City(name=f"CC{_uid()}", state="S", is_active=True)
        db.add(ci); db.flush()
        n = _uid()
        r = client.post("/admin/colleges/new",
                        data={"name": f"Co{n}", "city_id": str(ci.id),
                              "address": "A", "is_active": "on",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_college_edit(self, client, db):
        _login_admin(client, db)
        col = make_college(db, name=f"ECo{_uid()}")
        db.commit()
        assert client.get(f"/admin/colleges/{col.id}/edit").status_code == 200

    def test_college_update(self, client, db):
        _login_admin(client, db)
        col = make_college(db, name=f"UCo{_uid()}")
        db.commit()
        r = client.post(f"/admin/colleges/{col.id}/edit",
                        data={"name": col.name, "city_id": str(col.city_id),
                              "address": "Up", "is_active": "on",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_college_delete(self, client, db):
        _login_admin(client, db)
        col = make_college(db, name=f"DCo{_uid()}")
        db.commit()
        r = client.post(f"/admin/colleges/{col.id}/delete",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    # -- auditoriums --
    def test_auditoriums_redirect(self, client, db):
        _login_admin(client, db)
        r = client.get("/admin/auditoriums", follow_redirects=False)
        assert r.status_code in (302, 303)

    def test_auditorium_create(self, client, db):
        _login_admin(client, db)
        col = make_college(db, name=f"ACo{_uid()}")
        db.commit()
        r = client.post(f"/admin/colleges/{col.id}/auditoriums/new",
                        data={"name": f"Au{_uid()}", "location": "B1",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_auditorium_edit(self, client, db):
        _login_admin(client, db)
        col = make_college(db, name=f"AECo{_uid()}")
        aud = make_auditorium(db, name=f"AE{_uid()}", college=col)
        db.commit()
        r = client.post(f"/admin/colleges/{col.id}/auditoriums/{aud.id}/edit",
                        data={"name": aud.name, "location": "Up",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_auditorium_delete(self, client, db):
        _login_admin(client, db)
        col = make_college(db, name=f"ADCo{_uid()}")
        aud = make_auditorium(db, name=f"AD{_uid()}", college=col)
        db.commit()
        r = client.post(f"/admin/colleges/{col.id}/auditoriums/{aud.id}/delete",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    # -- seat types --
    def test_seat_types_list(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/seat-types").status_code == 200

    def test_seat_type_new(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/seat-types/new").status_code == 200

    def test_seat_type_create(self, client, db):
        _login_admin(client, db)
        n = _uid()
        r = client.post("/admin/seat-types/new",
                        data={"name": f"ST{n}", "colour": "#FF0000",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_seat_type_edit(self, client, db):
        _login_admin(client, db)
        st = SeatType(name=f"EST{_uid()}", colour="#00FF00")
        db.add(st); db.commit()
        assert client.get(f"/admin/seat-types/{st.id}/edit").status_code == 200

    def test_seat_type_update(self, client, db):
        _login_admin(client, db)
        st = SeatType(name=f"UST{_uid()}", colour="#00FF00")
        db.add(st); db.commit()
        r = client.post(f"/admin/seat-types/{st.id}/edit",
                        data={"name": st.name, "colour": "#0000FF",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_seat_type_delete(self, client, db):
        _login_admin(client, db)
        st = SeatType(name=f"DST{_uid()}", colour="#FF0000")
        db.add(st); db.commit()
        r = client.post(f"/admin/seat-types/{st.id}/delete",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    # -- seat layout --
    def test_seat_layout_page(self, client, db):
        _login_admin(client, db)
        aud = make_auditorium(db, name=f"LA{_uid()}")
        db.commit()
        assert client.get(f"/admin/auditoriums/{aud.id}/layout").status_code == 200

    def test_seat_layout_save(self, client, db):
        _login_admin(client, db)
        aud = make_auditorium(db, name=f"LS{_uid()}")
        db.commit()
        r = client.post(f"/admin/auditoriums/{aud.id}/layout",
                        data={"layout_data": "[]", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    # -- speakers --
    def test_speakers_list(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/speakers").status_code == 200

    def test_speaker_new(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/speakers/new").status_code == 200

    def test_speaker_create(self, client, db):
        _login_admin(client, db)
        n = _uid()
        r = client.post("/admin/speakers/new",
                        data={"name": f"Sp{n}", "title": "Prof",
                              "bio": "Bio", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_speaker_edit(self, client, db):
        _login_admin(client, db)
        sp = make_speaker(db, name=f"ESp{_uid()}")
        db.commit()
        assert client.get(f"/admin/speakers/{sp.id}/edit").status_code == 200

    def test_speaker_update(self, client, db):
        _login_admin(client, db)
        sp = make_speaker(db, name=f"USp{_uid()}")
        db.commit()
        r = client.post(f"/admin/speakers/{sp.id}/edit",
                        data={"name": sp.name, "title": "Dr.",
                              "bio": "Up", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_speaker_delete_check(self, client, db):
        _login_admin(client, db)
        sp = make_speaker(db, name=f"ChkSp{_uid()}")
        db.commit()
        r = client.get(f"/admin/speakers/{sp.id}/delete-check")
        assert r.status_code == 200
        assert "speaker_name" in r.json()

    def test_speaker_delete_check_unauth(self, client, db):
        assert client.get("/admin/speakers/1/delete-check").status_code == 403

    def test_speaker_delete(self, client, db):
        _login_admin(client, db)
        sp = make_speaker(db, name=f"DSp{_uid()}")
        db.commit()
        r = client.post(f"/admin/speakers/{sp.id}/delete",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_speaker_invite(self, client, db):
        _login_admin(client, db)
        sp = make_speaker(db, name=f"ISp{_uid()}")
        db.commit()
        r = client.post(f"/admin/speakers/{sp.id}/invite",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    # -- events --
    def test_events_list_admin(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/events").status_code == 200

    def test_event_new_form(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/events/new").status_code == 200

    def test_event_create(self, client, db):
        _login_admin(client, db)
        col = make_college(db, name=f"EvCo{_uid()}")
        aud = make_auditorium(db, name=f"EvA{_uid()}", college=col)
        db.commit()
        r = client.post("/admin/events/new",
                        data={"name": f"NE{_uid()}", "auditorium_id": str(aud.id),
                              "college_id": str(col.id), "start_date": "2026-09-01",
                              "end_date": "", "price": "100",
                              "price_vip": "", "price_accessible": "",
                              "processing_fee_pct": "", "status": "draft",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_event_edit_form(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        assert client.get(f"/admin/events/{ev.id}/edit").status_code == 200

    def test_event_update(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        r = client.post(f"/admin/events/{ev.id}/edit",
                        data={"name": ev.name, "auditorium_id": str(ev.auditorium_id),
                              "college_id": "", "start_date": ev.start_date.isoformat(),
                              "end_date": "", "price": "200",
                              "price_vip": "", "price_accessible": "",
                              "processing_fee_pct": "", "status": "published",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_event_delete(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        r = client.post(f"/admin/events/{ev.id}/delete",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_event_status_update(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        r = client.post(f"/admin/events/{ev.id}/status",
                        json={"status": "draft"})
        assert r.status_code in (200, 303)

    def test_event_status_update_unauth(self, client, db):
        assert client.post("/admin/events/1/status",
                           json={"status": "draft"}).status_code == 401

    def test_event_agenda_template(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/events/agenda-template").status_code == 200

    def test_event_template_download(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/events/event-template").status_code == 200

    # -- coupons --
    def test_coupon_new_form(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        assert client.get(f"/admin/events/{ev.id}/coupons/new").status_code == 200

    def test_coupon_create(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        r = client.post(f"/admin/events/{ev.id}/coupons/new",
                        data={"code": f"CP{_uid()}", "discount_pct": "10",
                              "discount_amount": "", "max_uses": "100",
                              "is_active": "on", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_coupon_edit(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db)
        cp = Coupon(code=f"ECP{_uid()}", discount_pct=15,
                    event_id=ev.id, is_active=True)
        db.add(cp); db.commit()
        assert client.get(f"/admin/events/{ev.id}/coupons/{cp.id}/edit").status_code == 200

    def test_coupon_update(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db)
        cp = Coupon(code=f"UCP{_uid()}", discount_pct=15,
                    event_id=ev.id, is_active=True)
        db.add(cp); db.commit()
        r = client.post(f"/admin/events/{ev.id}/coupons/{cp.id}/edit",
                        data={"code": cp.code, "discount_pct": "20",
                              "discount_amount": "", "max_uses": "50",
                              "is_active": "on", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_coupon_delete(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db)
        cp = Coupon(code=f"DCP{_uid()}", discount_pct=10,
                    event_id=ev.id, is_active=True)
        db.add(cp); db.commit()
        r = client.post(f"/admin/events/{ev.id}/coupons/{cp.id}/delete",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    # -- certificate templates --
    def test_cert_template_list(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/certificate-templates").status_code == 200

    def test_cert_template_new(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/certificate-templates/new").status_code == 200

    def test_cert_template_create(self, client, db):
        _login_admin(client, db)
        r = client.post("/admin/certificate-templates/new",
                        data={"name": f"CT{_uid()}", "description": "T",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_cert_template_edit(self, client, db):
        adm = _login_admin(client, db)
        ct = CertificateTemplate(name=f"ECT{_uid()}", created_by=adm.id)
        db.add(ct); db.commit()
        assert client.get(f"/admin/certificate-templates/{ct.id}/edit").status_code == 200

    def test_cert_template_update(self, client, db):
        adm = _login_admin(client, db)
        ct = CertificateTemplate(name=f"UCT{_uid()}", created_by=adm.id)
        db.add(ct); db.commit()
        r = client.post(f"/admin/certificate-templates/{ct.id}/edit",
                        data={"name": ct.name, "description": "Up",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_cert_template_delete(self, client, db):
        adm = _login_admin(client, db)
        ct = CertificateTemplate(name=f"DCT{_uid()}", created_by=adm.id)
        db.add(ct); db.commit()
        r = client.post(f"/admin/certificate-templates/{ct.id}/delete",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_cert_template_designer(self, client, db):
        adm = _login_admin(client, db)
        ct = CertificateTemplate(name=f"DesCT{_uid()}", created_by=adm.id)
        db.add(ct); db.commit()
        assert client.get(f"/admin/certificate-templates/{ct.id}/designer").status_code == 200

    def test_cert_template_apply_payload_unauth(self, client, db):
        assert client.get("/admin/certificate-templates/1/apply-payload").status_code == 401

    # -- feedback templates --
    def test_fb_template_list(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/feedback-templates").status_code == 200

    def test_fb_template_new(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/feedback-templates/new").status_code == 200

    def test_fb_template_create(self, client, db):
        _login_admin(client, db)
        r = client.post("/admin/feedback-templates/new",
                        data={"name": f"FT{_uid()}", "description": "T",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_fb_template_edit(self, client, db):
        adm = _login_admin(client, db)
        ft = FeedbackTemplate(name=f"EFT{_uid()}", created_by=adm.id)
        db.add(ft); db.commit()
        assert client.get(f"/admin/feedback-templates/{ft.id}/edit").status_code == 200

    def test_fb_template_update(self, client, db):
        adm = _login_admin(client, db)
        ft = FeedbackTemplate(name=f"UFT{_uid()}", created_by=adm.id)
        db.add(ft); db.commit()
        r = client.post(f"/admin/feedback-templates/{ft.id}/edit",
                        data={"name": ft.name, "description": "Up",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_fb_template_delete(self, client, db):
        adm = _login_admin(client, db)
        ft = FeedbackTemplate(name=f"DFT{_uid()}", created_by=adm.id)
        db.add(ft); db.commit()
        r = client.post(f"/admin/feedback-templates/{ft.id}/delete",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303


# ── Admin Event Management Hub ───────────────────────────────────────


class TestAdminEventMgmt:
    def test_landing_redirect(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/event-management",
                          follow_redirects=False).status_code == 302

    def test_overview(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        assert client.get(f"/admin/event-management/{ev.id}").status_code == 200

    def test_overview_unauth(self, client, db):
        assert client.get("/admin/event-management/1",
                          follow_redirects=False).status_code == 303

    def test_bookings(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        assert client.get(f"/admin/event-management/{ev.id}/bookings").status_code == 200

    def test_checkin_get(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        assert client.get(f"/admin/event-management/{ev.id}/checkin").status_code == 200

    def test_checkin_post(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        r = client.post(f"/admin/event-management/{ev.id}/checkin",
                        data={"ticket_id": "NONE", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code in (200, 303)

    def test_waitlist(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        assert client.get(f"/admin/event-management/{ev.id}/waitlist").status_code == 200

    def test_polls_get(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        assert client.get(f"/admin/event-management/{ev.id}/polls").status_code == 200

    def test_polls_create(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db)
        sess = make_session(db, title=f"MP{_uid()}", event=ev)
        db.commit()
        r = client.post(f"/admin/event-management/{ev.id}/polls",
                        json={"session_id": sess.id, "question": "?",
                              "poll_type": "yes_no", "options": [],
                              "allow_multiple": False})
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_recordings_get(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        assert client.get(f"/admin/event-management/{ev.id}/recordings").status_code == 200

    def test_recording_add(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db)
        sess = make_session(db, title=f"MR{_uid()}", event=ev)
        db.commit()
        r = client.post(f"/admin/event-management/{ev.id}/recordings",
                        data={"url": "https://yt.com/v", "session_id": str(sess.id),
                              "title": "Rec", "is_public": "on",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_recording_toggle(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db)
        sess = make_session(db, title=f"RT{_uid()}", event=ev)
        rec = make_recording(db, session=sess, title=f"RT{_uid()}")
        db.commit()
        r = client.post(f"/admin/event-management/{ev.id}/recordings/{rec.id}/toggle",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_recording_update(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db)
        sess = make_session(db, title=f"RU{_uid()}", event=ev)
        rec = make_recording(db, session=sess, title=f"RU{_uid()}")
        db.commit()
        r = client.post(f"/admin/event-management/{ev.id}/recordings/{rec.id}/update",
                        data={"title": "Up", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_recording_delete(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db)
        sess = make_session(db, title=f"RD{_uid()}", event=ev)
        rec = make_recording(db, session=sess, title=f"RD{_uid()}")
        db.commit()
        r = client.post(f"/admin/event-management/{ev.id}/recordings/{rec.id}/delete",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_feedback(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        assert client.get(f"/admin/event-management/{ev.id}/feedback").status_code == 200

    def test_alerts_get(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        assert client.get(f"/admin/event-management/{ev.id}/alerts").status_code == 200

    def test_alerts_send(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        r = client.post(f"/admin/event-management/{ev.id}/alerts/send",
                        json={"message": "Hi", "alert_type": "info"})
        assert r.status_code == 200

    def test_alerts_send_unauth(self, client, db):
        assert client.post("/admin/event-management/1/alerts/send",
                           json={"message": "X", "alert_type": "info"}).status_code == 403

    def test_report(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        assert client.get(f"/admin/event-management/{ev.id}/report").status_code == 200

    def test_report_pdf(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db); db.commit()
        assert client.get(f"/admin/event-management/{ev.id}/report/pdf").status_code == 200

    def test_completed_hub_checkin_redirects(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db, status="completed")
        db.commit()
        r = client.get(f"/admin/event-management/{ev.id}/checkin", follow_redirects=False)
        assert r.status_code == 303
        assert f"/admin/event-management/{ev.id}" in (r.headers.get("location") or "")

    def test_completed_hub_poll_create_forbidden(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db, status="completed")
        sess = make_session(db, title=f"CP{_uid()}", event=ev)
        db.commit()
        r = client.post(
            f"/admin/event-management/{ev.id}/polls",
            json={"session_id": sess.id, "question": "?", "poll_type": "yes_no", "options": [], "allow_multiple": False},
        )
        assert r.status_code == 403
        assert r.json().get("ok") is False

    def test_completed_hub_alerts_send_forbidden(self, client, db):
        _login_admin(client, db)
        ev, _, _ = _evt(db, status="completed")
        db.commit()
        r = client.post(
            f"/admin/event-management/{ev.id}/alerts/send",
            json={"message": "Hi", "alert_type": "info"},
        )
        assert r.status_code == 403
        assert r.json().get("ok") is False


# ── Admin misc routes ────────────────────────────────────────────────


class TestAdminMisc:
    def test_dashboard_unauth(self, client, db):
        assert client.get("/admin/",
                          follow_redirects=False).status_code == 303

    def test_dashboard_auth(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/").status_code == 200

    def test_settings_page(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/settings").status_code == 200

    def test_settings_update(self, client, db):
        _login_admin(client, db)
        r = client.post("/admin/settings",
                        data={"company_name": "T", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_settings_unauth(self, client, db):
        assert client.get("/admin/settings",
                          follow_redirects=False).status_code == 303

    def test_activity_log(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/activity-log").status_code == 200

    def test_activity_log_params(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/activity-log?category=auth&q=x&page=1").status_code == 200

    def test_users_list(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/users").status_code == 200

    def test_users_search(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/users?q=test&page=1").status_code == 200

    def test_users_export(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/users/export").status_code == 200

    def test_users_export_filtered(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/users/export?q=test&use_filters=1").status_code == 200

    def test_toggle_admin(self, client, db):
        _login_admin(client, db)
        t = make_user(db, username=f"ta{_uid()}", email=f"ta{_uid()}@t.co")
        db.commit()
        r = client.post(f"/admin/users/{t.id}/toggle-admin",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_toggle_supervisor(self, client, db):
        _login_admin(client, db)
        col = make_college(db, name=f"TSC{_uid()}")
        t = make_user(db, username=f"ts{_uid()}", email=f"ts{_uid()}@t.co")
        db.commit()
        r = client.post(f"/admin/users/{t.id}/toggle-supervisor",
                        data={"college_id": str(col.id),
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_user_soft_delete(self, client, db):
        _login_admin(client, db)
        t = make_user(db, username=f"sd{_uid()}", email=f"sd{_uid()}@t.co")
        db.commit()
        r = client.post(f"/admin/users/{t.id}/delete",
                        data={"delete_type": "soft", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_metrics_page(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/metrics").status_code == 200

    def test_metrics_tab(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/metrics?tab=overview").status_code == 200

    def test_metrics_pdf(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/metrics/report.pdf").status_code == 200

    def test_waitlist_list(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/waitlist").status_code == 200

    def test_bookings_list(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/bookings").status_code == 200

    def test_bookings_export(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/bookings/export").status_code == 200

    def test_checkin_page(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/checkin").status_code == 200

    def test_checkin_post(self, client, db):
        _login_admin(client, db)
        r = client.post("/admin/checkin",
                        data={"ticket_id": "X", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code in (200, 303)

    def test_feedback_list(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/feedback").status_code == 200

    def test_schedule_admin(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/schedule").status_code == 200

    def test_sessions_list_admin(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/sessions").status_code == 200

    def test_session_new(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/sessions/new").status_code == 200

    # -- polls (admin) --
    def test_poll_toggle_unauth(self, client, db):
        assert client.post("/admin/polls/1/toggle",
                           json={}).status_code == 403

    def test_poll_close_unauth(self, client, db):
        assert client.post("/admin/polls/1/close",
                           json={}).status_code == 403

    def test_poll_delete_unauth(self, client, db):
        _set_csrf(client)
        r = client.post("/admin/polls/1/delete",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_poll_toggle_auth(self, client, db):
        adm = _login_admin(client, db)
        ev, _, _ = _evt(db)
        sess = make_session(db, title=f"APT{_uid()}", event=ev)
        p = Poll(session_id=sess.id, event_id=ev.id, question="?",
                 poll_type="yes_no", is_active=True, created_by=adm.id)
        db.add(p); db.commit()
        assert client.post(f"/admin/polls/{p.id}/toggle",
                           json={}).status_code == 200

    def test_poll_close_auth(self, client, db):
        adm = _login_admin(client, db)
        ev, _, _ = _evt(db)
        sess = make_session(db, title=f"APC{_uid()}", event=ev)
        p = Poll(session_id=sess.id, event_id=ev.id, question="?",
                 poll_type="yes_no", is_active=True, created_by=adm.id)
        db.add(p); db.commit()
        assert client.post(f"/admin/polls/{p.id}/close",
                           json={}).status_code == 200

    # -- upload / quick create (unauth) --
    def test_upload_image_unauth(self, client, db):
        _set_csrf(client)
        r = client.post("/admin/upload-image",
                        data={"csrf_token": CSRF_TEST_TOKEN})
        assert r.status_code in (401, 403)

    def test_quick_session_unauth(self, client, db):
        assert client.post("/admin/api/sessions/create-quick",
                           json={}).status_code == 401

    def test_quick_speaker_unauth(self, client, db):
        assert client.post("/admin/api/speakers/create-quick",
                           json={}).status_code == 401

    # -- newsletters --
    def test_newsletters_list(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/newsletters").status_code == 200

    def test_newsletter_new_form(self, client, db):
        _login_admin(client, db)
        assert client.get("/admin/newsletters/new").status_code == 200

    def test_newsletter_create(self, client, db):
        _login_admin(client, db)
        r = client.post("/admin/newsletters/new",
                        data={"subject": f"NL{_uid()}", "body_html": "<p>Hi</p>",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_newsletter_edit_form(self, client, db):
        _login_admin(client, db)
        nl = Newsletter(subject=f"ENL{_uid()}", body_html="<p>T</p>", status="draft")
        db.add(nl); db.commit()
        assert client.get(f"/admin/newsletters/{nl.id}/edit").status_code == 200

    def test_newsletter_update(self, client, db):
        _login_admin(client, db)
        nl = Newsletter(subject=f"UNL{_uid()}", body_html="<p>T</p>", status="draft")
        db.add(nl); db.commit()
        r = client.post(f"/admin/newsletters/{nl.id}/edit",
                        data={"subject": nl.subject, "body_html": "<p>Up</p>",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_newsletter_delete(self, client, db):
        _login_admin(client, db)
        nl = Newsletter(subject=f"DNL{_uid()}", body_html="<p>T</p>", status="draft")
        db.add(nl); db.commit()
        r = client.post(f"/admin/newsletters/{nl.id}/delete",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_newsletter_status_unauth(self, client, db):
        assert client.get("/admin/newsletters/1/status").status_code == 401

    def test_newsletter_preview(self, client, db):
        _login_admin(client, db)
        r = client.post("/admin/newsletters/preview",
                        data={"body_html": "<p>P</p>",
                              "csrf_token": CSRF_TEST_TOKEN})
        assert r.status_code == 200

    def test_newsletter_preview_unauth(self, client, db):
        _set_csrf(client)
        r = client.post("/admin/newsletters/preview",
                        data={"body_html": "<p>P</p>",
                              "csrf_token": CSRF_TEST_TOKEN})
        assert r.status_code == 401

    # -- event certificate (unauth) --
    def test_event_cert_preview_unauth(self, client, db):
        r = client.get("/admin/events/1/certificate/preview",
                        follow_redirects=False)
        assert r.status_code in (302, 303, 401, 403)

    def test_event_cert_designer_unauth(self, client, db):
        r = client.get("/admin/events/1/certificate/designer",
                        follow_redirects=False)
        assert r.status_code in (302, 303, 401, 403)

    # -- feedback toggle --
    def test_feedback_toggle_featured_unauth(self, client, db):
        _set_csrf(client)
        r = client.post("/admin/feedback/1/toggle-featured",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303


# ── Supervisor routes ────────────────────────────────────────────────


class TestSupervisorRoutes:
    def test_dashboard_unauth(self, client, db):
        assert client.get("/supervisor/",
                          follow_redirects=False).status_code == 303

    def test_dashboard_auth(self, client, db):
        _login_supervisor(client, db)
        assert client.get("/supervisor/").status_code == 200

    def test_bookings(self, client, db):
        _login_supervisor(client, db)
        assert client.get("/supervisor/bookings").status_code == 200

    def test_schedule(self, client, db):
        _login_supervisor(client, db)
        assert client.get("/supervisor/schedule").status_code == 200

    def test_checkin_get(self, client, db):
        u, col = _login_supervisor(client, db)
        aud = make_auditorium(db, name=f"SVA{_uid()}", college=col)
        make_event(db, name=f"SVE{_uid()}", auditorium=aud, status="published")
        db.commit()
        assert client.get("/supervisor/checkin").status_code == 200

    def test_checkin_post(self, client, db):
        u, col = _login_supervisor(client, db)
        aud = make_auditorium(db, name=f"SVPA{_uid()}", college=col)
        make_event(db, name=f"SVPE{_uid()}", auditorium=aud, status="published")
        db.commit()
        r = client.post("/supervisor/checkin",
                        data={"ticket_id": "X", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code in (200, 303)


# ── Speaker routes ───────────────────────────────────────────────────


class TestSpeakerRoutes:
    def test_dashboard_unauth(self, client, db):
        assert client.get("/speaker/",
                          follow_redirects=False).status_code == 303

    def test_dashboard_no_speaker(self, client, db):
        _login_user(client, db)
        assert client.get("/speaker/",
                          follow_redirects=False).status_code == 303

    def test_dashboard_auth(self, client, db):
        _login_speaker(client, db)
        assert client.get("/speaker/").status_code == 200

    def test_sessions(self, client, db):
        _login_speaker(client, db)
        assert client.get("/speaker/sessions").status_code == 200

    def test_schedule_default(self, client, db):
        _login_speaker(client, db)
        assert client.get("/speaker/schedule").status_code == 200

    def test_schedule_month(self, client, db):
        _login_speaker(client, db)
        assert client.get("/speaker/schedule?view=month&year=2026&month=7").status_code == 200

    def test_schedule_week(self, client, db):
        _login_speaker(client, db)
        assert client.get("/speaker/schedule?view=week&year=2026&week=29").status_code == 200

    def test_session_edit_get(self, client, db):
        u, sp = _login_speaker(client, db)
        ev = make_event(db, name=f"SE{_uid()}", status="published")
        sess = make_session(db, title=f"SE{_uid()}", event=ev)
        sess.speaker_id = sp.id
        db.commit()
        assert client.get(f"/speaker/sessions/{sess.id}/edit").status_code == 200

    def test_session_edit_post(self, client, db):
        u, sp = _login_speaker(client, db)
        ev = make_event(db, name=f"SEP{_uid()}", status="published")
        sess = make_session(db, title=f"SEP{_uid()}", event=ev)
        sess.speaker_id = sp.id
        db.commit()
        r = client.post(f"/speaker/sessions/{sess.id}/edit",
                        data={"title": "Up", "description": "D",
                              "duration_minutes": "45",
                              "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_session_edit_not_found(self, client, db):
        _login_speaker(client, db)
        assert client.get("/speaker/sessions/99999/edit",
                          follow_redirects=False).status_code == 303

    def test_session_polls_get(self, client, db):
        u, sp = _login_speaker(client, db)
        ev = make_event(db, name=f"SPG{_uid()}", status="published")
        sess = make_session(db, title=f"SPG{_uid()}", event=ev)
        sess.speaker_id = sp.id
        db.commit()
        assert client.get(
            f"/speaker/sessions/{sess.id}/polls?event_id={ev.id}").status_code == 200

    def test_create_poll_yes_no(self, client, db):
        u, sp = _login_speaker(client, db)
        ev = make_event(db, name=f"CPY{_uid()}", status="published")
        sess = make_session(db, title=f"CPY{_uid()}", event=ev)
        sess.speaker_id = sp.id
        db.commit()
        r = client.post(f"/speaker/sessions/{sess.id}/polls?event_id={ev.id}",
                        json={"question": "?", "poll_type": "yes_no",
                              "options": [], "allow_multiple": False})
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_create_poll_mc(self, client, db):
        u, sp = _login_speaker(client, db)
        ev = make_event(db, name=f"CPM{_uid()}", status="published")
        sess = make_session(db, title=f"CPM{_uid()}", event=ev)
        sess.speaker_id = sp.id
        db.commit()
        r = client.post(f"/speaker/sessions/{sess.id}/polls?event_id={ev.id}",
                        json={"question": "Pick", "poll_type": "multiple_choice",
                              "options": ["A", "B", "C"], "allow_multiple": False})
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_toggle_poll(self, client, db):
        u, sp = _login_speaker(client, db)
        ev = make_event(db, name=f"TP{_uid()}", status="published")
        sess = make_session(db, title=f"TP{_uid()}", event=ev)
        sess.speaker_id = sp.id
        p = Poll(session_id=sess.id, event_id=ev.id, question="?",
                 poll_type="yes_no", is_active=True, created_by=u.id)
        db.add(p); db.commit()
        assert client.post(f"/speaker/polls/{p.id}/toggle",
                           json={}).status_code == 200

    def test_close_poll(self, client, db):
        u, sp = _login_speaker(client, db)
        ev = make_event(db, name=f"CP{_uid()}", status="published")
        sess = make_session(db, title=f"CP{_uid()}", event=ev)
        sess.speaker_id = sp.id
        p = Poll(session_id=sess.id, event_id=ev.id, question="?",
                 poll_type="yes_no", is_active=True, created_by=u.id)
        db.add(p); db.commit()
        assert client.post(f"/speaker/polls/{p.id}/close",
                           json={}).status_code == 200

    def test_delete_poll(self, client, db):
        u, sp = _login_speaker(client, db)
        ev = make_event(db, name=f"DP{_uid()}", status="published")
        sess = make_session(db, title=f"DP{_uid()}", event=ev)
        sess.speaker_id = sp.id
        p = Poll(session_id=sess.id, event_id=ev.id, question="?",
                 poll_type="yes_no", is_active=False, created_by=u.id)
        db.add(p); db.commit()
        r = client.post(f"/speaker/polls/{p.id}/delete",
                        data={"csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_profile_get(self, client, db):
        _login_speaker(client, db)
        assert client.get("/speaker/profile").status_code == 200

    def test_profile_update(self, client, db):
        _login_speaker(client, db)
        r = client.post("/speaker/profile",
                        data={"name": "Up", "title": "Dr.",
                              "bio": "B", "csrf_token": CSRF_TEST_TOKEN},
                        follow_redirects=False)
        assert r.status_code == 303

    def test_upload_image_no_file(self, client, db):
        _login_speaker(client, db)
        r = client.post("/speaker/upload-image",
                        data={"csrf_token": CSRF_TEST_TOKEN})
        assert r.status_code == 400


# ── Webhook routes ───────────────────────────────────────────────────


class TestWebhookRoutes:
    def test_missing_signature(self, client, db):
        r = client.post("/webhooks/razorpay",
                        json={"event": "refund.processed"})
        assert r.status_code != 500

    def test_bad_signature(self, client, db):
        r = client.post("/webhooks/razorpay",
                        json={"event": "refund.processed"},
                        headers={"X-Razorpay-Signature": "bad"})
        assert r.status_code != 500

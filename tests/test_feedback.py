"""Tests for the user feedback flow (form, submit, dismiss)."""

from datetime import datetime, timedelta

from tests.conftest import (
    admin_session,
    CSRF_TEST_TOKEN,
    make_feedback,
    make_session,
    make_showing,
    make_user,
)
from app.models.feedback import Feedback


def _login_user(client, db, **kw):
    user = make_user(db, **kw)
    db.commit()
    admin_session(client, user)
    return user


class TestFeedbackForm:
    """GET /feedback/{showing_id} -- renders the feedback form for logged-in users."""

    def test_feedback_form_unauthenticated(self, client, db):
        showing = make_showing(db)
        db.commit()
        resp = client.get(f"/feedback/{showing.id}", follow_redirects=False)
        assert resp.status_code == 303

    def test_feedback_form_authenticated(self, client, db):
        user = _login_user(client, db, username="fbuser", email="fbuser@test.com")
        session = make_session(db, title="Feedback Session")
        showing = make_showing(db, session=session)
        db.commit()

        resp = client.get(f"/feedback/{showing.id}")
        assert resp.status_code == 200
        assert b"Feedback Session" in resp.content


class TestFeedbackSubmit:
    """POST /feedback/{showing_id} -- submit rating + comment."""

    def test_submit_feedback(self, client, db):
        user = _login_user(client, db, username="submitter", email="sub@test.com")
        showing = make_showing(db)
        fb = Feedback(user_id=user.id, showing_id=showing.id)
        db.add(fb)
        db.commit()

        resp = client.post(
            f"/feedback/{showing.id}",
            data={
                "csrf_token": CSRF_TEST_TOKEN,
                "rating": "4",
                "comment": "Good session",
                "allow_public": "on",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (200, 303)


class TestFeedbackDismiss:
    """POST /feedback/{showing_id}/dismiss -- AJAX dismiss."""

    def test_dismiss_unauthenticated(self, client, db):
        resp = client.post("/feedback/1/dismiss")
        assert resp.status_code in (401, 403)

    def test_dismiss_authenticated(self, client, db):
        user = _login_user(client, db, username="dismisser", email="dismiss@test.com")
        showing = make_showing(db)
        fb = Feedback(user_id=user.id, showing_id=showing.id)
        db.add(fb)
        db.commit()

        resp = client.post(
            f"/feedback/{showing.id}/dismiss",
            data={"csrf_token": CSRF_TEST_TOKEN},
        )
        assert resp.status_code == 200

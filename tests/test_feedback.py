"""Tests for the user feedback flow (form, submit, dismiss)."""

from tests.conftest import (
    admin_session,
    CSRF_TEST_TOKEN,
    make_event,
    make_feedback,
    make_user,
)


def _login_user(client, db, **kw):
    user = make_user(db, **kw)
    db.commit()
    admin_session(client, user)
    return user


class TestFeedbackForm:
    """GET /feedback/{event_id} -- renders the feedback form for logged-in users."""

    def test_feedback_form_unauthenticated(self, client, db):
        event = make_event(db, name="Feedback Event")
        db.commit()
        resp = client.get(f"/feedback/{event.id}", follow_redirects=False)
        assert resp.status_code == 303

    def test_feedback_form_authenticated(self, client, db):
        user = _login_user(client, db, username="fbuser", email="fbuser@test.com")
        event = make_event(db, name="Feedback Event")
        db.commit()

        resp = client.get(f"/feedback/{event.id}")
        assert resp.status_code == 200
        assert b"Feedback Event" in resp.content


class TestFeedbackSubmit:
    """POST /feedback/{event_id} -- submit rating + comment."""

    def test_submit_feedback(self, client, db):
        from app.models.feedback import Feedback
        user = _login_user(client, db, username="submitter", email="sub@test.com")
        event = make_event(db, name="Submit Event")
        fb = Feedback(user_id=user.id, event_id=event.id)
        db.add(fb)
        db.commit()

        resp = client.post(
            f"/feedback/{event.id}",
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
    """POST /feedback/{event_id}/dismiss -- AJAX dismiss."""

    def test_dismiss_unauthenticated(self, client, db):
        resp = client.post("/feedback/1/dismiss")
        assert resp.status_code in (401, 403)

    def test_dismiss_authenticated(self, client, db):
        from app.models.feedback import Feedback
        user = _login_user(client, db, username="dismisser", email="dismiss@test.com")
        event = make_event(db, name="Dismiss Event")
        fb = Feedback(user_id=user.id, event_id=event.id)
        db.add(fb)
        db.commit()

        resp = client.post(
            f"/feedback/{event.id}/dismiss",
            data={"csrf_token": CSRF_TEST_TOKEN},
        )
        assert resp.status_code == 200

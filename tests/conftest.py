"""
Shared pytest fixtures for TechTrek integration tests.

Environment variables must be set BEFORE any app module is imported so that
``app.config.Settings`` validation passes and the database engine points at an
in-memory SQLite instance.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_techtrek.db")
os.environ.setdefault("SECRET_KEY", "a" * 64)

from cryptography.fernet import Fernet

_test_fernet_key = Fernet.generate_key().decode()
os.environ.setdefault("FIELD_ENCRYPTION_KEY", _test_fernet_key)

import pytest
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

from app.database import Base
from app.dependencies import get_db
from app.main import application

TEST_DB_URL = os.environ["DATABASE_URL"]
engine = create_engine(TEST_DB_URL, connect_args={} if "sqlite" not in TEST_DB_URL else {"check_same_thread": False})

if "sqlite" in TEST_DB_URL:
    @event.listens_for(engine, "connect")
    def _set_sqlite_fk_pragma(dbapi_conn, _rec):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

TestingSession = sessionmaker(bind=engine)


@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    try:
        if os.path.exists("test_techtrek.db"):
            os.remove("test_techtrek.db")
    except OSError:
        pass


@pytest.fixture()
def db():
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client(db):
    """FastAPI test client with DB dependency override."""
    def _override_get_db():
        try:
            yield db
        finally:
            pass

    application.dependency_overrides[get_db] = _override_get_db
    with TestClient(application, raise_server_exceptions=False) as c:
        yield c
    application.dependency_overrides.clear()


# ── Data factories ──────────────────────────────────────────────────────────

from app.models.auditorium import Auditorium
from app.models.booking import Booking
from app.models.college import College
from app.models.feedback import Feedback
from app.models.seat import Seat
from app.models.session import Session
from app.models.session_recording import SessionRecording
from app.models.showing import Showing
from app.models.speaker import Speaker
from app.models.testimonial import Testimonial
from app.models.user import User
from app.crypto import hash_lookup
from app.config import settings


def make_user(db, *, username="testuser", email="test@example.com",
              password_hash="fakehash", is_admin=False, **kw):
    enc_key = settings.field_encryption_key
    u = User(
        username=username,
        email=email,
        full_name=kw.pop("full_name", username),
        username_hash=hash_lookup(username, enc_key),
        email_hash=hash_lookup(email, enc_key),
        password_hash=password_hash,
        is_admin=is_admin,
        is_supervisor=kw.pop("is_supervisor", False),
        **kw,
    )
    db.add(u)
    db.flush()
    return u


def make_college(db, *, name="Test College", city_id=None):
    from app.models.city import City
    if city_id is None:
        city = City(name="Test City", state="Test State", is_active=True)
        db.add(city)
        db.flush()
        city_id = city.id
    c = College(name=name, city_id=city_id, is_active=True)
    db.add(c)
    db.flush()
    return c


def make_auditorium(db, *, name="Main Hall", college=None):
    if college is None:
        college = make_college(db)
    a = Auditorium(name=name, college_id=college.id, location="Building A")
    db.add(a)
    db.flush()
    return a


def make_session(db, *, title="Intro to AI", speaker_name="Dr. Smith"):
    s = Session(title=title, speaker_name=speaker_name, duration_minutes=30)
    db.add(s)
    db.flush()
    return s


def make_showing(db, *, session=None, auditorium=None, start_time=None,
                 price=0, status="published"):
    if session is None:
        session = make_session(db)
    if auditorium is None:
        auditorium = make_auditorium(db)
    if start_time is None:
        start_time = datetime.now() + timedelta(days=7)
    sh = Showing(
        session_id=session.id,
        auditorium_id=auditorium.id,
        start_time=start_time,
        price=Decimal(str(price)),
        status=status,
    )
    db.add(sh)
    db.flush()
    return sh


def make_testimonial(db, *, quote="Great event!", student_name="Test Student"):
    t = Testimonial(quote=quote, student_name=student_name, is_active=True)
    db.add(t)
    db.flush()
    return t


def make_feedback(db, *, user=None, showing=None, rating=5, comment="Excellent",
                  allow_public=False, is_featured=False):
    if user is None:
        user = make_user(db)
    if showing is None:
        showing = make_showing(db)
    fb = Feedback(
        user_id=user.id,
        showing_id=showing.id,
        rating=rating,
        comment=comment,
        allow_public=allow_public,
        is_featured=is_featured,
    )
    db.add(fb)
    db.flush()
    return fb



def make_speaker(db, *, name="Dr. Test Speaker", user=None, **kw):
    s = Speaker(
        name=name,
        user_id=user.id if user else None,
        **kw,
    )
    db.add(s)
    db.flush()
    return s


def make_recording(db, *, session=None, url="https://youtube.com/watch?v=test",
                   title="Test Recording", is_public=True, order=0):
    if session is None:
        session = make_session(db)
    r = SessionRecording(
        session_id=session.id,
        url=url,
        title=title,
        is_public=is_public,
        order=order,
    )
    db.add(r)
    db.flush()
    return r


CSRF_TEST_TOKEN = "test_csrf_token_for_testing_only"


def admin_session(client, user):
    """Inject user_id + csrf_token into the Starlette session cookie."""
    import base64
    import json
    from itsdangerous import TimestampSigner
    data = base64.b64encode(json.dumps({
        "user_id": user.id,
        "csrf_token": CSRF_TEST_TOKEN,
    }).encode()).decode()
    signer = TimestampSigner(settings.secret_key)
    cookie_value = signer.sign(data).decode()
    client.cookies.set("session", cookie_value)
    return client

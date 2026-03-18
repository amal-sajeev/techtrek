"""Seed script – populates the database with comprehensive demo data.

Usage:
    python seed.py                     # seed (skip if data exists)
    python seed.py --force             # clear everything and re-seed
    python seed.py --port 9000         # use a running service on port 9000
    python seed.py --base-url http://example.com  # custom base URL

If the service is not reachable at the given URL the script will start
uvicorn automatically and shut it down when seeding is done.
"""

import argparse
import re
import subprocess
import sys
import time
import warnings
import bcrypt
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import text

from app.database import SessionLocal, Base, engine
from app.models.user import User
from app.models.city import City
from app.models.college import College
from app.models.auditorium import Auditorium
from app.models.seat import Seat
from app.models.seat_type import SeatType
from app.models.speaker import Speaker
from app.models.session import Session as SessionModel
from app.models.session_speaker import SessionSpeaker
from app.models.session_recording import SessionRecording
from app.models.agenda import AgendaItem
from app.models.booking import Booking
from app.models.waitlist import Waitlist
from app.models.feedback import Feedback
from app.models.testimonial import Testimonial, NewsletterSubscriber
from app.models.activity_log import ActivityLog
from app.models.webhook_log import WebhookLog
from app.models.site_setting import SiteSetting
from app.models.event import Event
from app.models.event_break import EventBreak
from app.models.event_addon import EventAddOn
from app.models.coupon import Coupon
from app.models.feedback_template import FeedbackTemplate, TemplateQuestion
from app.crypto import hash_lookup
from app.config import settings


# ═══════════════════════════════════════════════════════════════════════
#  CLI & Service lifecycle
# ═══════════════════════════════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser(description="Seed the TechTrek database with comprehensive demo data.")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--base-url", type=str, default=None)
    p.add_argument("--force", "-f", action="store_true")
    return p.parse_args()


def ensure_service(base_url: str, port: int):
    """Return a subprocess handle if we had to start the server, else None."""
    try:
        httpx.get(base_url, timeout=3, follow_redirects=True)
        print(f"  Service already running at {base_url}")
        return None
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
        pass

    print(f"  Service not running -- launching uvicorn on port {port} ...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        time.sleep(1)
        try:
            httpx.get(base_url, timeout=2, follow_redirects=True)
            print(f"  Service started (pid {proc.pid})")
            return proc
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
            pass
    proc.terminate()
    sys.exit("ERROR: service did not become healthy within 30 s")


# ═══════════════════════════════════════════════════════════════════════
#  HTTP helper
# ═══════════════════════════════════════════════════════════════════════

class ApiClient:
    """Thin wrapper around httpx.Client that handles cookies + CSRF."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            base_url=self.base_url,
            follow_redirects=True,
            timeout=30,
        )
        self._csrf: str | None = None

    def _scrape_csrf(self, html: str):
        m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        if m:
            self._csrf = m.group(1)

    def login(self, username: str, password: str, retries: int = 3):
        for attempt in range(retries):
            try:
                r = self.client.get("/auth/login")
                self._scrape_csrf(r.text)
                r = self.client.post("/auth/login", data={
                    "username": username,
                    "password": password,
                    "csrf_token": self._csrf or "",
                })
                return r
            except (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError):
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)

    def logout(self, retries: int = 3):
        for attempt in range(retries):
            try:
                self.client.get("/auth/logout")
                self._csrf = None
                return
            except (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError):
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)

    def get(self, path: str, retries: int = 3):
        for attempt in range(retries):
            try:
                r = self.client.get(path)
                self._scrape_csrf(r.text)
                return r
            except (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError):
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)

    def post_form(self, path: str, data: dict, retries: int = 3):
        if not self._csrf:
            self.get("/")
        data["csrf_token"] = self._csrf or ""
        for attempt in range(retries):
            try:
                return self.client.post(path, data=data)
            except (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError):
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)
                self._csrf = None
                try:
                    self.get("/")
                except Exception:
                    time.sleep(2)
                    self.get("/")

    def close(self):
        self.client.close()


# ═══════════════════════════════════════════════════════════════════════
#  Phase 1 – Direct DB seeding
# ═══════════════════════════════════════════════════════════════════════

def _pw(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _make_user(**kwargs) -> User:
    """Create a User with email_hash and username_hash auto-populated."""
    key = settings.field_encryption_key
    u = User(**kwargs)
    u.email_hash = hash_lookup(kwargs["email"], key)
    u.username_hash = hash_lookup(kwargs["username"], key)
    return u


def phase1_db_seed(force: bool):
    """Create foundational entities directly in the database."""
    import logging
    for name in ("alembic", "alembic.runtime.migration"):
        logging.getLogger(name).setLevel(logging.ERROR)
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command as alembic_cmd
        acfg = AlembicConfig("alembic.ini")
        acfg.attributes["configure_logger"] = False
        alembic_cmd.upgrade(acfg, "head")
    except Exception:
        Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    if db.query(User).count() > 0 and not force:
        print("  Database already seeded -- skipping.  (Use --force to re-seed.)")
        db.close()
        return None

    if force and db.query(User).count() > 0:
        print("  --force: dropping and recreating all tables ...")
        db.close()
        with engine.connect() as conn:
            for tbl in ("event_showings", "showings"):
                try:
                    conn.execute(text(f"DROP TABLE IF EXISTS {tbl} CASCADE"))
                    conn.commit()
                except Exception:
                    conn.rollback()
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        print("  Cleared.")

    # ── Users ──────────────────────────────────────────────────────────
    admin = _make_user(username="admin", email="admin@techtrek.dev",
                       password_hash=_pw("admin123"), full_name="Admin User",
                       is_admin=True)
    supervisor = _make_user(username="supervisor", email="supervisor@techtrek.dev",
                            password_hash=_pw("supervisor123"),
                            full_name="Vijay Supervisor", is_supervisor=True)
    alice = _make_user(username="alice", email="alice@example.com",
                       password_hash=_pw("user123"), full_name="Alice Verma",
                       college="KSR College of Engineering", discipline="CSE",
                       domain="AI", year_of_study=3)
    bob = _make_user(username="bob", email="bob@example.com",
                     password_hash=_pw("user123"), full_name="Bob Sharma",
                     college="Delhi Technological University", discipline="IT",
                     domain="Cloud Computing", year_of_study=2)
    charlie = _make_user(username="charlie", email="charlie@example.com",
                         password_hash=_pw("user123"), full_name="Charlie Patel",
                         college="BITS Pilani", discipline="ECE",
                         domain="IoT", year_of_study=4)
    diana = _make_user(username="diana", email="diana@example.com",
                       password_hash=_pw("user123"), full_name="Diana Krishnan",
                       college="IIIT Bangalore", discipline="CSE",
                       domain="Full-Stack", year_of_study=3)
    speaker_sarah = _make_user(username="sarah", email="sarah@deepmind.example.com",
                               password_hash=_pw("speaker123"),
                               full_name="Dr. Sarah Chen")
    speaker_james = _make_user(username="james", email="james@fastly.example.com",
                               password_hash=_pw("speaker123"),
                               full_name="James Kowalski")
    speaker_maria = _make_user(username="maria", email="maria@rust.example.com",
                               password_hash=_pw("speaker123"),
                               full_name="Maria Gonzalez")
    speaker_amal = _make_user(username="amalsajeev", email="amsajeev333@gmail.com",
                              password_hash=_pw("speaker123"),
                              full_name="Amal Sajeev")
    all_users = [admin, supervisor, alice, bob, charlie, diana,
                 speaker_sarah, speaker_james, speaker_maria, speaker_amal]
    db.add_all(all_users)
    db.commit()
    for u in all_users:
        db.refresh(u)
    print(f"  Created {len(all_users)} users")

    # ── Cities ─────────────────────────────────────────────────────────
    cities = [
        City(name="Chennai", state="Tamil Nadu"),
        City(name="Delhi", state="Delhi"),
        City(name="Bangalore", state="Karnataka"),
        City(name="Mumbai", state="Maharashtra"),
        City(name="Pune", state="Maharashtra"),
    ]
    db.add_all(cities)
    db.commit()
    for c in cities:
        db.refresh(c)
    print(f"  Created {len(cities)} cities")

    # ── Colleges ───────────────────────────────────────────────────────
    colleges = [
        College(name="KSR College of Engineering", city_id=cities[0].id,
                address="KSR Kalvi Nagar, Tiruchengode"),
        College(name="Anna University", city_id=cities[0].id,
                address="Guindy, Chennai"),
        College(name="Delhi Technological University", city_id=cities[1].id,
                address="Shahbad Daulatpur, Delhi"),
        College(name="IIT Delhi", city_id=cities[1].id,
                address="Hauz Khas, New Delhi"),
        College(name="IIIT Bangalore", city_id=cities[2].id,
                address="26th Main Rd, Bangalore"),
        College(name="BITS Pilani – Goa Campus", city_id=cities[3].id,
                address="Zuarinagar, Goa"),
    ]
    db.add_all(colleges)
    db.commit()
    for c in colleges:
        db.refresh(c)
    print(f"  Created {len(colleges)} colleges")

    supervisor.supervisor_college_id = colleges[0].id
    db.commit()

    # ── Seat types ─────────────────────────────────────────────────────
    seat_types = [
        SeatType(name="Premium", colour="#f59e0b", icon="star",
                 price=800, is_custom=True),
        SeatType(name="Balcony", colour="#8b5cf6", icon="building",
                 price=600, is_custom=True),
    ]
    db.add_all(seat_types)
    db.commit()
    for st in seat_types:
        db.refresh(st)
    print(f"  Created {len(seat_types)} custom seat types")

    # ── Speakers ───────────────────────────────────────────────────────
    speakers = [
        Speaker(name="Dr. Sarah Chen", title="VP of AI Research, DeepMind",
                bio="Leading researcher in autonomous agents and reinforcement learning with 15+ years of experience.",
                email="sarah@deepmind.example.com",
                photo_url="https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=200&h=200&fit=crop",
                user_id=speaker_sarah.id),
        Speaker(name="James Kowalski", title="Staff Engineer, Fastly",
                bio="WebAssembly pioneer and edge computing evangelist. Co-author of the WASI spec.",
                email="james@fastly.example.com",
                user_id=speaker_james.id),
        Speaker(name="Maria Gonzalez", title="Rust Core Team Member",
                bio="Systems programming expert and Rust educator. Author of 'Rust in Action'.",
                email="maria@rust.example.com",
                user_id=speaker_maria.id),
        Speaker(name="Alex Petrov", title="Principal DB Engineer, Neon",
                bio="PostgreSQL internals expert. Speaker at PGConf and author of 'Database Internals'.",
                email="alex@neon.example.com"),
        Speaker(name="Priya Sharma", title="Accessibility Lead, Google",
                bio="WCAG expert and inclusive design advocate. Built Google's accessibility testing framework.",
                email="priya@google.example.com"),
        Speaker(name="Michael Torres", title="CISO, CrowdStrike",
                bio="Cybersecurity veteran with experience in zero-trust architecture and threat detection.",
                email="michael@crowdstrike.example.com"),
        Speaker(name="Anika Desai", title="CTO, Razorpay",
                bio="Fintech leader scaling payment infrastructure for millions of businesses across India."),
        Speaker(name="Rahul Mehta", title="ML Lead, Microsoft Research",
                bio="Quantum computing researcher working on practical quantum ML applications."),
        Speaker(name="Amal Sajeev",
                title="Principal Engineer & Tech Speaker",
                bio="Full-stack architect and developer advocate with 12+ years building scalable systems.",
                email="amsajeev333@gmail.com",
                user_id=speaker_amal.id),
    ]
    db.add_all(speakers)
    db.commit()
    for s in speakers:
        db.refresh(s)
    print(f"  Created {len(speakers)} speakers")

    # ── Auditoriums & seats ────────────────────────────────────────────
    auditoriums = [
        Auditorium(
            name="Main Hall", college_id=colleges[0].id,
            location="KSR College, Tiruchengode",
            description="Flagship 150-seat auditorium with state-of-the-art AV.",
            total_rows=10, total_cols=15,
            stage_cols=10, stage_offset=2, stage_label="Main Stage",
        ),
        Auditorium(
            name="Innovation Lab", college_id=colleges[2].id,
            location="DTU Campus, Delhi",
            description="Intimate 60-seat space for hands-on workshops.",
            total_rows=6, total_cols=10,
        ),
        Auditorium(
            name="Seminar Hall A", college_id=colleges[4].id,
            location="IIIT Bangalore Campus",
            description="Modern 80-seat seminar hall with tiered seating.",
            total_rows=8, total_cols=10,
        ),
        Auditorium(
            name="Lecture Theatre B", college_id=colleges[1].id,
            location="Anna University, Chennai",
            description="Classic 100-seat lecture theatre.",
            total_rows=10, total_cols=10,
        ),
        Auditorium(
            name="Micro Hall", college_id=colleges[0].id,
            location="KSR College, Tiruchengode",
            description="Tiny 9-seat room for demos (useful for sold-out testing).",
            total_rows=3, total_cols=3,
        ),
    ]
    db.add_all(auditoriums)
    db.commit()
    for a in auditoriums:
        db.refresh(a)

    _create_seats(db, auditoriums, seat_types)
    print(f"  Created {len(auditoriums)} auditoriums with seats")

    # ── Testimonials ───────────────────────────────────────────────────
    testimonials = [
        Testimonial(student_name="Priya Sharma", college="KSR College of Engineering",
                    quote="TechTrek opened my eyes to quantum computing. The speaker was phenomenal and the venue was buzzing with energy!"),
        Testimonial(student_name="Arjun Mehta", college="Delhi Technological University",
                    quote="The best industry event I've attended as a student. Clear, concise talks that actually help you understand where the industry is heading."),
        Testimonial(student_name="Sneha Patel", college="BITS Pilani",
                    quote="From booking my seat to attending — the whole experience was seamless. Can't wait for the next TechTrek!"),
        Testimonial(student_name="Vikram Singh", college="IIT Delhi",
                    quote="The AI Agents session blew my mind. Real practical insights from someone who builds these systems daily."),
        Testimonial(student_name="Ananya Rao", college="IIIT Bangalore",
                    quote="Finally an event that treats students like professionals. The networking opportunities alone were worth it."),
        Testimonial(student_name="Karthik Nair", college="Anna University",
                    quote="Loved the Rust workshop – Maria explained ownership in 20 minutes better than any YouTube video."),
    ]
    db.add_all(testimonials)
    db.commit()
    print(f"  Created {len(testimonials)} testimonials")

    # ── Newsletter subscribers ─────────────────────────────────────────
    subs = [
        NewsletterSubscriber(email="student1@example.com"),
        NewsletterSubscriber(email="student2@example.com"),
        NewsletterSubscriber(email="techfan@example.com"),
        NewsletterSubscriber(email="curious@example.com"),
    ]
    db.add_all(subs)
    db.commit()
    print(f"  Created {len(subs)} newsletter subscribers")

    # ── Site settings ──────────────────────────────────────────────────
    site_settings = [
        SiteSetting(key="hero_title", value="TechTrek 2026"),
        SiteSetting(key="hero_subtitle", value="India's Premier Student Tech Conference"),
        SiteSetting(key="contact_email", value="hello@techtrek.dev"),
    ]
    db.add_all(site_settings)
    db.commit()
    print(f"  Created {len(site_settings)} site settings")

    # ── Feedback template ────────────────────────────────────────────
    fb_template = FeedbackTemplate(
        name="Workshop Feedback",
        description="Post-workshop feedback form with session-specific and overall questions.",
        created_by=admin.id,
    )
    db.add(fb_template)
    db.flush()
    template_questions = [
        TemplateQuestion(
            template_id=fb_template.id, order=0,
            question_text="Which session was the most valuable to you and why?",
            question_type="text", is_required=True,
        ),
        TemplateQuestion(
            template_id=fb_template.id, order=1,
            question_text="How would you rate the hands-on exercises?",
            question_type="rating_scale", is_required=True,
        ),
        TemplateQuestion(
            template_id=fb_template.id, order=2,
            question_text="What is your experience level with cloud-native technologies?",
            question_type="multiple_choice", is_required=False,
            options_json=["Complete beginner", "Some exposure", "Intermediate", "Advanced"],
        ),
        TemplateQuestion(
            template_id=fb_template.id, order=3,
            question_text="What topics would you like covered in a future workshop?",
            question_type="text", is_required=False,
        ),
    ]
    db.add_all(template_questions)
    db.commit()
    print(f"  Created feedback template '{fb_template.name}' with {len(template_questions)} questions")

    refs = {
        "speakers": [{"id": s.id, "name": s.name} for s in speakers],
        "auditoriums": [{"id": a.id, "name": a.name, "college_id": a.college_id}
                        for a in auditoriums],
        "colleges": [{"id": c.id, "name": c.name} for c in colleges],
        "feedback_template_id": fb_template.id,
    }
    db.close()
    return refs


def _create_seats(db, auditoriums, seat_types):
    """Generate seat grids for every auditorium."""
    aud_main, aud_lab, aud_seminar, aud_lecture, aud_micro = auditoriums

    for r in range(1, 11):
        for c in range(1, 16):
            if c == 8:
                stype, label, active = "aisle", "", False
            else:
                stype, label, active = "standard", f"{chr(64+r)}{c}", True
            db.add(Seat(auditorium_id=aud_main.id, row_num=r, col_num=c,
                        label=label, seat_type=stype, is_active=active))

    for r in range(1, 7):
        for c in range(1, 11):
            if c == 5:
                stype, label, active = "aisle", "", False
            else:
                stype, label, active = "standard", f"{chr(64+r)}{c}", True
            db.add(Seat(auditorium_id=aud_lab.id, row_num=r, col_num=c,
                        label=label, seat_type=stype, is_active=active))

    for r in range(1, 9):
        for c in range(1, 11):
            db.add(Seat(auditorium_id=aud_seminar.id, row_num=r, col_num=c,
                        label=f"{chr(64+r)}{c}", seat_type="standard",
                        is_active=True))

    for r in range(1, 11):
        for c in range(1, 11):
            db.add(Seat(auditorium_id=aud_lecture.id, row_num=r, col_num=c,
                        label=f"{chr(64+r)}{c}", seat_type="standard",
                        is_active=True))

    for r in range(1, 4):
        for c in range(1, 4):
            db.add(Seat(auditorium_id=aud_micro.id, row_num=r, col_num=c,
                        label=f"{chr(64+r)}{c}", seat_type="standard",
                        is_active=True))

    db.commit()


# ═══════════════════════════════════════════════════════════════════════
#  Phase 2a – Event data definitions
# ═══════════════════════════════════════════════════════════════════════

def build_event_data(speakers, auditoriums, colleges):
    """Return a list of event dicts with sessions, breaks, and coupons.

    Single event: TechTrek AI & Future Tech Summit 2026 at KSR College.
    Data sourced from the official session spreadsheet.
    Speakers 0=Sarah 1=James 2=Maria 3=Alex 4=Priya 5=Michael 6=Anika 7=Rahul 8=Amal
    """

    yesterday = -1

    return [
        # ── Past completed event (for feedback / certificate demo) ──
        {
            "name": "TechTrek Cloud-Native Engineering Workshop 2026",
            "description": (
                "An intensive hands-on workshop covering cloud-native architecture, "
                "containerisation with Docker and Kubernetes, CI/CD pipelines, and "
                "observability. Attendees built and deployed a microservice from "
                "scratch and left with a production-grade starter template."
            ),
            "banner_url": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1200&h=400&fit=crop",
            "college_idx": 1,   # Anna University
            "aud_idx": 3,       # Lecture Theatre B
            "start_offset_days": yesterday,
            "end_offset_days": yesterday,
            "price": 0,
            "price_vip": None,
            "price_accessible": None,
            "processing_fee_pct": None,
            "status": "published",  # changed to completed after amalsajeev books in phase3
            "link_feedback_template": True,
            "cert": {
                "cert_title": "Certificate of Completion",
                "cert_subtitle": "TechTrek Cloud-Native Engineering Workshop 2026",
                "cert_footer": "Issued by TechTrek Pvt Ltd & Anna University",
                "cert_signer_name": "James Kowalski",
                "cert_signer_designation": "Staff Engineer, Fastly",
                "cert_color_scheme": "blue",
            },
            "sessions": [
                {
                    "title": "Containers from First Principles",
                    "speaker_id": speakers[1]["id"],
                    "speaker_name": "James Kowalski",
                    "description": (
                        "What happens when you type docker run? This session peels "
                        "back namespaces, cgroups, and overlay filesystems to show "
                        "exactly how containers work under the hood — then builds "
                        "one from scratch using only shell commands."
                    ),
                    "banner_url": "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=1200&h=400&fit=crop",
                    "duration_minutes": 40,
                    "start_offset_hours": 10,
                    "order": 0,
                    "agenda": [
                        {"title": "Linux Namespaces & Cgroups", "speaker_idx": 1, "dur": 15,
                         "desc": "The kernel primitives that make containers possible."},
                        {"title": "Building a Container by Hand", "speaker_idx": 1, "dur": 15,
                         "desc": "Using unshare, chroot, and pivot_root to build a container from scratch."},
                        {"title": "Docker Architecture Walkthrough", "speaker_idx": 1, "dur": 10,
                         "desc": "From Dockerfile to running container — every layer explained."},
                    ],
                    "session_speakers": [{"speaker_idx": 1, "role": "Workshop Lead"}],
                    "recordings": [],
                },
                {
                    "title": "Kubernetes in Production: Patterns That Scale",
                    "speaker_id": speakers[3]["id"],
                    "speaker_name": "Alex Petrov",
                    "description": (
                        "Moving beyond kubectl apply. This session covers production "
                        "patterns: health probes, resource budgets, HPA, network "
                        "policies, and secrets management — with live demos on a "
                        "real cluster."
                    ),
                    "banner_url": "https://images.unsplash.com/photo-1504639725590-34d0984388bd?w=1200&h=400&fit=crop",
                    "duration_minutes": 40,
                    "start_offset_hours": 11,
                    "order": 1,
                    "agenda": [
                        {"title": "Health Probes & Resource Budgets", "speaker_idx": 3, "dur": 15,
                         "desc": "Liveness, readiness, startup probes and how they prevent outages."},
                        {"title": "Autoscaling & Network Policies", "speaker_idx": 3, "dur": 15,
                         "desc": "HPA, VPA, and zero-trust networking inside a cluster."},
                        {"title": "Secrets & Config Management", "speaker_idx": 3, "dur": 10,
                         "desc": "External Secrets Operator, sealed secrets, and config reload patterns."},
                    ],
                    "session_speakers": [{"speaker_idx": 3, "role": "Workshop Lead"}],
                    "recordings": [],
                },
                {
                    "title": "Observability: Logs, Metrics, and Traces",
                    "speaker_id": speakers[8]["id"],
                    "speaker_name": "Amal Sajeev",
                    "description": (
                        "You can't fix what you can't see. This session introduces "
                        "the three pillars of observability — structured logging with "
                        "Loki, metrics with Prometheus/Grafana, and distributed tracing "
                        "with OpenTelemetry — wired into the microservice built earlier."
                    ),
                    "banner_url": "https://images.unsplash.com/photo-1555949963-ff9fe0c870eb?w=1200&h=400&fit=crop",
                    "duration_minutes": 40,
                    "start_offset_hours": 12.25,
                    "order": 3,
                    "agenda": [
                        {"title": "Structured Logging with Loki", "speaker_idx": 8, "dur": 12,
                         "desc": "Moving beyond print statements to queryable, structured logs."},
                        {"title": "Metrics & Dashboards with Prometheus", "speaker_idx": 8, "dur": 14,
                         "desc": "RED metrics, custom counters, and building a Grafana dashboard."},
                        {"title": "Distributed Tracing with OpenTelemetry", "speaker_idx": 8, "dur": 14,
                         "desc": "Propagating trace context across services to debug latency."},
                    ],
                    "session_speakers": [{"speaker_idx": 8, "role": "Workshop Lead"}],
                    "recordings": [],
                },
            ],
            "breaks": [
                {
                    "title": "Networking Break",
                    "description": "Grab a coffee, swap GitHub handles, and discuss the morning sessions.",
                    "duration_minutes": 30,
                    "start_offset_hours": 11.75,
                    "order": 2,
                },
            ],
            "addons": [],
            "coupons": [],
        },
        # ── Future event (main event) ──
        {
            "name": "TechTrek AI & Future Tech Summit 2026",
            "description": (
                "A full-day summit exploring AI\u2019s impact on careers, technology, and society. "
                "From designing human-centric AI futures to quantum computing breakthroughs, "
                "this event equips students with the knowledge and action plans to thrive in "
                "an AI-accelerated world."
            ),
            "banner_url": "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?w=1200&h=400&fit=crop",
            "college_idx": 0,
            "aud_idx": 0,
            "start_offset_days": 10,
            "end_offset_days": 10,
            "price": 500,
            "price_vip": None,
            "price_accessible": None,
            "processing_fee_pct": 2.5,
            "status": "published",
            "cert": {
                "cert_title": "Certificate of Attendance",
                "cert_subtitle": "TechTrek AI & Future Tech Summit 2026",
                "cert_footer": "Issued by TechTrek Pvt Ltd",
                "cert_signer_name": "Dr. Sarah Chen",
                "cert_signer_designation": "VP of AI Research, DeepMind",
                "cert_color_scheme": "purple",
            },
            "sessions": [
                {
                    "title": "Designing a Human-Centric AI Future",
                    "speaker_id": speakers[0]["id"],
                    "speaker_name": "Dr. Sarah Chen",
                    "description": (
                        "AI doesn\u2019t arrive in a vacuum\u2014it lands inside geopolitics, regulation, "
                        "culture, and power. Using the \u2018Good Future\u2019 lens, this talk explores how "
                        "nations (especially India, as referenced) can shape AI toward human-centered "
                        "outcomes: trust, democracy, sustainability, and shared prosperity instead of "
                        "surveillance, manipulation, or inequality."
                    ),
                    "banner_url": "https://images.unsplash.com/photo-1677442136019-21780ecad995?w=1200&h=400&fit=crop",
                    "duration_minutes": 30,
                    "start_offset_hours": 10,
                    "order": 0,
                    "agenda": [
                        {"title": "Geopolitics & AI Policy", "speaker_idx": 0, "dur": 10,
                         "desc": "How geopolitics and policy influence AI development and deployment."},
                        {"title": "Good Future vs Bad Future Pathways", "speaker_idx": 0, "dur": 10,
                         "desc": "Differentiating outcomes using concrete examples from governance, ethics, and security."},
                        {"title": "Framing Career Choices Around Impact", "speaker_idx": 0, "dur": 10,
                         "desc": "What you build, who it benefits, and what it risks."},
                    ],
                    "session_speakers": [{"speaker_idx": 0, "role": "Keynote"}],
                    "recordings": [],
                },
                {
                    "title": "The Invisible Wave of Technological Change",
                    "speaker_id": speakers[5]["id"],
                    "speaker_name": "Michael Torres",
                    "description": (
                        "\u2018AI Tsunami\u2019 is a blunt metaphor for scale and speed: capabilities arrive "
                        "faster than institutions can adapt. This session unpacks near\u2011term AI progress, "
                        "societal readiness gaps, and why safety, alignment, and governance become "
                        "engineering problems\u2014not just philosophy."
                    ),
                    "banner_url": "https://images.unsplash.com/photo-1563013544-824ae1b704d3?w=1200&h=400&fit=crop",
                    "duration_minutes": 30,
                    "start_offset_hours": 10.75,
                    "order": 1,
                    "agenda": [
                        {"title": "The AI Tsunami Argument", "speaker_idx": 5, "dur": 10,
                         "desc": "Summarizing the readiness challenges as capabilities outpace institutions."},
                        {"title": "Safety Concepts for Students", "speaker_idx": 5, "dur": 10,
                         "desc": "Evaluation, red-teaming, and guardrails in practical terms."},
                        {"title": "Personal Action Planning", "speaker_idx": 5, "dur": 10,
                         "desc": "Skills to learn, communities to join, and questions to research."},
                    ],
                    "session_speakers": [{"speaker_idx": 5, "role": "Keynote"}],
                    "recordings": [],
                },
                {
                    "title": "How Computers Are Redefining Work",
                    "speaker_id": speakers[1]["id"],
                    "speaker_name": "James Kowalski",
                    "description": (
                        "Perplexity\u2019s \u2018Computer\u2019 idea points to a shift from chatbots to agents that "
                        "can operate a full digital workspace\u2014browsing, clicking, filling forms, and "
                        "completing tasks end-to-end. This session looks at how \u2018AI that uses a computer\u2019 "
                        "changes productivity, entry-level work, and the skills students need to stay "
                        "valuable when routine screen-work is automated."
                    ),
                    "banner_url": "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=1200&h=400&fit=crop",
                    "duration_minutes": 30,
                    "start_offset_hours": 11.5,
                    "order": 2,
                    "agenda": [
                        {"title": "AI Agents vs Chatbots", "speaker_idx": 1, "dur": 10,
                         "desc": "What an AI computer/agent is and how it differs from a normal chatbot."},
                        {"title": "Tasks Most Likely to Be Automated", "speaker_idx": 1, "dur": 10,
                         "desc": "Identifying office-style workflows ripe for automation."},
                        {"title": "Human Advantage & Portfolio Planning", "speaker_idx": 1, "dur": 10,
                         "desc": "Judgment, problem framing, and showcasing collaboration with AI tools."},
                    ],
                    "session_speakers": [{"speaker_idx": 1, "role": "Keynote"}],
                    "recordings": [],
                },
                {
                    "title": "The World Students Will Graduate Into",
                    "speaker_id": speakers[6]["id"],
                    "speaker_name": "Anika Desai",
                    "description": (
                        "The late-2020s as a \u2018reset\u2019 period where AI reshapes how value is created. "
                        "This talk argues that relying only on paid labor is risky, and emphasizes "
                        "building durable skills, networks, and ownership\u2014from projects and products "
                        "to audiences and equity-like assets\u2014so students can thrive in an "
                        "AI-accelerated economy."
                    ),
                    "banner_url": "https://images.unsplash.com/photo-1556742049-0cfed4f6a45d?w=1200&h=400&fit=crop",
                    "duration_minutes": 30,
                    "start_offset_hours": 12.25,
                    "order": 3,
                    "agenda": [
                        {"title": "Labor vs Ownership Income", "speaker_idx": 6, "dur": 10,
                         "desc": "The difference between income-from-labor and income-from-ownership."},
                        {"title": "Durable Assets for Students", "speaker_idx": 6, "dur": 10,
                         "desc": "Portfolio, audience, product, or niche skill stack\u2014choosing one to build."},
                        {"title": "90-Day Builder Plan", "speaker_idx": 6, "dur": 10,
                         "desc": "Moving from consumer of AI to builder with AI: projects, distribution, community."},
                    ],
                    "session_speakers": [{"speaker_idx": 6, "role": "Keynote"}],
                    "recordings": [],
                },
                # Session order 4 is the Lunch Break – handled as EventBreak below
                {
                    "title": "Building AI Projects That Employers Notice",
                    "speaker_id": speakers[2]["id"],
                    "speaker_name": "Maria Gonzalez",
                    "description": (
                        "Hiring signals have changed: recruiters want proof you can build, ship, "
                        "and explain. This talk breaks down portfolio-ready project ideas that "
                        "demonstrate data handling, modeling, evaluation, and real-world deployment "
                        "thinking\u2014not just notebooks."
                    ),
                    "banner_url": "https://images.unsplash.com/photo-1504639725590-34d0984388bd?w=1200&h=400&fit=crop",
                    "duration_minutes": 30,
                    "start_offset_hours": 13.75,
                    "order": 5,
                    "agenda": [
                        {"title": "Project Archetypes That Land Jobs", "speaker_idx": 2, "dur": 10,
                         "desc": "Five project types employers recognize as job-relevant."},
                        {"title": "Defining \u2018Done\u2019 for AI Projects", "speaker_idx": 2, "dur": 10,
                         "desc": "Problem, data, metrics, demo, documentation, and evaluation mindset."},
                        {"title": "Portfolio Checklist for Recruiters", "speaker_idx": 2, "dur": 10,
                         "desc": "A GitHub/portfolio checklist that communicates impact clearly."},
                    ],
                    "session_speakers": [{"speaker_idx": 2, "role": "Keynote"}],
                    "recordings": [],
                },
                {
                    "title": "Will AI Take Over Jobs\u2014or Transform Them?",
                    "speaker_id": speakers[4]["id"],
                    "speaker_name": "Priya Sharma",
                    "description": (
                        "This session examines bold claims about AI replacing millions of jobs. "
                        "Students learn how to interrogate such statements: what counts as a \u2018job\u2019, "
                        "what tasks get automated first, and how industries redesign roles rather "
                        "than simply deleting them."
                    ),
                    "banner_url": "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?w=1200&h=400&fit=crop",
                    "duration_minutes": 30,
                    "start_offset_hours": 14.5,
                    "order": 6,
                    "agenda": [
                        {"title": "Job Replacement vs Task Automation", "speaker_idx": 4, "dur": 10,
                         "desc": "Distinguishing the two with real-world examples."},
                        {"title": "Interrogating AI Headlines", "speaker_idx": 4, "dur": 10,
                         "desc": "Evidence questions: who said it, context, assumptions, and timeframe."},
                        {"title": "Personal Automation Audit", "speaker_idx": 4, "dur": 10,
                         "desc": "Career strategies: adaptability, domain depth, tool fluency, and skill upgrades."},
                    ],
                    "session_speakers": [{"speaker_idx": 4, "role": "Keynote"}],
                    "recordings": [],
                },
                {
                    "title": "AI is Outdated: Quantum + AI is the Next Big Leap",
                    "speaker_id": speakers[7]["id"],
                    "speaker_name": "Rahul Mehta",
                    "description": (
                        "This talk positions quantum computing as a new layer that could amplify "
                        "AI\u2014especially for optimization, simulation, and complex search. Without "
                        "requiring heavy physics, it introduces why quantum matters, where hype exists, "
                        "and how students can build a credible learning path from linear algebra basics "
                        "to quantum algorithms and AI applications."
                    ),
                    "banner_url": "https://images.unsplash.com/photo-1635070041078-e363dbe005cb?w=1200&h=400&fit=crop",
                    "duration_minutes": 30,
                    "start_offset_hours": 15.25,
                    "order": 7,
                    "agenda": [
                        {"title": "Quantum Computing Demystified", "speaker_idx": 7, "dur": 10,
                         "desc": "What quantum computing is and is not\u2014in plain language."},
                        {"title": "Where Quantum Meets AI", "speaker_idx": 7, "dur": 10,
                         "desc": "AI problem types that may benefit: optimization, simulation, and practical constraints."},
                        {"title": "Starter Roadmap for Students", "speaker_idx": 7, "dur": 10,
                         "desc": "Prerequisites, tools (simulators), and mini-experiments to get started."},
                    ],
                    "session_speakers": [{"speaker_idx": 7, "role": "Keynote"}],
                    "recordings": [],
                },
                {
                    "title": "Lessons from Failed GenAI Experiments",
                    "speaker_id": speakers[3]["id"],
                    "speaker_name": "Alex Petrov",
                    "description": (
                        "Most GenAI prototypes die before production because the hard parts start "
                        "after the demo: data quality, evaluation, security, cost, reliability, and "
                        "governance. This session turns failure modes into a practical playbook "
                        "students can apply to projects, hackathons, and internships."
                    ),
                    "banner_url": "https://images.unsplash.com/photo-1555949963-ff9fe0c870eb?w=1200&h=400&fit=crop",
                    "duration_minutes": 30,
                    "start_offset_hours": 16,
                    "order": 8,
                    "agenda": [
                        {"title": "Why GenAI Projects Fail", "speaker_idx": 3, "dur": 10,
                         "desc": "Top reasons AI prototypes die after a promising demo."},
                        {"title": "Evaluation & Production Essentials", "speaker_idx": 3, "dur": 10,
                         "desc": "Quality, safety, robustness, monitoring, feedback loops, latency, and cost control."},
                        {"title": "Demo to Production Problem Statement", "speaker_idx": 3, "dur": 10,
                         "desc": "Rewriting a cool demo idea into a production-ready problem statement with constraints."},
                    ],
                    "session_speakers": [{"speaker_idx": 3, "role": "Keynote"}],
                    "recordings": [],
                },
            ],
            "breaks": [
                {
                    "title": "Lunch Break",
                    "description": (
                        "A purposeful pause to reset attention and energy. Use this slot to reflect "
                        "on the morning sessions, capture 5 key ideas, and convert them into questions "
                        "you want answered in the afternoon\u2014because your next question shapes your "
                        "learning path."
                    ),
                    "duration_minutes": 45,
                    "start_offset_hours": 13,
                    "order": 4,
                },
            ],
            "addons": [
                {
                    "title": "Student Voices: Open Forum and Career Guidance",
                    "description": (
                        "An interactive forum where students drive the agenda: doubts, career paths, "
                        "higher studies, projects, internships, and AI ethics. The goal is to convert "
                        "uncertainty into clarity\u2014through honest questions, peer stories, and concrete "
                        "next steps."
                    ),
                    "price": 100,
                },
            ],
            "coupons": [
                {"code": "AISUMMIT10", "discount_pct": 10, "max_uses": 50},
            ],
        },
    ]


# ═══════════════════════════════════════════════════════════════════════
#  Phase 2b – Admin API seeding
# ═══════════════════════════════════════════════════════════════════════

def phase2_api_admin(api: ApiClient, refs: dict):
    """Create events, sessions, breaks, coupons, and recordings via the admin web UI."""
    speakers = refs["speakers"]
    auditoriums = refs["auditoriums"]
    colleges = refs["colleges"]

    event_data = build_event_data(speakers, auditoriums, colleges)

    api.login("admin", "admin123")
    api.get("/admin/")
    api.get("/admin/events/new")

    now = datetime.utcnow()
    created_events = []

    for ev_idx, evd in enumerate(event_data):
        college_id = colleges[evd["college_idx"]]["id"] if evd["college_idx"] is not None else None
        aud_id = auditoriums[evd["aud_idx"]]["id"] if evd["aud_idx"] is not None else None

        start_d = (now + timedelta(days=evd["start_offset_days"])).date()
        end_d = (now + timedelta(days=evd["end_offset_days"])).date() if evd.get("end_offset_days") is not None else None

        event_form = {
            "name": evd["name"],
            "description": evd["description"],
            "banner_url": evd.get("banner_url", ""),
            "college_id": str(college_id) if college_id else "",
            "auditorium_id": str(aud_id) if aud_id else "",
            "start_date": start_d.isoformat(),
            "end_date": end_d.isoformat() if end_d else "",
            "price": str(evd.get("price", 0)),
            "price_vip": str(evd.get("price_vip") or ""),
            "price_accessible": str(evd.get("price_accessible") or ""),
            "processing_fee_pct": str(evd.get("processing_fee_pct") or ""),
            "status": evd.get("status", "draft"),
        }

        for k, v in evd.get("cert", {}).items():
            event_form[k] = v

        if evd.get("link_feedback_template") and refs.get("feedback_template_id"):
            event_form["feedback_template_id"] = str(refs["feedback_template_id"])

        api.post_form("/admin/events/new", event_form)

        db = SessionLocal()
        ev = db.query(Event).filter(Event.name == evd["name"]).order_by(Event.id.desc()).first()
        if not ev:
            print(f"    WARNING: event '{evd['name']}' was not created")
            db.close()
            continue

        created_events.append(ev)

        event_midnight = datetime.combine(start_d, datetime.min.time())

        for bi, brk in enumerate(evd.get("breaks", [])):
            brk_start = None
            if brk.get("start_offset_hours") is not None:
                brk_start = event_midnight + timedelta(
                    hours=brk["start_offset_hours"],
                )
            db.add(EventBreak(
                event_id=ev.id,
                title=brk["title"],
                description=brk.get("description"),
                duration_minutes=brk.get("duration_minutes", 15),
                start_time=brk_start,
                order=brk.get("order", bi),
            ))
        for ao in evd.get("addons", []):
            db.add(EventAddOn(
                event_id=ev.id,
                title=ao["title"],
                description=ao.get("description"),
                price=ao.get("price", 0),
                max_quantity=ao.get("max_quantity"),
                is_active=True,
            ))
        db.commit()

        for ord_idx, sd in enumerate(evd.get("sessions", [])):
            session_start = None
            if sd.get("start_offset_hours") is not None:
                session_start = event_midnight + timedelta(
                    hours=sd["start_offset_hours"],
                )

            session_form = {
                "event_id": str(ev.id),
                "title": sd["title"],
                "speaker_id": str(sd["speaker_id"]),
                "speaker_name": sd["speaker_name"],
                "description": sd.get("description", ""),
                "banner_url": sd.get("banner_url", ""),
                "duration_minutes": str(sd.get("duration_minutes", 30)),
                "start_time": session_start.isoformat() if session_start else "",
                "order": str(sd.get("order", ord_idx)),
            }

            for ai, item in enumerate(sd.get("agenda", [])):
                session_form[f"agenda_title_{ai}"] = item["title"]
                session_form[f"agenda_duration_{ai}"] = str(item["dur"])
                session_form[f"agenda_desc_{ai}"] = item.get("desc", "")
                sp_idx = item.get("speaker_idx")
                session_form[f"agenda_speaker_id_{ai}"] = str(speakers[sp_idx]["id"]) if sp_idx is not None else ""

            for si, ss in enumerate(sd.get("session_speakers", [])):
                session_form[f"session_speaker_id_{si}"] = str(speakers[ss["speaker_idx"]]["id"])
                session_form[f"session_speaker_role_{si}"] = ss["role"]

            api.post_form("/admin/sessions/new", session_form)

            sess = db.query(SessionModel).filter(
                SessionModel.event_id == ev.id,
                SessionModel.title == sd["title"],
            ).order_by(SessionModel.id.desc()).first()

            if sess:
                for rec in sd.get("recordings", []):
                    rec_data = {"url": rec["url"], "title": rec.get("title", "")}
                    if rec.get("is_public"):
                        rec_data["is_public"] = "on"
                    api.post_form(f"/admin/sessions/{sess.id}/recordings", rec_data)

        for coup in evd.get("coupons", []):
            coup_form = {
                "code": coup["code"],
                "discount_pct": str(coup.get("discount_pct", "")),
                "discount_amount": str(coup.get("discount_amount", "")),
                "max_uses": str(coup.get("max_uses", "")),
                "is_active": "on",
            }
            api.post_form(f"/admin/events/{ev.id}/coupons/new", coup_form)

        db.close()
        print(f"    [{ev_idx+1}/{len(event_data)}] {evd['name']} ({len(evd.get('sessions', []))} sessions, {len(evd.get('breaks', []))} breaks, {len(evd.get('addons', []))} add-ons)")

    db = SessionLocal()
    actual_sessions = db.query(SessionModel).count()
    actual_coupons = db.query(Coupon).count()
    actual_breaks = db.query(EventBreak).count()
    actual_addons = db.query(EventAddOn).count()
    db.close()
    print(f"  Created {len(created_events)} events, {actual_sessions} sessions, {actual_breaks} breaks, {actual_addons} add-ons, {actual_coupons} coupons")

    return {"events": created_events}


# ═══════════════════════════════════════════════════════════════════════
#  Phase 3 – User flows via API
# ═══════════════════════════════════════════════════════════════════════

def phase3_user_flows(api: ApiClient, refs: dict):
    """Simulate real user actions: bookings, waitlist, feedback, cancellations."""
    db = SessionLocal()

    today = datetime.utcnow().date()

    published = (
        db.query(Event)
        .filter(Event.status.in_(["published", "completed"]))
        .order_by(Event.start_date)
        .all()
    )
    if not published:
        print("  No published/completed events – skipping user flows.")
        db.close()
        return

    future_events = [e for e in published if e.start_date and e.start_date >= today]
    past_events = [e for e in published if e.start_date and e.start_date < today]

    bookings_made = 0
    cancellations = 0
    waitlists = 0
    feedbacks_created = 0
    checkins = 0

    # ── Book seats for alice ───────────────────────────────────────────
    api.logout()
    api.login("alice", "user123")
    for ev in future_events[:3]:
        seats = _get_available_seats(db, ev.id, count=2)
        if seats:
            ok = _book_free(api, db, ev.id, seats)
            if ok:
                bookings_made += ok
    print(f"    alice: booked {bookings_made} seat(s)")

    # ── Book seats for bob (cancel one later) ──────────────────────────
    api.logout()
    api.login("bob", "user123")
    bob_bookings_count = 0
    bob_cancel_booking_id = None
    for ev in future_events[:2]:
        seats = _get_available_seats(db, ev.id, count=1)
        if seats:
            ok = _book_free(api, db, ev.id, seats)
            if ok:
                bob_bookings_count += ok
                if bob_cancel_booking_id is None:
                    bob_hash = hash_lookup("bob", settings.field_encryption_key)
                    user_bob = db.query(User).filter(User.username_hash == bob_hash).first()
                    if user_bob:
                        latest = (
                            db.query(Booking)
                            .filter(Booking.user_id == user_bob.id,
                                    Booking.payment_status == "paid")
                            .order_by(Booking.id.desc())
                            .first()
                        )
                        if latest:
                            bob_cancel_booking_id = latest.id
    bookings_made += bob_bookings_count
    print(f"    bob: booked {bob_bookings_count} seat(s)")

    if bob_cancel_booking_id:
        api.post_form(f"/booking/cancel/{bob_cancel_booking_id}", {})
        cancellations += 1
        print(f"    bob: cancelled booking #{bob_cancel_booking_id}")

    # ── Book seats for charlie ─────────────────────────────────────────
    api.logout()
    api.login("charlie", "user123")
    charlie_count = 0
    for ev in future_events[:1]:
        seats = _get_available_seats(db, ev.id, count=1)
        if seats:
            ok = _book_free(api, db, ev.id, seats)
            if ok:
                charlie_count += ok
    bookings_made += charlie_count
    print(f"    charlie: booked {charlie_count} seat(s)")

    # ── diana: book seats ──────────────────────────────────────────────
    api.logout()
    api.login("diana", "user123")
    diana_count = 0
    for ev in future_events[:1]:
        seats = _get_available_seats(db, ev.id, count=2)
        if seats:
            ok = _book_free(api, db, ev.id, seats)
            if ok:
                diana_count += ok
    bookings_made += diana_count
    print(f"    diana: booked {diana_count} seat(s)")

    # ── Check-in some bookings (admin) ─────────────────────────────────
    api.logout()
    api.login("admin", "admin123")
    api.get("/admin/")

    for ev in past_events:
        past_bookings = (
            db.query(Booking)
            .filter(Booking.event_id == ev.id, Booking.payment_status == "paid")
            .all()
        )
        ev_start = ev.start_date
        if ev_start:
            from datetime import time as time_cls
            checkin_time = datetime.combine(ev_start, time_cls(10, 5))
            for b in past_bookings:
                b.checked_in = True
                b.checked_in_at = checkin_time
                checkins += 1
    db.commit()

    if future_events:
        first_future = (
            db.query(Booking)
            .filter(Booking.event_id == future_events[0].id,
                    Booking.payment_status == "paid",
                    Booking.checked_in == False)
            .limit(2)
            .all()
        )
        for b in first_future:
            b.checked_in = True
            b.checked_in_at = datetime.utcnow()
            checkins += 1
        db.commit()
    print(f"    Checked in {checkins} booking(s)")

    # ── Feedback for past events ───────────────────────────────────────
    feedback_comments = [
        (5, "Absolutely brilliant session! Learned so much.", True, True),
        (4, "Great content, could use more hands-on examples.", True, False),
        (5, "Best talk I've attended this year.", True, True),
        (3, "Decent overview but I wanted more depth.", False, False),
        (4, "Really enjoyed the live demo portion.", True, False),
    ]
    users = db.query(User).filter(User.is_admin == False, User.is_supervisor == False).all()
    fi = 0
    for ev in past_events:
        booked_users = (
            db.query(Booking.user_id)
            .filter(Booking.event_id == ev.id, Booking.payment_status == "paid")
            .all()
        )
        for (uid,) in booked_users:
            if fi >= len(feedback_comments):
                break
            rating, comment, allow_public, featured = feedback_comments[fi]
            existing = db.query(Feedback).filter(
                Feedback.user_id == uid, Feedback.event_id == ev.id
            ).first()
            if not existing:
                db.add(Feedback(
                    user_id=uid, event_id=ev.id,
                    rating=rating, comment=comment,
                    allow_public=allow_public, is_featured=featured,
                ))
                feedbacks_created += 1
                fi += 1
    for ev in past_events:
        for user in users[:3]:
            if fi >= len(feedback_comments):
                fi = 0
            rating, comment, allow_public, featured = feedback_comments[fi]
            existing = db.query(Feedback).filter(
                Feedback.user_id == user.id, Feedback.event_id == ev.id
            ).first()
            if not existing:
                db.add(Feedback(
                    user_id=user.id, event_id=ev.id,
                    rating=rating, comment=comment,
                    allow_public=allow_public, is_featured=featured,
                ))
                feedbacks_created += 1
                fi += 1
    db.commit()
    print(f"    Created {feedbacks_created} feedback entries")

    # ── Book amalsajeev into the past event (feedback + cert demo) ──
    past_published = [
        e for e in published
        if e.start_date and e.start_date < today and e.status == "published"
    ]
    if past_published:
        api.logout()
        api.login("amalsajeev", "speaker123")
        amal_count = 0
        for ev in past_published:
            seats = _get_available_seats(db, ev.id, count=1)
            if seats:
                ok = _book_free(api, db, ev.id, seats)
                if ok:
                    amal_count += ok
                    bookings_made += ok
        api.logout()
        print(f"    amalsajeev: booked {amal_count} seat(s) in past event(s)")

        amal_hash = hash_lookup("amalsajeev", settings.field_encryption_key)
        amal_user = db.query(User).filter(User.username_hash == amal_hash).first()
        if amal_user:
            amal_bookings = (
                db.query(Booking)
                .filter(
                    Booking.user_id == amal_user.id,
                    Booking.payment_status == "paid",
                    Booking.event_id.in_([e.id for e in past_published]),
                )
                .all()
            )
            from datetime import time as time_cls
            for b in amal_bookings:
                ev_obj = db.query(Event).get(b.event_id)
                if ev_obj and ev_obj.start_date:
                    b.checked_in = True
                    b.checked_in_at = datetime.combine(ev_obj.start_date, time_cls(10, 5))
                    checkins += 1
            db.commit()
            print(f"    amalsajeev: checked in {len(amal_bookings)} booking(s)")

        for ev in past_published:
            db.expire(ev)
            ev.status = "completed"
        db.commit()
        print(f"    Marked {len(past_published)} past event(s) as completed — ready for feedback + certificate flow")

    db.close()

    return {
        "bookings": bookings_made,
        "cancellations": cancellations,
        "waitlists": waitlists,
        "feedbacks": feedbacks_created,
        "checkins": checkins,
    }


def _get_available_seats(db, event_id: int, count: int = 1) -> list[int]:
    """Return up to `count` available (non-aisle, active) seat IDs for an event."""
    event = db.query(Event).get(event_id)
    if not event or not event.auditorium_id:
        return []

    taken = set(
        sid for (sid,) in db.query(Booking.seat_id).filter(
            Booking.event_id == event_id,
            Booking.payment_status.in_(["hold", "paid"]),
        ).all()
    )

    q = db.query(Seat).filter(
        Seat.auditorium_id == event.auditorium_id,
        Seat.is_active == True,
        Seat.seat_type != "aisle",
    )
    if taken:
        q = q.filter(~Seat.id.in_(taken))
    available = q.order_by(Seat.row_num, Seat.col_num).limit(count).all()
    return [s.id for s in available]


def _book_free(api: ApiClient, db, event_id: int, seat_ids: list[int]) -> int:
    """Hold seats then confirm as free booking. Returns number confirmed."""
    seat_str = ",".join(str(s) for s in seat_ids)
    api.post_form(f"/booking/event/{event_id}/hold", {"seat_ids": seat_str})
    api.post_form(f"/booking/event/{event_id}/pay", {})

    db.expire_all()
    confirmed = (
        db.query(Booking)
        .filter(
            Booking.event_id == event_id,
            Booking.payment_status == "paid",
            Booking.seat_id.in_(seat_ids),
        )
        .count()
    )
    return confirmed


# ═══════════════════════════════════════════════════════════════════════
#  Phase 4 – Summary
# ═══════════════════════════════════════════════════════════════════════

def phase4_summary():
    db = SessionLocal()

    counts = {
        "Users": db.query(User).count(),
        "Cities": db.query(City).count(),
        "Colleges": db.query(College).count(),
        "Auditoriums": db.query(Auditorium).count(),
        "Seats": db.query(Seat).filter(Seat.is_active == True).count(),
        "Seat Types (custom)": db.query(SeatType).filter(SeatType.is_custom == True).count(),
        "Speakers": db.query(Speaker).count(),
        "Sessions": db.query(SessionModel).count(),
        "Event Breaks": db.query(EventBreak).count(),
        "Event Add-Ons": db.query(EventAddOn).count(),
        "Events": db.query(Event).count(),
        "Coupons": db.query(Coupon).count(),
        "Bookings (paid)": db.query(Booking).filter(Booking.payment_status == "paid").count(),
        "Bookings (cancelled)": db.query(Booking).filter(Booking.payment_status == "cancelled").count(),
        "Waitlist entries": db.query(Waitlist).count(),
        "Feedback entries": db.query(Feedback).count(),
        "Testimonials": db.query(Testimonial).count(),
        "Newsletter subs": db.query(NewsletterSubscriber).count(),
        "Session recordings": db.query(SessionRecording).count(),
        "Activity log entries": db.query(ActivityLog).count(),
        "Site settings": db.query(SiteSetting).count(),
    }

    events = db.query(Event).all()
    db.close()

    print("\n" + "=" * 60)
    print("  SEED COMPLETE")
    print("=" * 60)
    print()

    col_w = max(len(k) for k in counts) + 2
    for label, cnt in counts.items():
        print(f"  {label:<{col_w}} {cnt}")

    print()
    print("  Login credentials:")
    print("  " + "-" * 45)
    print("  Admin:       admin / admin123")
    print("  Supervisor:  supervisor / supervisor123  (KSR College)")
    print("  Users:       alice, bob, charlie, diana / user123")
    print("  Speakers:    sarah, james, maria, amalsajeev / speaker123")
    print()

    print("  Events:")
    print("  " + "-" * 45)
    for ev in events:
        print(f"  Event: '{ev.name}' (id={ev.id}, status={ev.status})")
    print("  bob has a cancelled booking -> test refund view")
    print("  amalsajeev attended completed event -> feedback popup + certificate email")
    print()


# ═══════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════

def seed():
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", message=".*LegacyAPIWarning.*")
    args = parse_args()
    base_url = args.base_url or f"http://127.0.0.1:{args.port}"

    print()
    print("=" * 48)
    print("       TechTrek Seed Script")
    print("=" * 48)
    print()

    # ── Phase 1: Direct DB ─────────────────────────────────────────────
    print("[Phase 1] Database seeding ...")
    refs = phase1_db_seed(args.force)
    if refs is None:
        return

    # ── Service lifecycle ──────────────────────────────────────────────
    print()
    print("[Service] Ensuring the app is running ...")
    proc = ensure_service(base_url, args.port)

    api = ApiClient(base_url)
    try:
        # ── Phase 2: Admin API ─────────────────────────────────────────
        print()
        print("[Phase 2] Creating events, sessions, breaks, and coupons via admin API ...")
        api_refs = phase2_api_admin(api, refs)

        # ── Phase 3: User flows ────────────────────────────────────────
        print()
        print("[Phase 3] Simulating user flows (bookings, feedback) ...")
        phase3_user_flows(api, refs)

        # ── Process pending feedback (creates Feedback rows + sends cert emails) ──
        print()
        print("[Phase 3b] Processing pending feedback for completed events ...")
        from app.services.feedback import process_pending_feedback
        process_pending_feedback()
        db = SessionLocal()
        pending_count = db.query(Feedback).filter(
            Feedback.rating == None, Feedback.dismissed == False  # noqa: E711
        ).count()
        db.close()
        print(f"    Created {pending_count} pending feedback entry(ies) — popup will show on login")

    finally:
        api.close()
        if proc:
            print()
            print("[Service] Shutting down auto-launched server ...")
            proc.terminate()
            proc.wait(timeout=5)

    # ── Phase 4: Summary ───────────────────────────────────────────────
    phase4_summary()


if __name__ == "__main__":
    seed()

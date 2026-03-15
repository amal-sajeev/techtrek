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
from datetime import datetime, timedelta, timezone

import httpx

from app.database import SessionLocal, Base, engine
from app.models.user import User
from app.models.city import City
from app.models.college import College
from app.models.auditorium import Auditorium
from app.models.seat import Seat
from app.models.seat_type import SeatType
from app.models.speaker import Speaker
from app.models.session import Session as SessionModel
from app.models.showing import Showing
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
from app.models.event_showing import EventShowing
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

    def login(self, username: str, password: str):
        r = self.client.get("/auth/login")
        self._scrape_csrf(r.text)
        r = self.client.post("/auth/login", data={
            "username": username,
            "password": password,
            "csrf_token": self._csrf or "",
        })
        return r

    def logout(self):
        self.client.get("/auth/logout")
        self._csrf = None

    def get(self, path: str):
        r = self.client.get(path)
        self._scrape_csrf(r.text)
        return r

    def post_form(self, path: str, data: dict):
        if not self._csrf:
            self.get("/")
        data["csrf_token"] = self._csrf or ""
        return self.client.post(path, data=data)

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
    # Ensure schema is up to date (adds missing columns/tables)
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

    # Link supervisor to first college
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

    # Snapshot IDs into plain dicts so they survive after db.close()
    refs = {
        "speakers": [{"id": s.id, "name": s.name} for s in speakers],
        "auditoriums": [{"id": a.id, "name": a.name, "college_id": a.college_id}
                        for a in auditoriums],
        "colleges": [{"id": c.id, "name": c.name} for c in colleges],
    }
    db.close()
    return refs


def _create_seats(db, auditoriums, seat_types):
    """Generate seat grids for every auditorium."""
    aud_main, aud_lab, aud_seminar, aud_lecture, aud_micro = auditoriums

    # Main Hall 10×15 – center aisle at col 8, VIP rows 1-2, accessible edges
    for r in range(1, 11):
        for c in range(1, 16):
            if c == 8:
                stype, label, active = "aisle", "", False
            elif r <= 2:
                stype, label, active = "vip", f"{chr(64+r)}{c}", True
            elif c in (1, 15):
                stype, label, active = "accessible", f"{chr(64+r)}{c}", True
            else:
                stype, label, active = "standard", f"{chr(64+r)}{c}", True
            db.add(Seat(auditorium_id=aud_main.id, row_num=r, col_num=c,
                        label=label, seat_type=stype, is_active=active))

    # Innovation Lab 6×10 – aisle at col 5
    for r in range(1, 7):
        for c in range(1, 11):
            if c == 5:
                stype, label, active = "aisle", "", False
            else:
                stype, label, active = "standard", f"{chr(64+r)}{c}", True
            db.add(Seat(auditorium_id=aud_lab.id, row_num=r, col_num=c,
                        label=label, seat_type=stype, is_active=active))

    # Seminar Hall A 8×10 – VIP first row
    for r in range(1, 9):
        for c in range(1, 11):
            stype = "vip" if r == 1 else "standard"
            db.add(Seat(auditorium_id=aud_seminar.id, row_num=r, col_num=c,
                        label=f"{chr(64+r)}{c}", seat_type=stype,
                        is_active=True))

    # Lecture Theatre B 10×10 – custom "Premium" in first 2 rows
    custom_name = f"custom_{seat_types[0].id}"
    for r in range(1, 11):
        for c in range(1, 11):
            if r <= 2:
                stype = custom_name
            elif c in (1, 10):
                stype = "accessible"
            else:
                stype = "standard"
            db.add(Seat(auditorium_id=aud_lecture.id, row_num=r, col_num=c,
                        label=f"{chr(64+r)}{c}", seat_type=stype,
                        is_active=True))

    # Micro Hall 3×3 – all standard (tiny, for sold-out testing)
    for r in range(1, 4):
        for c in range(1, 4):
            db.add(Seat(auditorium_id=aud_micro.id, row_num=r, col_num=c,
                        label=f"{chr(64+r)}{c}", seat_type="standard",
                        is_active=True))

    db.commit()


# ═══════════════════════════════════════════════════════════════════════
#  Phase 2a – Session data definitions
# ═══════════════════════════════════════════════════════════════════════

def build_session_data(speakers, auditoriums):
    """Return a list of session dicts with all content, ready for the API.

    `speakers` and `auditoriums` are plain dicts with at least an "id" key,
    as returned by phase1_db_seed.
    """
    now = datetime.utcnow()

    # Indices into speakers list:
    #  0=Sarah  1=James  2=Maria  3=Alex  4=Priya
    #  5=Michael 6=Anika  7=Rahul  8=Amal
    # Indices into auditoriums list:
    #  0=Main Hall  1=Innovation Lab  2=Seminar Hall A
    #  3=Lecture Theatre B  4=Micro Hall

    return [
        # ── 0. The Future of AI Agents ─────────────────────────────────
        {
            "title": "The Future of AI Agents",
            "speaker_id": speakers[0]["id"],
            "speaker_name": "Dr. Sarah Chen",
            "description": (
                "Explore how autonomous AI agents are reshaping software development, "
                "from code generation to infrastructure management. We'll examine the "
                "latest breakthroughs in multi-agent collaboration, tool-use patterns, "
                "and the emerging safety frameworks that keep agents aligned with human intent."
            ),
            "banner_url": "https://images.unsplash.com/photo-1677442136019-21780ecad995?w=1200&h=400&fit=crop",
            "duration_minutes": 60,
            "showings": [
                {"aud": 0, "offset_days": 3, "offset_hours": 10, "price": 0,
                 "price_vip": 0, "price_accessible": 0, "status": "published"},
            ],
            "agenda": [
                {"title": "Introduction to AI Agents", "speaker_idx": 0, "dur": 10,
                 "desc": "What defines an agent vs. a chatbot."},
                {"title": "Autonomous Code Generation", "speaker_idx": 0, "dur": 20,
                 "desc": "Real-world code-gen pipelines at DeepMind."},
                {"title": "Live Demo: Agent-in-the-Loop", "speaker_idx": 0, "dur": 15,
                 "desc": "Watching an agent debug a production issue in real time."},
                {"title": "Q&A Session", "speaker_idx": None, "dur": 15, "desc": ""},
            ],
            "session_speakers": [
                {"speaker_idx": 0, "role": "Keynote"},
            ],
            "cert": {
                "cert_title": "Certificate of Attendance",
                "cert_subtitle": "The Future of AI Agents – TechTrek 2026",
                "cert_footer": "Issued by TechTrek Pvt Ltd",
                "cert_signer_name": "Dr. Sarah Chen",
                "cert_signer_designation": "VP of AI Research, DeepMind",
                "cert_color_scheme": "blue",
            },
            "recordings": [],
        },

        # ── 1. WebAssembly Beyond the Browser ─────────────────────────
        {
            "title": "WebAssembly Beyond the Browser",
            "speaker_id": speakers[1]["id"],
            "speaker_name": "James Kowalski",
            "description": (
                "Discover how Wasm is being used for serverless functions, edge computing, "
                "and plugin systems far from the browser. We'll build a Wasm-based plugin "
                "host live on stage and benchmark it against native code."
            ),
            "banner_url": "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=1200&h=400&fit=crop",
            "duration_minutes": 50,
            "showings": [
                {"aud": 0, "offset_days": 3, "offset_hours": 14, "price": 0,
                 "price_vip": 0, "price_accessible": 0, "status": "published"},
            ],
            "agenda": [
                {"title": "Wasm Fundamentals Refresher", "speaker_idx": 1, "dur": 10,
                 "desc": "Linear memory, modules, and the component model."},
                {"title": "Wasm on the Edge", "speaker_idx": 1, "dur": 20,
                 "desc": "Running Wasm at 200+ PoPs with Fastly Compute."},
                {"title": "Building a Wasm Plugin System", "speaker_idx": 1, "dur": 15,
                 "desc": "Live coding a host with wasmtime."},
                {"title": "Q&A", "speaker_idx": None, "dur": 5, "desc": ""},
            ],
            "session_speakers": [
                {"speaker_idx": 1, "role": "Keynote"},
            ],
            "cert": {},
            "recordings": [],
        },

        # ── 2. Hands-on Rust for Systems Programming ──────────────────
        {
            "title": "Hands-on Rust for Systems Programming",
            "speaker_id": speakers[2]["id"],
            "speaker_name": "Maria Gonzalez",
            "description": (
                "A hands-on workshop covering Rust fundamentals through building a "
                "concurrent file processor. You'll write safe, fearless code with "
                "ownership, lifetimes, and async Rust – no prior Rust experience needed."
            ),
            "banner_url": "https://images.unsplash.com/photo-1623479322729-28b25c16b011?w=1200&h=400&fit=crop",
            "duration_minutes": 90,
            "showings": [
                {"aud": 1, "offset_days": 5, "offset_hours": 14, "price": 0,
                 "price_vip": 0, "price_accessible": 0, "status": "published"},
                {"aud": 2, "offset_days": 8, "offset_hours": 10, "price": 0,
                 "price_vip": 0, "price_accessible": 0, "status": "published"},
            ],
            "agenda": [
                {"title": "Rust Setup & Ownership Basics", "speaker_idx": 2, "dur": 25,
                 "desc": "Getting Cargo running, understanding move semantics."},
                {"title": "Structs, Enums & Pattern Matching", "speaker_idx": 2, "dur": 25,
                 "desc": "Modelling data the Rust way."},
                {"title": "Concurrency with Tokio", "speaker_idx": 2, "dur": 25,
                 "desc": "Async file processing pipeline."},
                {"title": "Wrap-up & Q&A", "speaker_idx": None, "dur": 15, "desc": ""},
            ],
            "session_speakers": [
                {"speaker_idx": 2, "role": "Workshop Lead"},
            ],
            "cert": {
                "cert_title": "Workshop Completion Certificate",
                "cert_subtitle": "Hands-on Rust for Systems Programming",
                "cert_footer": "TechTrek 2026 Workshop Series",
                "cert_signer_name": "Maria Gonzalez",
                "cert_signer_designation": "Rust Core Team",
                "cert_color_scheme": "orange",
            },
            "recordings": [],
        },

        # ── 3. Scaling PostgreSQL to 10 Million Users ─────────────────
        {
            "title": "Scaling PostgreSQL to 10 Million Users",
            "speaker_id": speakers[3]["id"],
            "speaker_name": "Alex Petrov",
            "description": (
                "Real-world strategies for partitioning, connection pooling, and "
                "query optimization at scale. Alex shares war stories from Neon's "
                "serverless Postgres and shows you the tooling that makes 10M-user "
                "databases manageable."
            ),
            "banner_url": "https://images.unsplash.com/photo-1544383835-bda2bc66a55d?w=1200&h=400&fit=crop",
            "duration_minutes": 60,
            "showings": [
                {"aud": 2, "offset_days": 7, "offset_hours": 9, "price": 0,
                 "price_vip": 0, "price_accessible": 0, "status": "published"},
            ],
            "agenda": [
                {"title": "PostgreSQL Internals Overview", "speaker_idx": 3, "dur": 10,
                 "desc": "MVCC, WAL, and the query planner."},
                {"title": "Partitioning Strategies", "speaker_idx": 3, "dur": 15,
                 "desc": "Range, list, and hash partitioning in practice."},
                {"title": "Connection Pooling Deep Dive", "speaker_idx": 3, "dur": 15,
                 "desc": "PgBouncer vs. built-in pooling."},
                {"title": "Query Optimization Workshop", "speaker_idx": 3, "dur": 20,
                 "desc": "EXPLAIN ANALYZE walkthrough on real queries."},
            ],
            "session_speakers": [
                {"speaker_idx": 3, "role": "Keynote"},
            ],
            "cert": {},
            "recordings": [],
        },

        # ── 4. Designing for Accessibility ────────────────────────────
        {
            "title": "Designing for Accessibility",
            "speaker_id": speakers[4]["id"],
            "speaker_name": "Priya Sharma",
            "description": (
                "Learn WCAG 2.2 guidelines and practical techniques for building "
                "inclusive web experiences. Priya demos Google's internal accessibility "
                "audit tool and shows you how to integrate a11y testing into CI."
            ),
            "banner_url": "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?w=1200&h=400&fit=crop",
            "duration_minutes": 45,
            "showings": [
                {"aud": 1, "offset_days": 7, "offset_hours": 15, "price": 0,
                 "price_vip": 0, "price_accessible": 0, "status": "published"},
            ],
            "agenda": [
                {"title": "Why Accessibility Matters", "speaker_idx": 4, "dur": 10,
                 "desc": "The business and ethical case."},
                {"title": "WCAG 2.2 Crash Course", "speaker_idx": 4, "dur": 15,
                 "desc": "Perceivable, Operable, Understandable, Robust."},
                {"title": "Live Audit Demo", "speaker_idx": 4, "dur": 15,
                 "desc": "Auditing a real site with Lighthouse and axe."},
                {"title": "Q&A", "speaker_idx": None, "dur": 5, "desc": ""},
            ],
            "session_speakers": [
                {"speaker_idx": 4, "role": "Keynote"},
                {"speaker_idx": 0, "role": "Panelist"},
            ],
            "cert": {},
            "recordings": [],
        },

        # ── 5. Zero Trust Architecture in Practice ────────────────────
        {
            "title": "Zero Trust Architecture in Practice",
            "speaker_id": speakers[5]["id"],
            "speaker_name": "Michael Torres",
            "description": (
                "Implementing zero-trust security patterns in cloud-native applications. "
                "Michael walks through BeyondCorp at CrowdStrike, mTLS service meshes, "
                "and identity-aware proxies you can adopt today."
            ),
            "banner_url": "https://images.unsplash.com/photo-1563013544-824ae1b704d3?w=1200&h=400&fit=crop",
            "duration_minutes": 50,
            "showings": [
                {"aud": 0, "offset_days": 10, "offset_hours": 10, "price": 0,
                 "price_vip": 0, "price_accessible": 0, "status": "draft"},
            ],
            "agenda": [
                {"title": "The Zero Trust Model", "speaker_idx": 5, "dur": 15,
                 "desc": "Never trust, always verify."},
                {"title": "mTLS & Service Meshes", "speaker_idx": 5, "dur": 15,
                 "desc": "Istio and Linkerd in production."},
                {"title": "Identity-Aware Proxies", "speaker_idx": 5, "dur": 15,
                 "desc": "BeyondCorp for your org."},
                {"title": "Q&A", "speaker_idx": None, "dur": 5, "desc": ""},
            ],
            "session_speakers": [
                {"speaker_idx": 5, "role": "Keynote"},
            ],
            "cert": {},
            "recordings": [],
        },

        # ── 6. Building India's Payment Infrastructure ────────────────
        {
            "title": "Building India's Payment Infrastructure",
            "speaker_id": speakers[6]["id"],
            "speaker_name": "Anika Desai",
            "description": (
                "How Razorpay scaled to process billions in payments with reliability "
                "and security. Anika covers UPI internals, distributed transaction "
                "patterns, and what it takes to keep a payment gateway available at "
                "99.999% uptime."
            ),
            "banner_url": "https://images.unsplash.com/photo-1556742049-0cfed4f6a45d?w=1200&h=400&fit=crop",
            "duration_minutes": 55,
            "showings": [
                {"aud": 2, "offset_days": 12, "offset_hours": 10, "price": 0,
                 "price_vip": 0, "price_accessible": 0, "status": "published"},
            ],
            "agenda": [
                {"title": "UPI Under the Hood", "speaker_idx": 6, "dur": 15,
                 "desc": "NPCI architecture and settlement flows."},
                {"title": "Distributed Transactions", "speaker_idx": 6, "dur": 15,
                 "desc": "Saga pattern at Razorpay scale."},
                {"title": "Five 9s Uptime", "speaker_idx": 6, "dur": 15,
                 "desc": "Chaos engineering and graceful degradation."},
                {"title": "Q&A", "speaker_idx": None, "dur": 10, "desc": ""},
            ],
            "session_speakers": [
                {"speaker_idx": 6, "role": "Keynote"},
            ],
            "cert": {},
            "recordings": [],
        },

        # ── 7. Quantum Computing for ML Engineers ─────────────────────
        {
            "title": "Quantum Computing for ML Engineers",
            "speaker_id": speakers[7]["id"],
            "speaker_name": "Rahul Mehta",
            "description": (
                "A practical introduction to quantum machine learning – what works "
                "today and what's hype. Rahul demos Qiskit circuits on real IBM "
                "hardware and benchmarks quantum kernels vs. classical SVMs."
            ),
            "banner_url": "https://images.unsplash.com/photo-1635070041078-e363dbe005cb?w=1200&h=400&fit=crop",
            "duration_minutes": 60,
            "showings": [
                {"aud": 0, "offset_days": 14, "offset_hours": 11, "price": 0,
                 "price_vip": 0, "price_accessible": 0, "status": "published"},
            ],
            "agenda": [
                {"title": "Qubits & Gates 101", "speaker_idx": 7, "dur": 15,
                 "desc": "Superposition, entanglement, and measurement."},
                {"title": "Quantum Kernels for ML", "speaker_idx": 7, "dur": 20,
                 "desc": "Variational circuits as feature maps."},
                {"title": "Live: Running on IBM Hardware", "speaker_idx": 7, "dur": 15,
                 "desc": "Qiskit runtime demo."},
                {"title": "Q&A", "speaker_idx": None, "dur": 10, "desc": ""},
            ],
            "session_speakers": [
                {"speaker_idx": 7, "role": "Keynote"},
            ],
            "cert": {},
            "recordings": [],
        },

        # ── 8. Building Production-Ready APIs ─────────────────────────
        {
            "title": "Building Production-Ready APIs: Design, Security, and Scale",
            "speaker_id": speakers[8]["id"],
            "speaker_name": "Amal Sajeev",
            "description": (
                "A deep dive into designing REST and GraphQL APIs that are secure, "
                "versioned, and built to scale. We cover authentication (OAuth2, JWT), "
                "rate limiting, idempotency, error contracts, and observability. "
                "You'll leave with a concrete checklist and patterns you can apply "
                "in your next service."
            ),
            "banner_url": "https://images.unsplash.com/photo-1555949963-ff9fe0c870eb?w=1200&h=400&fit=crop",
            "duration_minutes": 90,
            "showings": [
                {"aud": 0, "offset_days": 2, "offset_hours": 10, "price": 0,
                 "price_vip": 0, "price_accessible": 0, "status": "published"},
                {"aud": 3, "offset_days": 9, "offset_hours": 10, "price": 0,
                 "price_vip": 0, "price_accessible": 0, "status": "published"},
            ],
            "agenda": [
                {"title": "API Design Principles & Versioning", "speaker_idx": 8, "dur": 20,
                 "desc": "Resource naming, pagination, HATEOAS vs. pragmatism."},
                {"title": "Auth, Rate Limits, Idempotency", "speaker_idx": 8, "dur": 25,
                 "desc": "OAuth2 flows, sliding-window rate limiters, idempotency keys."},
                {"title": "Error Contracts & Observability", "speaker_idx": 8, "dur": 20,
                 "desc": "RFC 7807 problem details, structured logging, OpenTelemetry."},
                {"title": "Checklist & Q&A", "speaker_idx": 8, "dur": 25,
                 "desc": "Production readiness review you can adopt."},
            ],
            "session_speakers": [
                {"speaker_idx": 8, "role": "Keynote"},
                {"speaker_idx": 3, "role": "Panelist"},
            ],
            "cert": {
                "cert_title": "Certificate of Attendance",
                "cert_subtitle": "Building Production-Ready APIs – TechTrek 2026",
                "cert_footer": "Issued by TechTrek Pvt Ltd",
                "cert_signer_name": "Amal Sajeev",
                "cert_signer_designation": "Principal Engineer",
                "cert_color_scheme": "green",
            },
            "recordings": [],
        },

        # ── 9. From Monolith to Microservices ─────────────────────────
        {
            "title": "From Monolith to Microservices: A Practical Migration Guide",
            "speaker_id": speakers[8]["id"],
            "speaker_name": "Amal Sajeev",
            "description": (
                "Real-world strategies for incrementally breaking down a monolith "
                "without big-bang rewrites. We discuss bounded contexts, strangler-fig "
                "pattern, shared databases vs events, and how to keep teams unblocked "
                "during the transition."
            ),
            "banner_url": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1200&h=400&fit=crop",
            "duration_minutes": 90,
            "showings": [
                {"aud": 1, "offset_days": 4, "offset_hours": 14, "price": 0,
                 "price_vip": 0, "price_accessible": 0, "status": "published"},
            ],
            "agenda": [
                {"title": "Bounded Contexts & Migration Strategies", "speaker_idx": 8, "dur": 25,
                 "desc": "Identifying seams in your monolith."},
                {"title": "Strangler Fig & Incremental Extraction", "speaker_idx": 8, "dur": 25,
                 "desc": "Routing traffic through the new service."},
                {"title": "Data and Events During Transition", "speaker_idx": 8, "dur": 20,
                 "desc": "Change-data-capture vs. dual writes."},
                {"title": "Q&A and War Stories", "speaker_idx": 8, "dur": 20,
                 "desc": "Lessons from high-traffic migrations."},
            ],
            "session_speakers": [
                {"speaker_idx": 8, "role": "Keynote"},
            ],
            "cert": {},
            "recordings": [],
        },

        # ── 10. Clean Code in the Real World ──────────────────────────
        {
            "title": "Clean Code in the Real World: Readability, Tests, and Refactoring",
            "speaker_id": speakers[8]["id"],
            "speaker_name": "Amal Sajeev",
            "description": (
                "Principles from Clean Code and beyond applied to everyday codebases. "
                "We focus on naming, small functions, testability, and safe refactoring "
                "techniques. Includes live refactoring of sample code to show "
                "before/after."
            ),
            "banner_url": "https://images.unsplash.com/photo-1461749280684-dccba630e2f6?w=1200&h=400&fit=crop",
            "duration_minutes": 90,
            "showings": [
                {"aud": 2, "offset_days": 6, "offset_hours": 9, "price": 0,
                 "price_vip": 0, "price_accessible": 0, "status": "published"},
            ],
            "agenda": [
                {"title": "Naming and Small Functions", "speaker_idx": 8, "dur": 20,
                 "desc": "Why good names eliminate comments."},
                {"title": "Testability and Dependency Injection", "speaker_idx": 8, "dur": 25,
                 "desc": "Designing code that's easy to test."},
                {"title": "Live Refactoring Demo", "speaker_idx": 8, "dur": 35,
                 "desc": "Transforming messy code step by step."},
                {"title": "Q&A", "speaker_idx": 8, "dur": 10, "desc": ""},
            ],
            "session_speakers": [
                {"speaker_idx": 8, "role": "Workshop Lead"},
            ],
            "cert": {
                "cert_title": "Workshop Completion Certificate",
                "cert_subtitle": "Clean Code in the Real World",
                "cert_footer": "TechTrek 2026 Workshop Series",
                "cert_signer_name": "Amal Sajeev",
                "cert_signer_designation": "Principal Engineer",
                "cert_color_scheme": "purple",
            },
            "recordings": [],
        },

        # ── 11. Developer Experience ──────────────────────────────────
        {
            "title": "Developer Experience: Building Tools and Docs That Engineers Love",
            "speaker_id": speakers[8]["id"],
            "speaker_name": "Amal Sajeev",
            "description": (
                "Why great DX leads to faster adoption and fewer support tickets. "
                "We cover CLI design, SDK ergonomics, API documentation (OpenAPI, "
                "guides, examples), internal platforms, and measuring developer happiness."
            ),
            "banner_url": "https://images.unsplash.com/photo-1504639725590-34d0984388bd?w=1200&h=400&fit=crop",
            "duration_minutes": 90,
            "showings": [
                {"aud": 0, "offset_days": 8, "offset_hours": 14, "price": 0,
                 "price_vip": 0, "price_accessible": 0, "status": "published"},
            ],
            "agenda": [
                {"title": "Why DX Matters: Metrics and Outcomes", "speaker_idx": 8, "dur": 15,
                 "desc": "DORA metrics and developer satisfaction surveys."},
                {"title": "CLIs, SDKs, and API Docs", "speaker_idx": 8, "dur": 30,
                 "desc": "Designing Stripe-quality developer tools."},
                {"title": "Internal Platforms & Measuring Happiness", "speaker_idx": 8, "dur": 25,
                 "desc": "Platform engineering done right."},
                {"title": "Q&A", "speaker_idx": None, "dur": 20, "desc": ""},
            ],
            "session_speakers": [
                {"speaker_idx": 8, "role": "Keynote"},
                {"speaker_idx": 1, "role": "Panelist"},
            ],
            "cert": {},
            "recordings": [],
        },

        # ── 12. Past session (for feedback/recording testing) ─────────
        {
            "title": "Introduction to Cloud-Native Development",
            "speaker_id": speakers[3]["id"],
            "speaker_name": "Alex Petrov",
            "description": (
                "A beginner-friendly introduction to containers, Kubernetes, and "
                "12-factor apps. This session has already happened and has recordings "
                "and feedback data seeded."
            ),
            "banner_url": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1200&h=400&fit=crop",
            "duration_minutes": 45,
            "showings": [
                {"aud": 4, "offset_days": -5, "offset_hours": 10, "price": 0,
                 "price_vip": 0, "price_accessible": 0, "status": "published"},
            ],
            "agenda": [
                {"title": "Containers 101", "speaker_idx": 3, "dur": 15,
                 "desc": "Docker, OCI images, and runtimes."},
                {"title": "Kubernetes Essentials", "speaker_idx": 3, "dur": 15,
                 "desc": "Pods, services, and deployments."},
                {"title": "12-Factor Walkthrough", "speaker_idx": 3, "dur": 15,
                 "desc": "Config, logging, and disposability."},
            ],
            "session_speakers": [
                {"speaker_idx": 3, "role": "Keynote"},
                {"speaker_idx": 8, "role": "Moderator"},
            ],
            "cert": {},
            "recordings": [
                {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                 "title": "Full Session Recording", "is_public": True},
                {"url": "https://www.youtube.com/watch?v=J---aiyznGQ",
                 "title": "Q&A Highlights", "is_public": False},
            ],
        },

        # ── 13. Past session in Micro Hall (sold-out testing) ─────────
        {
            "title": "Lightning Talk: The Art of Code Review",
            "speaker_id": speakers[4]["id"],
            "speaker_name": "Priya Sharma",
            "description": (
                "A short, punchy talk on giving and receiving code reviews "
                "effectively. Held in the tiny Micro Hall – perfect for testing "
                "sold-out scenarios."
            ),
            "banner_url": "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?w=1200&h=400&fit=crop",
            "duration_minutes": 30,
            "showings": [
                {"aud": 4, "offset_days": 5, "offset_hours": 16, "price": 0,
                 "price_vip": 0, "price_accessible": 0, "status": "published"},
            ],
            "agenda": [
                {"title": "What Makes a Great Review", "speaker_idx": 4, "dur": 10,
                 "desc": "Empathy, specificity, and scope."},
                {"title": "Common Anti-Patterns", "speaker_idx": 4, "dur": 10,
                 "desc": "Nit-picking vs. architectural feedback."},
                {"title": "Q&A", "speaker_idx": None, "dur": 10, "desc": ""},
            ],
            "session_speakers": [
                {"speaker_idx": 4, "role": "Keynote"},
            ],
            "cert": {},
            "recordings": [],
        },
    ]


# ═══════════════════════════════════════════════════════════════════════
#  Phase 2b – Admin API seeding
# ═══════════════════════════════════════════════════════════════════════

def phase2_api_admin(api: ApiClient, refs: dict):
    """Create sessions, showings, events via the admin web UI."""
    speakers = refs["speakers"]
    auditoriums = refs["auditoriums"]
    colleges = refs["colleges"]

    session_data = build_session_data(speakers, auditoriums)

    # Login as admin
    api.login("admin", "admin123")
    api.get("/admin/")

    now = datetime.utcnow()
    created_sessions = []
    all_showings = []

    for idx, sd in enumerate(session_data):
        first_showing = sd["showings"][0]
        aud = auditoriums[first_showing["aud"]]
        start = now + timedelta(days=first_showing["offset_days"],
                                hours=first_showing["offset_hours"])

        form = {
            "title": sd["title"],
            "speaker_id": str(sd["speaker_id"]),
            "speaker_name": sd["speaker_name"],
            "description": sd["description"],
            "banner_url": sd.get("banner_url", ""),
            "duration_minutes": str(sd["duration_minutes"]),
            "auditorium_id": str(aud["id"]),
            "start_time": start.isoformat(),
            "price": str(first_showing["price"]),
            "price_vip": str(first_showing.get("price_vip", "")),
            "price_accessible": str(first_showing.get("price_accessible", "")),
            "processing_fee_pct": str(first_showing.get("processing_fee_pct", "")),
            "status": first_showing["status"],
        }

        # Certificate fields
        for k, v in sd.get("cert", {}).items():
            form[k] = v

        # Agenda items
        for ai, item in enumerate(sd.get("agenda", [])):
            form[f"agenda_title_{ai}"] = item["title"]
            form[f"agenda_duration_{ai}"] = str(item["dur"])
            form[f"agenda_desc_{ai}"] = item.get("desc", "")
            sp_idx = item.get("speaker_idx")
            form[f"agenda_speaker_id_{ai}"] = str(speakers[sp_idx]["id"]) if sp_idx is not None else ""

        # Session speakers
        for si, ss in enumerate(sd.get("session_speakers", [])):
            form[f"session_speaker_id_{si}"] = str(speakers[ss["speaker_idx"]]["id"])
            form[f"session_speaker_role_{si}"] = ss["role"]

        r = api.post_form("/admin/sessions/new", form)

        # After redirect, figure out the session ID from the DB
        db = SessionLocal()
        sess = db.query(SessionModel).filter(SessionModel.title == sd["title"]).first()
        if not sess:
            print(f"    WARNING: session '{sd['title']}' was not created")
            db.close()
            continue

        created_sessions.append(sess)
        first_sh = db.query(Showing).filter(Showing.session_id == sess.id).first()
        if first_sh:
            all_showings.append(first_sh)

        # Additional showings beyond the first
        for extra in sd["showings"][1:]:
            extra_aud = auditoriums[extra["aud"]]
            extra_start = now + timedelta(days=extra["offset_days"],
                                          hours=extra["offset_hours"])
            r = api.post_form(f"/admin/sessions/{sess.id}/showings/new", {
                "auditorium_id": str(extra_aud["id"]),
                "start_time": extra_start.isoformat(),
                "duration_minutes": str(sd["duration_minutes"]),
                "price": str(extra["price"]),
                "price_vip": str(extra.get("price_vip", "")),
                "price_accessible": str(extra.get("price_accessible", "")),
                "processing_fee_pct": str(extra.get("processing_fee_pct", "")),
                "status": extra["status"],
            })
            extra_sh = (
                db.query(Showing)
                .filter(Showing.session_id == sess.id,
                        Showing.auditorium_id == extra_aud["id"])
                .order_by(Showing.id.desc())
                .first()
            )
            if extra_sh:
                all_showings.append(extra_sh)

        # Recordings
        for rec in sd.get("recordings", []):
            rec_data = {"url": rec["url"], "title": rec.get("title", "")}
            if rec.get("is_public"):
                rec_data["is_public"] = "on"
            api.post_form(f"/admin/sessions/{sess.id}/recordings", rec_data)

        db.close()
        print(f"    [{idx+1}/{len(session_data)}] {sd['title']}")

    print(f"  Created {len(created_sessions)} sessions with {len(all_showings)} showings")

    # ── Events ─────────────────────────────────────────────────────────
    db = SessionLocal()
    # Refresh showings from DB
    all_showings_db = db.query(Showing).filter(
        Showing.status == "published"
    ).order_by(Showing.start_time).all()

    # Group showings by college (via auditorium)
    college_showings: dict[int, list[Showing]] = {}
    for sh in all_showings_db:
        aud = db.query(Auditorium).get(sh.auditorium_id)
        if aud and aud.college_id:
            college_showings.setdefault(aud.college_id, []).append(sh)

    events_created = 0

    def _create_event(name, desc, banner, college_id, discount, status, showings):
        form_data = {
            "csrf_token": api._csrf or "",
            "name": name,
            "description": desc,
            "banner_url": banner,
            "college_id": str(college_id) if college_id else "",
            "discount_pct": str(discount) if discount else "",
            "status": status,
        }
        form_data["session_ids"] = [str(sh.id) for sh in showings]
        api.client.post("/admin/events/new", data=form_data, follow_redirects=True)

    ksr_id = colleges[0]["id"]
    anna_id = colleges[1]["id"]
    dtu_id = colleges[2]["id"]
    iiit_id = colleges[4]["id"]

    ksr_showings = college_showings.get(ksr_id, [])
    anna_showings = college_showings.get(anna_id, [])
    dtu_showings = college_showings.get(dtu_id, [])
    iiit_showings = college_showings.get(iiit_id, [])

    # Separate KSR showings by venue for different events
    ksr_main = [s for s in ksr_showings
                if db.query(Auditorium).get(s.auditorium_id).name != "Micro Hall"]
    ksr_micro = [s for s in ksr_showings
                 if db.query(Auditorium).get(s.auditorium_id).name == "Micro Hall"]

    # Event 1: KSR TechFest – large multi-day event (5 sessions)
    if len(ksr_main) >= 2:
        _create_event(
            "KSR TechFest 2026",
            "A multi-day technology festival at KSR College featuring AI, APIs, "
            "WebAssembly, and developer experience talks from top industry speakers.",
            "https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=1200&h=400&fit=crop",
            ksr_id, 10, "published", ksr_main[:5],
        )
        events_created += 1

    # Event 2: IIIT Bangalore Workshop Series (4 sessions)
    if len(iiit_showings) >= 2:
        _create_event(
            "IIIT Bangalore Workshop Series",
            "Intensive hands-on workshops on Rust, PostgreSQL, payments, and "
            "clean code practices at IIIT Bangalore.",
            "https://images.unsplash.com/photo-1517245386807-bb43f82c33c4?w=1200&h=400&fit=crop",
            iiit_id, 15, "published", iiit_showings[:4],
        )
        events_created += 1

    # Event 3: DTU Innovation Day (3 sessions)
    if len(dtu_showings) >= 1:
        _create_event(
            "DTU Innovation Day 2026",
            "A full day of innovation at Delhi Technological University covering "
            "Rust, accessibility, and microservices architecture.",
            "https://images.unsplash.com/photo-1523580494863-6f3031224c94?w=1200&h=400&fit=crop",
            dtu_id, 5, "published", dtu_showings[:3],
        )
        events_created += 1

    # Event 4: Anna University API Deep Dive (1 session – small single-talk event)
    if anna_showings:
        _create_event(
            "Anna University API Deep Dive",
            "An intensive single-session event focused on building production-ready "
            "APIs, hosted at Anna University's Lecture Theatre.",
            "https://images.unsplash.com/photo-1555949963-ff9fe0c870eb?w=1200&h=400&fit=crop",
            anna_id, 0, "published", anna_showings[:1],
        )
        events_created += 1

    # Event 5: KSR Lightning Sessions – small Micro Hall event (2 sessions)
    if ksr_micro:
        _create_event(
            "KSR Lightning Sessions",
            "Quick-fire talks and demos in the intimate Micro Hall. "
            "Limited seats — book early!",
            "https://images.unsplash.com/photo-1475721027785-f74eccf877e2?w=1200&h=400&fit=crop",
            ksr_id, 0, "published", ksr_micro[:2],
        )
        events_created += 1

    # Event 6: National TechTrek Tour – cross-college draft (6 sessions)
    tour_showings = []
    for pool in (ksr_main, iiit_showings, dtu_showings, anna_showings):
        for sh in pool[:2]:
            if sh not in tour_showings:
                tour_showings.append(sh)
            if len(tour_showings) >= 6:
                break
        if len(tour_showings) >= 6:
            break
    if len(tour_showings) >= 3:
        _create_event(
            "National TechTrek Tour 2026",
            "The flagship nationwide tour bringing TechTrek's best sessions to "
            "colleges across India. This draft event is being planned for Q3.",
            "https://images.unsplash.com/photo-1492538368677-f6e0afe31dcc?w=1200&h=400&fit=crop",
            None, 20, "draft", tour_showings,
        )
        events_created += 1

    db.close()
    print(f"  Created {events_created} events")

    return {"sessions": created_sessions, "showings": all_showings}


# ═══════════════════════════════════════════════════════════════════════
#  Phase 3 – User flows via API
# ═══════════════════════════════════════════════════════════════════════

def phase3_user_flows(api: ApiClient, refs: dict):
    """Simulate real user actions: bookings, waitlist, feedback, cancellations."""
    db = SessionLocal()

    # Get published showings
    published = (
        db.query(Showing)
        .filter(Showing.status == "published")
        .order_by(Showing.start_time)
        .all()
    )
    if not published:
        print("  No published showings – skipping user flows.")
        db.close()
        return

    # Separate past and future showings
    now = datetime.utcnow()
    future_showings = [s for s in published if s.start_time > now]
    past_showings = [s for s in published if s.start_time <= now]

    bookings_made = 0
    cancellations = 0
    waitlists = 0
    feedbacks_created = 0
    checkins = 0

    # ── Book seats for alice (2-3 future showings) ─────────────────────
    api.logout()
    api.login("alice", "user123")
    for showing in future_showings[:3]:
        seats = _get_available_seats(db, showing.id, count=2)
        if seats:
            ok = _book_free(api, db, showing.id, seats)
            if ok:
                bookings_made += ok
    print(f"    alice: booked {bookings_made} seat(s)")

    # ── Book seats for bob (2 showings, cancel one later) ──────────────
    api.logout()
    api.login("bob", "user123")
    bob_bookings_count = 0
    bob_cancel_booking_id = None
    for showing in future_showings[1:3]:
        seats = _get_available_seats(db, showing.id, count=1)
        if seats:
            ok = _book_free(api, db, showing.id, seats)
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

    # Cancel one of bob's bookings
    if bob_cancel_booking_id:
        api.post_form(f"/booking/cancel/{bob_cancel_booking_id}", {})
        cancellations += 1
        print(f"    bob: cancelled booking #{bob_cancel_booking_id}")

    # ── Book seats for charlie + waitlist ───────────────────────────────
    api.logout()
    api.login("charlie", "user123")
    charlie_count = 0
    for showing in future_showings[2:4]:
        seats = _get_available_seats(db, showing.id, count=1)
        if seats:
            ok = _book_free(api, db, showing.id, seats)
            if ok:
                charlie_count += ok
    bookings_made += charlie_count
    print(f"    charlie: booked {charlie_count} seat(s)")

    # Find the Micro Hall showing (tiny venue) for waitlist
    micro_showings = [
        s for s in future_showings
        if db.query(Auditorium).get(s.auditorium_id).name == "Micro Hall"
    ]
    if micro_showings:
        api.post_form(f"/booking/waitlist/{micro_showings[0].id}", {})
        waitlists += 1
        print(f"    charlie: joined waitlist for showing #{micro_showings[0].id}")

    # ── diana: book the Micro Hall showing (sell it out) ───────────────
    api.logout()
    api.login("diana", "user123")
    diana_count = 0
    if micro_showings:
        micro_sh = micro_showings[0]
        all_micro_seats = _get_available_seats(db, micro_sh.id, count=9)
        if all_micro_seats:
            ok = _book_free(api, db, micro_sh.id, all_micro_seats)
            if ok:
                diana_count += ok
    # Also book a regular showing
    if len(future_showings) > 4:
        seats = _get_available_seats(db, future_showings[4].id, count=2)
        if seats:
            ok = _book_free(api, db, future_showings[4].id, seats)
            if ok:
                diana_count += ok
    bookings_made += diana_count
    print(f"    diana: booked {diana_count} seat(s)")

    # ── Check-in some bookings (admin) ─────────────────────────────────
    api.logout()
    api.login("admin", "admin123")
    api.get("/admin/")

    # Mark some past-showing bookings as checked in via DB
    for sh in past_showings:
        past_bookings = (
            db.query(Booking)
            .filter(Booking.showing_id == sh.id, Booking.payment_status == "paid")
            .all()
        )
        for b in past_bookings:
            b.checked_in = True
            b.checked_in_at = sh.start_time + timedelta(minutes=5)
            checkins += 1
    db.commit()

    # Also check in a few future bookings for testing
    if future_showings:
        first_future = (
            db.query(Booking)
            .filter(Booking.showing_id == future_showings[0].id,
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

    # ── Feedback for past showings ─────────────────────────────────────
    feedback_comments = [
        (5, "Absolutely brilliant session! Learned so much.", True, True),
        (4, "Great content, could use more hands-on examples.", True, False),
        (5, "Best talk I've attended this year.", True, True),
        (3, "Decent overview but I wanted more depth.", False, False),
        (4, "Really enjoyed the live demo portion.", True, False),
    ]
    users = db.query(User).filter(User.is_admin == False, User.is_supervisor == False).all()
    fi = 0
    for sh in past_showings:
        booked_users = (
            db.query(Booking.user_id)
            .filter(Booking.showing_id == sh.id, Booking.payment_status == "paid")
            .all()
        )
        for (uid,) in booked_users:
            if fi >= len(feedback_comments):
                break
            rating, comment, allow_public, featured = feedback_comments[fi]
            existing = db.query(Feedback).filter(
                Feedback.user_id == uid, Feedback.showing_id == sh.id
            ).first()
            if not existing:
                db.add(Feedback(
                    user_id=uid, showing_id=sh.id,
                    rating=rating, comment=comment,
                    allow_public=allow_public, is_featured=featured,
                ))
                feedbacks_created += 1
                fi += 1
    # Also add feedback from known users for past showings
    for sh in past_showings:
        for user in users[:3]:
            if fi >= len(feedback_comments):
                fi = 0
            rating, comment, allow_public, featured = feedback_comments[fi]
            existing = db.query(Feedback).filter(
                Feedback.user_id == user.id, Feedback.showing_id == sh.id
            ).first()
            if not existing:
                db.add(Feedback(
                    user_id=user.id, showing_id=sh.id,
                    rating=rating, comment=comment,
                    allow_public=allow_public, is_featured=featured,
                ))
                feedbacks_created += 1
                fi += 1
    db.commit()
    print(f"    Created {feedbacks_created} feedback entries")

    db.close()

    return {
        "bookings": bookings_made,
        "cancellations": cancellations,
        "waitlists": waitlists,
        "feedbacks": feedbacks_created,
        "checkins": checkins,
    }


def _get_available_seats(db, showing_id: int, count: int = 1) -> list[int]:
    """Return up to `count` available (non-aisle, active) seat IDs for a showing."""
    showing = db.query(Showing).get(showing_id)
    if not showing:
        return []

    taken = set(
        sid for (sid,) in
        db.query(Booking.seat_id)
        .filter(Booking.showing_id == showing_id,
                Booking.payment_status.in_(["hold", "paid"]))
        .all()
    )

    q = (
        db.query(Seat)
        .filter(Seat.auditorium_id == showing.auditorium_id,
                Seat.is_active == True,
                Seat.seat_type != "aisle")
    )
    if taken:
        q = q.filter(~Seat.id.in_(taken))
    available = q.order_by(Seat.row_num, Seat.col_num).limit(count).all()
    return [s.id for s in available]


def _book_free(api: ApiClient, db, showing_id: int, seat_ids: list[int]) -> int:
    """Hold seats then confirm as free booking. Returns number confirmed."""
    seat_str = ",".join(str(s) for s in seat_ids)
    api.post_form(f"/booking/hold/{showing_id}", {"seat_ids": seat_str})
    api.post_form(f"/booking/pay/{showing_id}", {})

    # Verify
    db.expire_all()
    confirmed = (
        db.query(Booking)
        .filter(Booking.showing_id == showing_id,
                Booking.payment_status == "paid",
                Booking.seat_id.in_(seat_ids))
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
        "Showings": db.query(Showing).count(),
        "Events": db.query(Event).count(),
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

    # Sold-out showings
    micro_aud = db.query(Auditorium).filter(Auditorium.name == "Micro Hall").first()
    sold_out_ids = []
    if micro_aud:
        micro_showings = db.query(Showing).filter(
            Showing.auditorium_id == micro_aud.id,
            Showing.status == "published",
        ).all()
        for sh in micro_showings:
            total_seats = db.query(Seat).filter(
                Seat.auditorium_id == micro_aud.id,
                Seat.is_active == True,
                Seat.seat_type != "aisle",
            ).count()
            booked = db.query(Booking).filter(
                Booking.showing_id == sh.id,
                Booking.payment_status.in_(["hold", "paid"]),
            ).count()
            if booked >= total_seats:
                sold_out_ids.append(sh.id)

    # Events
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

    print("  Notable test scenarios:")
    print("  " + "-" * 45)
    if sold_out_ids:
        print(f"  Sold-out showings (Micro Hall):  IDs {sold_out_ids}")
        print("    -> charlie is on the waitlist for these")
    for ev in events:
        status = ev.status
        print(f"  Event: '{ev.name}' (id={ev.id}, status={status})")
    print("  bob has a cancelled booking -> test refund view")
    print("  Past showings have feedback + recordings -> test those pages")
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
        print("[Phase 2] Creating sessions, showings, and events via admin API ...")
        api_refs = phase2_api_admin(api, refs)

        # ── Phase 3: User flows ────────────────────────────────────────
        print()
        print("[Phase 3] Simulating user flows (bookings, waitlist, feedback) ...")
        phase3_user_flows(api, refs)

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

"""Seed script to populate the database with sample data for development."""

import argparse
import bcrypt
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal, Base, engine
from app.models.user import User
from app.models.city import City
from app.models.college import College
from app.models.auditorium import Auditorium
from app.models.seat import Seat
from app.models.speaker import Speaker
from app.models.session import LectureSession
from app.models.agenda import AgendaItem
from app.models.testimonial import Testimonial, NewsletterSubscriber
from app.models.booking import Booking
from app.models.waitlist import Waitlist
from app.models.activity_log import ActivityLog


def seed(force: bool = False):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    if db.query(User).count() > 0 and not force:
        print("Database already seeded. Skipping. (Use --force to clear and re-seed.)")
        db.close()
        return

    if force and db.query(User).count() > 0:
        print("Force re-seed: clearing existing data...")
        db.query(AgendaItem).delete()
        db.query(Booking).delete()
        db.query(Waitlist).delete()
        db.query(ActivityLog).delete()
        db.query(LectureSession).delete()
        db.query(Seat).delete()
        db.query(Auditorium).delete()
        db.query(College).delete()
        db.query(City).delete()
        db.query(Testimonial).delete()
        db.query(NewsletterSubscriber).delete()
        db.query(Speaker).delete()
        db.query(User).delete()
        db.commit()
        print("Cleared. Seeding...")

    pw = lambda p: bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

    # ── Users ──
    admin = User(
        username="admin", email="admin@techtrek.dev", password_hash=pw("admin123"),
        full_name="Admin User", is_admin=True,
    )
    alice = User(
        username="alice", email="alice@example.com", password_hash=pw("user123"),
        full_name="Alice Verma", college="KSR College of Engineering",
        discipline="CSE", domain="AI", year_of_study=3,
    )
    bob = User(
        username="bob", email="bob@example.com", password_hash=pw("user123"),
        full_name="Bob Sharma", college="Delhi Technological University",
        discipline="IT", domain="Cloud Computing", year_of_study=2,
    )
    charlie = User(
        username="charlie", email="charlie@example.com", password_hash=pw("user123"),
        full_name="Charlie Patel", college="BITS Pilani",
        discipline="ECE", domain="IoT", year_of_study=4,
    )
    speaker_sarah = User(
        username="sarah", email="sarah@deepmind.example.com", password_hash=pw("speaker123"),
        full_name="Dr. Sarah Chen",
    )
    speaker_james = User(
        username="james", email="james@fastly.example.com", password_hash=pw("speaker123"),
        full_name="James Kowalski",
    )
    speaker_maria = User(
        username="maria", email="maria@rust.example.com", password_hash=pw("speaker123"),
        full_name="Maria Gonzalez",
    )
    speaker_amal = User(
        username="amalsajeev", email="amsajeev333@gmail.com", password_hash=pw("speaker123"),
        full_name="Amal Sajeev",
    )
    db.add_all([admin, alice, bob, charlie, speaker_sarah, speaker_james, speaker_maria, speaker_amal])
    db.commit()
    for u in [speaker_sarah, speaker_james, speaker_maria, speaker_amal]:
        db.refresh(u)
    print("Created users: admin/admin123, alice/user123, bob/user123, charlie/user123")
    print("Created speaker users: sarah/speaker123, james/speaker123, maria/speaker123, amalsajeev/speaker123 (amsajeev333@gmail.com)")

    # ── Cities ──
    cities = [
        City(name="Chennai", state="Tamil Nadu", is_active=True),
        City(name="Delhi", state="Delhi", is_active=True),
        City(name="Bangalore", state="Karnataka", is_active=True),
        City(name="Mumbai", state="Maharashtra", is_active=True),
        City(name="Pune", state="Maharashtra", is_active=True),
    ]
    db.add_all(cities)
    db.commit()
    for c in cities:
        db.refresh(c)
    print(f"Created {len(cities)} cities")

    # ── Colleges ──
    colleges = [
        College(name="KSR College of Engineering", city_id=cities[0].id, address="KSR Kalvi Nagar, Tiruchengode", is_active=True),
        College(name="Anna University", city_id=cities[0].id, address="Guindy, Chennai", is_active=True),
        College(name="Delhi Technological University", city_id=cities[1].id, address="Shahbad Daulatpur, Delhi", is_active=True),
        College(name="IIT Delhi", city_id=cities[1].id, address="Hauz Khas, New Delhi", is_active=True),
        College(name="IIIT Bangalore", city_id=cities[2].id, address="26th Main Rd, Bangalore", is_active=True),
        College(name="BITS Pilani - Goa Campus", city_id=cities[3].id, address="Zuarinagar, Goa", is_active=True),
    ]
    db.add_all(colleges)
    db.commit()
    for c in colleges:
        db.refresh(c)
    print(f"Created {len(colleges)} colleges")

    # ── Speakers ──
    speakers = [
        Speaker(name="Dr. Sarah Chen", title="VP of AI Research, DeepMind", bio="Leading researcher in autonomous agents and reinforcement learning with 15+ years of experience.", email="sarah@deepmind.example.com", photo_url="https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=200&h=200&fit=crop", user_id=speaker_sarah.id),
        Speaker(name="James Kowalski", title="Staff Engineer, Fastly", bio="WebAssembly pioneer and edge computing evangelist. Co-author of the WASI spec.", email="james@fastly.example.com", user_id=speaker_james.id),
        Speaker(name="Maria Gonzalez", title="Rust Core Team Member", bio="Systems programming expert and Rust educator. Author of 'Rust in Action'.", email="maria@rust.example.com", user_id=speaker_maria.id),
        Speaker(name="Alex Petrov", title="Principal DB Engineer, Neon", bio="PostgreSQL internals expert. Speaker at PGConf and author of 'Database Internals'.", email="alex@neon.example.com"),
        Speaker(name="Priya Sharma", title="Accessibility Lead, Google", bio="WCAG expert and inclusive design advocate. Built Google's accessibility testing framework.", email="priya@google.example.com"),
        Speaker(name="Michael Torres", title="CISO, CrowdStrike", bio="Cybersecurity veteran with experience in zero-trust architecture and threat detection.", email="michael@crowdstrike.example.com"),
        Speaker(name="Anika Desai", title="CTO, Razorpay", bio="Fintech leader scaling payment infrastructure for millions of businesses across India."),
        Speaker(name="Rahul Mehta", title="ML Lead, Microsoft Research", bio="Quantum computing researcher working on practical quantum ML applications."),
        Speaker(name="Amal Sajeev", title="Principal Engineer & Tech Speaker", bio="Full-stack architect and developer advocate with 12+ years building scalable systems. Former tech lead at multiple product companies. Passionate about clean code, APIs, and teaching the next generation of engineers.", email="amsajeev333@gmail.com", user_id=speaker_amal.id),
    ]
    db.add_all(speakers)
    db.commit()
    for s in speakers:
        db.refresh(s)
    print(f"Created {len(speakers)} speakers")

    # ── Auditoriums ──
    aud1 = Auditorium(
        name="Main Hall", college_id=colleges[0].id,
        location="KSR College, Tiruchengode",
        description="Flagship 150-seat auditorium with state-of-the-art AV equipment.",
        total_rows=10, total_cols=15,
    )
    aud2 = Auditorium(
        name="Innovation Lab", college_id=colleges[2].id,
        location="DTU Campus, Delhi",
        description="Intimate 60-seat space for hands-on workshops.",
        total_rows=6, total_cols=10,
    )
    aud3 = Auditorium(
        name="Seminar Hall A", college_id=colleges[4].id,
        location="IIIT Bangalore Campus",
        description="Modern 80-seat seminar hall with tiered seating.",
        total_rows=8, total_cols=10,
    )
    db.add_all([aud1, aud2, aud3])
    db.commit()
    for a in [aud1, aud2, aud3]:
        db.refresh(a)

    # ── Seats for Main Hall (10x15 with center aisle at col 8) ──
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
            db.add(Seat(auditorium_id=aud1.id, row_num=r, col_num=c, label=label, seat_type=stype, is_active=active))

    # ── Seats for Innovation Lab (6x10 with aisle at col 5) ──
    for r in range(1, 7):
        for c in range(1, 11):
            if c == 5:
                stype, label, active = "aisle", "", False
            else:
                stype, label, active = "standard", f"{chr(64+r)}{c}", True
            db.add(Seat(auditorium_id=aud2.id, row_num=r, col_num=c, label=label, seat_type=stype, is_active=active))

    # ── Seats for Seminar Hall A (8x10, no aisle) ──
    for r in range(1, 9):
        for c in range(1, 11):
            stype = "vip" if r == 1 else "standard"
            db.add(Seat(auditorium_id=aud3.id, row_num=r, col_num=c, label=f"{chr(64+r)}{c}", seat_type=stype, is_active=True))

    db.commit()
    print("Created 3 auditoriums with seats")

    # ── Lecture Sessions ──
    now = datetime.now(timezone.utc)
    sessions_data = [
        {
            "auditorium_id": aud1.id, "speaker_id": speakers[0].id,
            "title": "The Future of AI Agents", "speaker": "Dr. Sarah Chen",
            "description": "Explore how autonomous AI agents are reshaping software development, from code generation to infrastructure management.",
            "start_time": now + timedelta(days=3, hours=10), "price": 500, "price_vip": 1200, "price_accessible": 400, "status": "published",
        },
        {
            "auditorium_id": aud1.id, "speaker_id": speakers[1].id,
            "title": "WebAssembly Beyond the Browser", "speaker": "James Kowalski",
            "description": "Discover how Wasm is being used for serverless, edge computing, and plugin systems.",
            "start_time": now + timedelta(days=3, hours=11), "price": 500, "price_vip": 1200, "price_accessible": 400, "status": "published",
        },
        {
            "auditorium_id": aud2.id, "speaker_id": speakers[2].id,
            "title": "Hands-on Rust for Systems Programming", "speaker": "Maria Gonzalez",
            "description": "A hands-on session covering Rust fundamentals through building a concurrent file processor.",
            "start_time": now + timedelta(days=5, hours=14), "price": 500, "price_vip": 1000, "price_accessible": 400, "status": "published",
        },
        {
            "auditorium_id": aud3.id, "speaker_id": speakers[3].id,
            "title": "Scaling PostgreSQL to 10 Million Users", "speaker": "Alex Petrov",
            "description": "Real-world strategies for partitioning, connection pooling, and query optimization at scale.",
            "start_time": now + timedelta(days=7, hours=9), "price": 500, "price_vip": 1200, "price_accessible": 400, "status": "published",
        },
        {
            "auditorium_id": aud2.id, "speaker_id": speakers[4].id,
            "title": "Designing for Accessibility", "speaker": "Priya Sharma",
            "description": "Learn WCAG guidelines and practical techniques for building inclusive web experiences.",
            "start_time": now + timedelta(days=7, hours=15), "price": 500, "price_vip": 1000, "price_accessible": 400, "status": "published",
        },
        {
            "auditorium_id": aud1.id, "speaker_id": speakers[5].id,
            "title": "Zero Trust Architecture in Practice", "speaker": "Michael Torres",
            "description": "Implementing zero-trust security patterns in cloud-native applications.",
            "start_time": now + timedelta(days=10, hours=10), "price": 500, "price_vip": 1200, "price_accessible": 400, "status": "draft",
        },
        {
            "auditorium_id": aud3.id, "speaker_id": speakers[6].id,
            "title": "Building India's Payment Infrastructure", "speaker": "Anika Desai",
            "description": "How Razorpay scaled to process billions in payments with reliability and security.",
            "start_time": now + timedelta(days=12, hours=10), "price": 500, "price_vip": 1200, "price_accessible": 400, "status": "published",
        },
        {
            "auditorium_id": aud1.id, "speaker_id": speakers[7].id,
            "title": "Quantum Computing for ML Engineers", "speaker": "Rahul Mehta",
            "description": "Practical introduction to quantum machine learning — what works today and what's coming.",
            "start_time": now + timedelta(days=14, hours=11), "price": 500, "price_vip": 1200, "price_accessible": 400, "status": "published",
        },
        # —— Amal Sajeev: 4 detailed sessions for speaker account testing ——
        {
            "auditorium_id": aud1.id, "speaker_id": speakers[8].id,
            "title": "Building Production-Ready APIs: Design, Security, and Scale",
            "speaker": "Amal Sajeev",
            "description": "A deep dive into designing REST and GraphQL APIs that are secure, versioned, and built to scale. We cover authentication (OAuth2, JWT), rate limiting, idempotency, error contracts, and observability. You'll leave with a concrete checklist and patterns you can apply in your next service.",
            "start_time": now + timedelta(days=2, hours=10), "price": 500, "price_vip": 1200, "price_accessible": 400, "status": "published",
        },
        {
            "auditorium_id": aud2.id, "speaker_id": speakers[8].id,
            "title": "From Monolith to Microservices: A Practical Migration Guide",
            "speaker": "Amal Sajeev",
            "description": "Real-world strategies for incrementally breaking down a monolith without big-bang rewrites. We discuss bounded contexts, strangler fig pattern, shared databases vs events, and how to keep teams unblocked during the transition. Includes lessons from migrations at high-traffic product companies.",
            "start_time": now + timedelta(days=4, hours=14), "price": 500, "price_vip": 1000, "price_accessible": 400, "status": "published",
        },
        {
            "auditorium_id": aud3.id, "speaker_id": speakers[8].id,
            "title": "Clean Code in the Real World: Readability, Tests, and Refactoring",
            "speaker": "Amal Sajeev",
            "description": "Principles from Clean Code and Beyond applied to everyday codebases. We focus on naming, small functions, testability, and safe refactoring techniques. Live refactoring of sample code to show before/after and how to introduce change without breaking production.",
            "start_time": now + timedelta(days=6, hours=9), "price": 500, "price_vip": 1200, "price_accessible": 400, "status": "published",
        },
        {
            "auditorium_id": aud1.id, "speaker_id": speakers[8].id,
            "title": "Developer Experience: Building Tools and Docs That Engineers Love",
            "speaker": "Amal Sajeev",
            "description": "Why great DX leads to faster adoption and fewer support tickets. We cover CLI design, SDK ergonomics, API documentation (OpenAPI, guides, examples), internal platforms, and measuring developer happiness. With practical examples from open-source and in-house tools.",
            "start_time": now + timedelta(days=8, hours=11), "price": 500, "price_vip": 1200, "price_accessible": 400, "status": "published",
        },
    ]

    created_sessions = []
    for s in sessions_data:
        sess = LectureSession(**s)
        db.add(sess)
        db.commit()
        db.refresh(sess)
        created_sessions.append(sess)

    print(f"Created {len(sessions_data)} sessions")

    # ── Agenda Items ──
    agenda_data = [
        (created_sessions[0].id, [
            ("Introduction to AI Agents", "Dr. Sarah Chen", 10),
            ("Autonomous Code Generation", "Dr. Sarah Chen", 20),
            ("Live Demo: Agent-in-the-Loop", "Dr. Sarah Chen", 15),
            ("Q&A Session", None, 10),
        ]),
        (created_sessions[1].id, [
            ("Wasm Fundamentals Refresher", "James Kowalski", 10),
            ("Wasm on the Edge", "James Kowalski", 20),
            ("Building a Wasm Plugin System", "James Kowalski", 15),
        ]),
        (created_sessions[3].id, [
            ("PostgreSQL Internals Overview", "Alex Petrov", 10),
            ("Partitioning Strategies", "Alex Petrov", 15),
            ("Connection Pooling Deep Dive", "Alex Petrov", 15),
            ("Query Optimization Workshop", "Alex Petrov", 20),
        ]),
        (created_sessions[8].id, [
            ("API design principles & versioning", "Amal Sajeev", 20),
            ("Auth, rate limits, idempotency", "Amal Sajeev", 25),
            ("Error contracts & observability", "Amal Sajeev", 20),
            ("Checklist & Q&A", "Amal Sajeev", 25),
        ]),
        (created_sessions[9].id, [
            ("Bounded contexts & migration strategies", "Amal Sajeev", 25),
            ("Strangler fig & incremental extraction", "Amal Sajeev", 25),
            ("Data and events during transition", "Amal Sajeev", 20),
            ("Q&A and war stories", "Amal Sajeev", 20),
        ]),
        (created_sessions[10].id, [
            ("Naming and small functions", "Amal Sajeev", 20),
            ("Testability and dependency injection", "Amal Sajeev", 25),
            ("Live refactoring demo", "Amal Sajeev", 35),
            ("Q&A", "Amal Sajeev", 20),
        ]),
        (created_sessions[11].id, [
            ("Why DX matters: metrics and outcomes", "Amal Sajeev", 15),
            ("CLIs, SDKs, and API docs", "Amal Sajeev", 30),
            ("Internal platforms & measuring happiness", "Amal Sajeev", 25),
            ("Q&A", "Amal Sajeev", 20),
        ]),
    ]
    for sess_id, items in agenda_data:
        for idx, (title, speaker_name, dur) in enumerate(items):
            db.add(AgendaItem(session_id=sess_id, order=idx, title=title, speaker_name=speaker_name, duration_minutes=dur))
    db.commit()
    print("Created agenda items")

    # ── Testimonials ──
    testimonials = [
        Testimonial(student_name="Priya Sharma", college="KSR College of Engineering", quote="TechTrek opened my eyes to quantum computing. The speaker was phenomenal and the venue was buzzing with energy!"),
        Testimonial(student_name="Arjun Mehta", college="Delhi Technological University", quote="The best industry event I've attended as a student. Clear, concise talks that actually help you understand where the industry is heading."),
        Testimonial(student_name="Sneha Patel", college="BITS Pilani", quote="From booking my seat to attending — the whole experience was seamless. Can't wait for the next TechTrek!"),
        Testimonial(student_name="Vikram Singh", college="IIT Delhi", quote="The AI Agents session blew my mind. Real practical insights from someone who builds these systems daily."),
        Testimonial(student_name="Ananya Rao", college="IIIT Bangalore", quote="Finally an event that treats students like professionals. The networking opportunities alone were worth it."),
    ]
    db.add_all(testimonials)
    db.commit()
    print(f"Created {len(testimonials)} testimonials")

    # ── Newsletter Subscribers ──
    subs = [
        NewsletterSubscriber(email="student1@example.com"),
        NewsletterSubscriber(email="student2@example.com"),
        NewsletterSubscriber(email="techfan@example.com"),
    ]
    db.add_all(subs)
    db.commit()
    print(f"Created {len(subs)} newsletter subscribers")

    print("\n--- Seeding complete! ---")
    print("Admin login:    admin / admin123")
    print("User logins:    alice / user123, bob / user123, charlie / user123")
    print("Speaker logins: sarah / speaker123, james / speaker123, maria / speaker123, amalsajeev / speaker123")
    print(f"Sessions:       {len(sessions_data)} (across 3 auditoriums in 3 cities)")
    print(f"Speakers:       {len(speakers)} (4 with linked accounts)")
    print(f"Testimonials:   {len(testimonials)}")
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Seed the TechTrek database.")
    p.add_argument("--force", "-f", action="store_true", help="Clear existing data and re-seed.")
    args = p.parse_args()
    seed(force=args.force)

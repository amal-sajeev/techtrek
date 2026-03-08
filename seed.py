"""Seed script to populate the database with sample data for development."""

import bcrypt
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal, Base, engine
from app.models.user import User
from app.models.auditorium import Auditorium
from app.models.seat import Seat
from app.models.session import LectureSession


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    if db.query(User).count() > 0:
        print("Database already seeded. Skipping.")
        db.close()
        return

    # ── Users ──
    admin_pw = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
    user_pw = bcrypt.hashpw(b"user123", bcrypt.gensalt()).decode()

    admin = User(username="admin", email="admin@techtrek.dev", password_hash=admin_pw, is_admin=True)
    user1 = User(username="alice", email="alice@example.com", password_hash=user_pw)
    user2 = User(username="bob", email="bob@example.com", password_hash=user_pw)

    db.add_all([admin, user1, user2])
    db.commit()
    print(f"Created users: admin (pw: admin123), alice (pw: user123), bob (pw: user123)")

    # ── Auditoriums ──
    aud1 = Auditorium(
        name="Main Hall",
        location="TechTrek HQ, San Francisco",
        description="Our flagship 150-seat auditorium with state-of-the-art AV equipment.",
        total_rows=10,
        total_cols=15,
    )
    aud2 = Auditorium(
        name="Innovation Lab",
        location="Downtown Campus, Austin",
        description="Intimate 60-seat space for hands-on workshops.",
        total_rows=6,
        total_cols=10,
    )
    db.add_all([aud1, aud2])
    db.commit()
    db.refresh(aud1)
    db.refresh(aud2)

    # ── Seats for Main Hall ──
    seats1 = []
    for r in range(1, 11):
        for c in range(1, 16):
            if c == 8:
                seat_type = "aisle"
                label = ""
                active = False
            elif r <= 2:
                seat_type = "vip"
                label = f"{chr(64 + r)}{c}"
                active = True
            elif c == 1 or c == 15:
                seat_type = "accessible"
                label = f"{chr(64 + r)}{c}"
                active = True
            else:
                seat_type = "standard"
                label = f"{chr(64 + r)}{c}"
                active = True
            seats1.append(Seat(
                auditorium_id=aud1.id, row_num=r, col_num=c,
                label=label, seat_type=seat_type, is_active=active,
            ))
    db.add_all(seats1)

    # ── Seats for Innovation Lab ──
    seats2 = []
    for r in range(1, 7):
        for c in range(1, 11):
            if c == 5:
                seat_type = "aisle"
                label = ""
                active = False
            else:
                seat_type = "standard"
                label = f"{chr(64 + r)}{c}"
                active = True
            seats2.append(Seat(
                auditorium_id=aud2.id, row_num=r, col_num=c,
                label=label, seat_type=seat_type, is_active=active,
            ))
    db.add_all(seats2)
    db.commit()

    # ── Lecture Sessions ──
    now = datetime.now(timezone.utc)
    sessions_data = [
        {
            "auditorium_id": aud1.id,
            "title": "The Future of AI Agents",
            "speaker": "Dr. Sarah Chen",
            "description": "Explore how autonomous AI agents are reshaping software development, from code generation to infrastructure management.",
            "start_time": now + timedelta(days=3, hours=10),
            "price": 25.00,
            "status": "published",
        },
        {
            "auditorium_id": aud1.id,
            "title": "WebAssembly Beyond the Browser",
            "speaker": "James Kowalski",
            "description": "Discover how Wasm is being used for serverless, edge computing, and plugin systems in modern applications.",
            "start_time": now + timedelta(days=3, hours=11),
            "price": 20.00,
            "status": "published",
        },
        {
            "auditorium_id": aud2.id,
            "title": "Hands-on Rust for Systems Programming",
            "speaker": "Maria Gonzalez",
            "description": "A hands-on session covering Rust fundamentals through building a concurrent file processor.",
            "start_time": now + timedelta(days=5, hours=14),
            "price": 30.00,
            "status": "published",
        },
        {
            "auditorium_id": aud1.id,
            "title": "Scaling PostgreSQL to 10 Million Users",
            "speaker": "Alex Petrov",
            "description": "Real-world strategies for partitioning, connection pooling, and query optimization at scale.",
            "start_time": now + timedelta(days=7, hours=9),
            "price": 15.00,
            "status": "published",
        },
        {
            "auditorium_id": aud2.id,
            "title": "Designing for Accessibility",
            "speaker": "Priya Sharma",
            "description": "Learn WCAG guidelines and practical techniques for building inclusive web experiences.",
            "start_time": now + timedelta(days=7, hours=15),
            "price": 10.00,
            "status": "published",
        },
        {
            "auditorium_id": aud1.id,
            "title": "Zero Trust Architecture in Practice",
            "speaker": "Michael Torres",
            "description": "Implementing zero-trust security patterns in cloud-native applications.",
            "start_time": now + timedelta(days=10, hours=10),
            "price": 20.00,
            "status": "draft",
        },
    ]

    for s in sessions_data:
        db.add(LectureSession(**s))
    db.commit()

    print(f"Created {len(sessions_data)} sessions across 2 auditoriums.")
    print("Seeding complete!")
    db.close()


if __name__ == "__main__":
    seed()

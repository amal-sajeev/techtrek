#!/usr/bin/env python
"""seed_demo.py – Bulk-generate realistic data for analytics dashboards.

Run AFTER the base seed:
    python seed.py --force
    python seed_demo.py

Generates ~120 demo users, hundreds of bookings, feedback, polls, session
ratings, coupon usage, add-on sales, and waitlist entries across both events
so the analytics dashboard looks production-quality.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, time as time_cls

import bcrypt
from sqlalchemy import func, text

from app.database import SessionLocal
from app.models.user import User
from app.models.event import Event
from app.models.booking import Booking
from app.models.seat import Seat
from app.models.seat_type import SeatType
from app.models.coupon import Coupon
from app.models.waitlist import Waitlist
from app.models.feedback import Feedback
from app.models.session_feedback import SessionFeedback
from app.models.feedback_template import FeedbackResponse
from app.models.event_session import EventSession
from app.models.event_addon import EventAddOn, BookingAddOn
from app.models.poll import Poll, PollOption, PollVote
from app.models.session import Session as SessionModel
from app.crypto import hash_lookup
from app.config import settings

random.seed(2026)

# ═══════════════════════════════════════════════════════════════════════
#  Data pools
# ═══════════════════════════════════════════════════════════════════════

FIRST_M = [
    "Aarav", "Aditya", "Akash", "Amit", "Ankit", "Arjun", "Aryan",
    "Deepak", "Dev", "Dhruv", "Gaurav", "Harsh", "Ishaan", "Jay",
    "Karan", "Kartik", "Kunal", "Manish", "Mohan", "Nikhil",
    "Om", "Pranav", "Rahul", "Raj", "Ravi", "Rohit", "Sahil",
    "Sanjay", "Shubham", "Siddharth", "Suresh", "Tanmay",
    "Varun", "Vijay", "Vikram", "Yash",
]
FIRST_F = [
    "Aditi", "Ananya", "Anjali", "Bhavna", "Diya", "Fatima",
    "Ishita", "Kavya", "Kriti", "Meera", "Neha", "Nisha",
    "Pooja", "Priya", "Radhika", "Riya", "Sakshi", "Shreya",
    "Simran", "Sneha", "Sonal", "Swati", "Tanvi", "Tanya",
    "Trisha", "Vaishnavi", "Vidya", "Zara",
]
LAST = [
    "Agarwal", "Banerjee", "Bhatt", "Chauhan", "Chopra", "Das",
    "Desai", "Dubey", "Garg", "Gupta", "Iyer", "Jain", "Joshi",
    "Kapoor", "Khan", "Kumar", "Malhotra", "Menon", "Mishra",
    "Nair", "Pandey", "Patel", "Pillai", "Rao", "Reddy", "Shah",
    "Sharma", "Singh", "Sinha", "Thakur", "Verma", "Yadav",
]
COLLEGES = [
    "KSR College of Engineering", "Anna University",
    "Delhi Technological University", "IIT Delhi",
    "IIIT Bangalore", "BITS Pilani", "IIT Bombay",
    "NIT Trichy", "VIT Vellore", "SRM Chennai",
    "RVCE Bangalore", "MIT Manipal", "PES University",
    "KIIT Bhubaneswar", "Amity University Noida", "LPU Jalandhar",
    "Thapar University", "NIT Surathkal", "IIT Madras",
    "IIIT Hyderabad", "Manipal Institute of Technology",
    "COEP Pune", "NIT Warangal", "IIT Kharagpur",
    "Jadavpur University", "NSUT Delhi",
]
DISCIPLINES = [
    "CSE", "IT", "ECE", "EEE", "Mechanical",
    "AI/ML", "Data Science", "Cybersecurity",
]
FEEDBACK_COMMENTS = [
    "Absolutely fantastic event! The speakers were incredibly knowledgeable and engaging.",
    "One of the best tech conferences I've attended as a student. Highly recommend.",
    "Great content, well-organized sessions, and an excellent venue.",
    "The AI session was mind-blowing — really opened my eyes to future possibilities.",
    "Loved the interactive Q&A segments between sessions.",
    "Would have liked more hands-on workshops, but overall a superb experience.",
    "The networking opportunities were invaluable. Met so many like-minded peers.",
    "Speakers were engaging and the topics were very relevant to current industry trends.",
    "Exceeded my expectations in every way. The production quality was top-notch.",
    "Great value for money. Will definitely attend again next year.",
    "The cybersecurity demo was incredibly eye-opening and practical.",
    "I wished some sessions were longer — they were that good!",
    "Perfect mix of theory and practical real-world insights.",
    "The quantum computing session made complex topics genuinely accessible.",
    "An amazing event that every CS student should experience at least once.",
    "Good event overall but the venue was a bit cramped during peak sessions.",
    "The career guidance session was exactly what I needed at this stage.",
    "Well curated content — each session built on the previous one beautifully.",
    "The speakers' deep industry experience really showed in their presentations.",
    "Inspiring talks that motivated me to start building my own AI side-project.",
    "Time management between sessions could be improved slightly.",
    "The portfolio building tips were practical, actionable, and immediately useful.",
    "Excellent exposure to cutting-edge technology trends shaping the industry.",
    "Really appreciated the focus on ethical AI and responsible technology development.",
    "Great atmosphere, wonderful people, and genuinely impactful content.",
    "The live CTF challenge was the highlight of my entire semester!",
    "Would recommend this to every engineering student I know without hesitation.",
    "Sessions on the AI job market were very informative and refreshingly realistic.",
    "The add-on career guidance forum was worth every rupee — so much clarity gained.",
    "Some speakers could slow down a bit, but the content quality was stellar.",
    "A perfect weekend spent learning directly from industry experts.",
    "The honest insights on GenAI failures were refreshingly candid and useful.",
    "Well-balanced agenda with sensible breaks — didn't feel exhausting at all.",
    "Hope to see more hackathon-style hands-on activities at the next event.",
    "Smooth registration, great app, and flawless event logistics. Impressed!",
]
POLL_DEFS_E1 = [
    {
        "q": "How confident do you feel about conducting a basic penetration test after this bootcamp?",
        "type": "rating",
    },
    {
        "q": "Which vulnerability type did you find most interesting to exploit?",
        "type": "multiple_choice",
        "opts": ["SQL Injection", "Cross-Site Scripting", "SSRF", "Broken Auth", "Privilege Escalation"],
    },
    {
        "q": "Should we extend the CTF challenge to a full day next time?",
        "type": "yes_no",
    },
]
POLL_DEFS_E2 = [
    {
        "q": "Which session topic was most valuable to you today?",
        "type": "multiple_choice",
        "opts": ["AI Ethics & Policy", "AI Agents & Automation", "Career in AI", "Quantum Computing", "GenAI in Practice"],
    },
    {
        "q": "How would you rate the overall event experience?",
        "type": "rating",
    },
    {
        "q": "Would you recommend this event to a friend?",
        "type": "yes_no",
    },
    {
        "q": "What topic should we cover in depth at our next summit?",
        "type": "text",
    },
    {
        "q": "How well did the event prepare you for AI-driven career changes?",
        "type": "multiple_choice",
        "opts": ["Extremely well", "Very well", "Somewhat", "Not much", "Not at all"],
    },
]
TEXT_ANSWERS = [
    "More hands-on workshops with real industry tools",
    "Advanced machine learning techniques and papers",
    "Cloud computing and DevOps practices",
    "Blockchain and Web3 real-world applications",
    "Mobile app development with on-device AI",
    "Natural Language Processing deep dive",
    "Computer vision and image recognition projects",
    "Robotics, drones, and physical automation",
    "Data engineering and MLOps pipelines",
    "Startup building and tech entrepreneurship",
    "Open source contribution masterclass",
    "Edge computing and IoT at scale",
    "Full-stack development best practices",
    "System design for tech interviews",
    "Research methodology and publishing in CS",
]


# ═══════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════

_key = settings.field_encryption_key


def _pw(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _ref():
    return f"TT-{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}"


def _ticket():
    return uuid.uuid4().hex[:16].upper()


def _available_seats(db, event_id, aud_id):
    taken = set(
        r[0] for r in db.query(Booking.seat_id).filter(
            Booking.event_id == event_id,
            Booking.payment_status.in_(["hold", "paid"]),
        ).all()
    )
    seats = (
        db.query(Seat)
        .filter(Seat.auditorium_id == aud_id, Seat.is_active == True, Seat.seat_type != "aisle")
        .order_by(Seat.row_num, Seat.col_num)
        .all()
    )
    return [s for s in seats if s.id not in taken]


# ═══════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    print()
    print("=" * 52)
    print("    TechTrek Demo Seed — Analytics Data")
    print("=" * 52)
    print()

    db = SessionLocal()

    # ── Idempotency check ─────────────────────────────────────────
    demo_hash = hash_lookup("demo1", _key)
    if db.query(User).filter(User.username_hash == demo_hash).first():
        print("  Demo data already exists — skipping.")
        print("  (Run `python seed.py --force` then `python seed_demo.py` to re-generate)")
        db.close()
        return

    # ── Find events ───────────────────────────────────────────────
    events = db.query(Event).order_by(Event.id).all()
    if len(events) < 2:
        print("  ERROR: Need at least 2 events. Run seed.py first.")
        db.close()
        return

    ev1, ev2 = events[0], events[1]
    print(f"  Event 1: {ev1.name} (id={ev1.id})")
    print(f"  Event 2: {ev2.name} (id={ev2.id})")
    print()

    admin_hash = hash_lookup("admin", _key)
    admin = db.query(User).filter(User.username_hash == admin_hash).first()
    admin_id = admin.id if admin else 1

    # ══════════════════════════════════════════════════════════════
    #  1. Create 120 demo users
    # ══════════════════════════════════════════════════════════════
    print("[1/11] Creating demo users ...")
    firsts = FIRST_M + FIRST_F
    random.shuffle(firsts)
    lasts = list(LAST)
    random.shuffle(lasts)
    password = _pw("demo123")

    demo_users = []
    seen = set()
    for first in firsts:
        for last in lasts:
            if len(demo_users) >= 120:
                break
            if (first, last) in seen:
                continue
            seen.add((first, last))

            idx = len(demo_users) + 1
            uname = f"demo{idx}"
            email = f"{first.lower()}.{last.lower()}{idx}@techtrek.dev"
            college = COLLEGES[idx % len(COLLEGES)]
            disc = DISCIPLINES[idx % len(DISCIPLINES)]
            year = random.choices([1, 2, 3, 4], weights=[10, 25, 40, 25], k=1)[0]

            u = User(
                username=uname, email=email, full_name=f"{first} {last}",
                password_hash=password, college=college, discipline=disc,
                domain="", year_of_study=year,
            )
            u.email_hash = hash_lookup(email, _key)
            u.username_hash = hash_lookup(uname, _key)
            demo_users.append(u)
        if len(demo_users) >= 120:
            break

    db.add_all(demo_users)
    db.commit()
    for u in demo_users:
        db.refresh(u)
    print(f"  Created {len(demo_users)} demo users")

    # ══════════════════════════════════════════════════════════════
    #  2. Diversify seat types in Main Hall (event 2)
    # ══════════════════════════════════════════════════════════════
    print("[2/11] Diversifying seat types ...")
    if ev2.auditorium_id:
        premium_st = db.query(SeatType).filter(SeatType.name == "Premium").first()
        balcony_st = db.query(SeatType).filter(SeatType.name == "Balcony").first()
        premium_key = f"custom_{premium_st.id}" if premium_st else "standard"
        balcony_key = f"custom_{balcony_st.id}" if balcony_st else "standard"
        db.execute(text(
            "UPDATE seats SET seat_type = :stype "
            "WHERE auditorium_id = :aid AND row_num <= 2 AND seat_type NOT IN ('aisle')"
        ), {"aid": ev2.auditorium_id, "stype": premium_key})
        db.execute(text(
            "UPDATE seats SET seat_type = :stype "
            "WHERE auditorium_id = :aid AND row_num IN (3,4) AND seat_type NOT IN ('aisle')"
        ), {"aid": ev2.auditorium_id, "stype": balcony_key})
        db.commit()
        print(f"  Rows 1-2 = {premium_key}, Rows 3-4 = {balcony_key}, rest = Standard")

    # ══════════════════════════════════════════════════════════════
    #  3. Create extra coupons
    # ══════════════════════════════════════════════════════════════
    print("[3/11] Creating coupons ...")
    new_coupons = [
        Coupon(code="EARLYBIRD20", discount_pct=20, max_uses=30,
               event_id=ev2.id, is_active=True, used_count=0),
        Coupon(code="STUDENT50", discount_amount=50, max_uses=100,
               event_id=ev2.id, is_active=True, used_count=0),
        Coupon(code="GROUPDEAL15", discount_pct=15, max_uses=40,
               event_id=ev2.id, is_active=True, used_count=0),
        Coupon(code="CYBER100", discount_pct=100, max_uses=20,
               event_id=ev1.id, is_active=True, used_count=0),
    ]
    db.add_all(new_coupons)
    db.commit()
    for c in new_coupons:
        db.refresh(c)

    all_coupons_e2 = (
        db.query(Coupon).filter(Coupon.event_id == ev2.id).all()
    )
    print(f"  Created {len(new_coupons)} coupons ({len(all_coupons_e2)} total for event 2)")

    # ══════════════════════════════════════════════════════════════
    #  4. Bookings — Event 1 (past, free, 42 seats)
    # ══════════════════════════════════════════════════════════════
    print("[4/11] Creating bookings — Event 1 ...")
    avail_e1 = _available_seats(db, ev1.id, ev1.auditorium_id)
    n_e1 = min(len(avail_e1), 42)
    users_e1 = random.sample(demo_users, n_e1)

    e1_date = ev1.start_date or (datetime.utcnow().date() - timedelta(days=1))
    e1_book_start = datetime.combine(e1_date - timedelta(days=14), time_cls(8, 0))

    bookings_e1 = []
    for i, (user, seat) in enumerate(zip(users_e1, avail_e1[:n_e1])):
        day = int(i / n_e1 * 14)
        booked_at = e1_book_start + timedelta(
            days=day, hours=random.randint(8, 22), minutes=random.randint(0, 59),
        )
        bg = uuid.uuid4().hex
        bookings_e1.append(Booking(
            user_id=user.id, event_id=ev1.id, seat_id=seat.id,
            payment_status="paid", booking_ref=_ref(), ticket_id=_ticket(),
            qr_code_data=uuid.uuid4().hex, booking_group=bg,
            amount_paid=0, booked_at=booked_at, is_shared_ticket=False,
            checked_in=True,
            checked_in_at=datetime.combine(e1_date, time_cls(9 + random.randint(0, 1), random.randint(0, 59))),
        ))

    db.add_all(bookings_e1)
    db.commit()
    print(f"  {len(bookings_e1)} paid bookings (all checked in)")

    # ══════════════════════════════════════════════════════════════
    #  5. Bookings — Event 2 (paid, varied seat types)
    # ══════════════════════════════════════════════════════════════
    print("[5/11] Creating bookings — Event 2 ...")
    avail_e2 = _available_seats(db, ev2.id, ev2.auditorium_id)
    random.shuffle(avail_e2)

    n_paid = min(len(avail_e2), 100)
    n_cancel = 12
    n_hold = 5
    total_e2 = n_paid + n_cancel + n_hold

    remaining = [u for u in demo_users if u not in set(users_e1)]
    users_e2_pool = users_e1[:30] + remaining
    random.shuffle(users_e2_pool)
    users_e2_pool = users_e2_pool[:total_e2]

    e2_date = ev2.start_date or (datetime.utcnow().date() + timedelta(days=10))
    e2_book_origin = datetime.combine(e2_date - timedelta(days=21), time_cls(0, 0))

    seat_prices = {"standard": 500, premium_key: 800, balcony_key: 600}
    coupon_used = {c.id: 0 for c in all_coupons_e2}

    bookings_e2 = []
    for idx in range(min(len(users_e2_pool), len(avail_e2[:total_e2]))):
        user = users_e2_pool[idx]
        seat = avail_e2[idx]

        # Realistic booking curve: most bookings in the final week
        r = random.random()
        day = int(21 * (r ** 0.45))
        booked_at = e2_book_origin + timedelta(
            days=day, hours=random.randint(7, 23), minutes=random.randint(0, 59),
        )

        base_price = seat_prices.get(seat.seat_type, 500)
        amount = base_price
        coupon_id = None

        if random.random() < 0.28 and all_coupons_e2:
            coupon = random.choice(all_coupons_e2)
            if not coupon.max_uses or coupon_used[coupon.id] < coupon.max_uses:
                coupon_id = coupon.id
                if coupon.discount_pct:
                    amount = round(base_price * (1 - coupon.discount_pct / 100))
                elif coupon.discount_amount:
                    amount = max(0, base_price - int(coupon.discount_amount or 0))
                coupon_used[coupon.id] += 1

        if idx < n_paid:
            status = "paid"
        elif idx < n_paid + n_cancel:
            status = "cancelled"
        else:
            status = "hold"

        bg = uuid.uuid4().hex
        bookings_e2.append(Booking(
            user_id=user.id, event_id=ev2.id, seat_id=seat.id,
            payment_status=status, booking_ref=_ref(), ticket_id=_ticket(),
            qr_code_data=uuid.uuid4().hex, booking_group=bg,
            amount_paid=amount if status == "paid" else 0,
            refund_amount=float(base_price) if status == "cancelled" else None,
            coupon_id=coupon_id, booked_at=booked_at, is_shared_ticket=False,
        ))

    db.add_all(bookings_e2)
    db.commit()

    for c in all_coupons_e2:
        c.used_count = (c.used_count or 0) + coupon_used.get(c.id, 0)
    db.commit()

    paid_e2 = [b for b in bookings_e2 if b.payment_status == "paid"]
    canc_e2 = [b for b in bookings_e2 if b.payment_status == "cancelled"]
    hold_e2 = [b for b in bookings_e2 if b.payment_status == "hold"]
    print(f"  {len(paid_e2)} paid, {len(canc_e2)} cancelled, {len(hold_e2)} on hold")

    # ══════════════════════════════════════════════════════════════
    #  6. Check-ins for Event 2
    # ══════════════════════════════════════════════════════════════
    print("[6/11] Creating check-ins ...")
    n_checkin = int(len(paid_e2) * 0.72)
    for b in random.sample(paid_e2, n_checkin):
        b.checked_in = True
        b.checked_in_at = datetime.combine(
            e2_date, time_cls(9, random.randint(0, 59)),
        )
    db.commit()
    print(f"  {n_checkin}/{len(paid_e2)} checked in ({round(n_checkin/len(paid_e2)*100)}%)")

    # ══════════════════════════════════════════════════════════════
    #  7. Feedback (legacy + FeedbackResponse)
    # ══════════════════════════════════════════════════════════════
    print("[7/11] Creating feedback ...")
    fb_total = 0

    for ev, ev_bookings, n_legacy, n_resp in [
        (ev1, bookings_e1, 30, 20),
        (ev2, paid_e2, 18, 25),
    ]:
        uids = list({b.user_id for b in ev_bookings})
        random.shuffle(uids)
        ev_date = ev.start_date or datetime.utcnow().date()

        for uid in uids[:n_legacy]:
            if db.query(Feedback).filter(
                Feedback.user_id == uid, Feedback.event_id == ev.id
            ).first():
                continue
            rating = random.choices([3, 4, 4, 5, 5, 5], k=1)[0]
            db.add(Feedback(
                user_id=uid, event_id=ev.id, rating=rating,
                comment=random.choice(FEEDBACK_COMMENTS),
                allow_public=random.random() > 0.2,
                is_featured=random.random() > 0.7,
                submitted_at=datetime.combine(ev_date, time_cls(17, random.randint(0, 59))),
            ))
            fb_total += 1

        for uid in uids[n_legacy : n_legacy + n_resp]:
            if db.query(FeedbackResponse).filter(
                FeedbackResponse.user_id == uid, FeedbackResponse.event_id == ev.id
            ).first():
                continue
            rating = random.choices([3, 3, 4, 4, 4, 5, 5, 5, 5], k=1)[0]
            comment = random.choice(FEEDBACK_COMMENTS) if random.random() > 0.25 else ""
            db.add(FeedbackResponse(
                user_id=uid, event_id=ev.id,
                overall_rating=rating, comment=comment,
            ))
            fb_total += 1

    db.commit()
    print(f"  {fb_total} feedback entries across both events")

    # ══════════════════════════════════════════════════════════════
    #  8. Session feedback (per-session star ratings)
    # ══════════════════════════════════════════════════════════════
    print("[8/11] Creating session feedback ...")
    sf_count = 0
    for ev, ev_bookings in [(ev1, bookings_e1), (ev2, paid_e2)]:
        ev_sessions = db.query(EventSession).filter(EventSession.event_id == ev.id).all()
        uids = list({b.user_id for b in ev_bookings})

        for es in ev_sessions:
            n_raters = min(len(uids), random.randint(20, 38))
            for uid in random.sample(uids, n_raters):
                if db.query(SessionFeedback).filter(
                    SessionFeedback.user_id == uid,
                    SessionFeedback.session_id == es.session_id,
                ).first():
                    continue
                rating = random.choices([3, 3, 4, 4, 4, 5, 5, 5], k=1)[0]
                db.add(SessionFeedback(
                    user_id=uid, session_id=es.session_id,
                    event_id=ev.id, rating=rating,
                ))
                sf_count += 1

    db.commit()
    print(f"  {sf_count} session ratings")

    # ══════════════════════════════════════════════════════════════
    #  9. Polls and votes
    # ══════════════════════════════════════════════════════════════
    print("[9/11] Creating polls and votes ...")
    poll_count = 0
    vote_count = 0

    for ev, poll_defs, ev_bookings in [
        (ev1, POLL_DEFS_E1, bookings_e1),
        (ev2, POLL_DEFS_E2, paid_e2),
    ]:
        ev_sessions = db.query(EventSession).filter(
            EventSession.event_id == ev.id
        ).all()
        if not ev_sessions:
            continue

        uids = list({b.user_id for b in ev_bookings})

        for pi, pd in enumerate(poll_defs):
            target_es = ev_sessions[pi % len(ev_sessions)]

            poll = Poll(
                session_id=target_es.session_id, event_id=ev.id,
                question=pd["q"], poll_type=pd["type"],
                is_active=False, created_by=admin_id,
                closed_at=datetime.utcnow() - timedelta(hours=random.randint(1, 48)),
            )
            db.add(poll)
            db.flush()
            poll_count += 1

            n_voters = min(len(uids), random.randint(28, 42))
            voters = random.sample(uids, n_voters)

            if pd["type"] == "multiple_choice":
                options = []
                for oi, otext in enumerate(pd["opts"]):
                    po = PollOption(poll_id=poll.id, option_text=otext, order=oi)
                    db.add(po)
                    options.append(po)
                db.flush()

                weights = [random.randint(2, 10) for _ in options]
                for uid in voters:
                    chosen = random.choices(options, weights=weights, k=1)[0]
                    db.add(PollVote(poll_id=poll.id, option_id=chosen.id, user_id=uid))
                    vote_count += 1

            elif pd["type"] == "yes_no":
                opt_y = PollOption(poll_id=poll.id, option_text="Yes", order=0)
                opt_n = PollOption(poll_id=poll.id, option_text="No", order=1)
                db.add_all([opt_y, opt_n])
                db.flush()

                for uid in voters:
                    chosen = random.choices([opt_y, opt_n], weights=[72, 28], k=1)[0]
                    db.add(PollVote(poll_id=poll.id, option_id=chosen.id, user_id=uid))
                    vote_count += 1

            elif pd["type"] == "rating":
                for uid in voters:
                    rv = random.choices([3, 4, 4, 4, 5, 5, 5], k=1)[0]
                    db.add(PollVote(poll_id=poll.id, user_id=uid, rating_value=rv))
                    vote_count += 1

            elif pd["type"] == "text":
                for uid in voters:
                    db.add(PollVote(
                        poll_id=poll.id, user_id=uid,
                        text_answer=random.choice(TEXT_ANSWERS),
                    ))
                    vote_count += 1

    db.commit()
    print(f"  {poll_count} polls, {vote_count} votes")

    # ══════════════════════════════════════════════════════════════
    #  10. Add-on purchases & waitlist
    # ══════════════════════════════════════════════════════════════
    print("[10/11] Add-on purchases & waitlist ...")

    addons_e2 = db.query(EventAddOn).filter(EventAddOn.event_id == ev2.id).all()
    addon_count = 0
    if addons_e2:
        buyers = random.sample(paid_e2, int(len(paid_e2) * 0.32))
        for b in buyers:
            addon = random.choice(addons_e2)
            db.add(BookingAddOn(
                booking_group=b.booking_group,
                addon_id=addon.id,
                quantity=random.choices([1, 1, 1, 2], k=1)[0],
            ))
            addon_count += 1

    booked_ids_e2 = {b.user_id for b in bookings_e2}
    wl_pool = [u for u in demo_users if u.id not in booked_ids_e2]
    wl_e2 = min(len(wl_pool), 18)
    for u in wl_pool[:wl_e2]:
        db.add(Waitlist(
            user_id=u.id, event_id=ev2.id,
            joined_at=datetime.utcnow() - timedelta(days=random.randint(0, 10)),
        ))

    booked_ids_e1 = {b.user_id for b in bookings_e1}
    wl_pool_e1 = [u for u in demo_users if u.id not in booked_ids_e1]
    wl_e1 = min(len(wl_pool_e1), 8)
    for u in wl_pool_e1[:wl_e1]:
        db.add(Waitlist(
            user_id=u.id, event_id=ev1.id,
            joined_at=datetime.combine(
                e1_date - timedelta(days=random.randint(1, 5)), time_cls(12, 0)
            ),
        ))

    db.commit()
    print(f"  {addon_count} add-on purchases")
    print(f"  {wl_e2} waitlist (event 2) + {wl_e1} waitlist (event 1)")

    # ══════════════════════════════════════════════════════════════
    #  11. Sold-out event with waitlist entries (waitlist demo)
    # ══════════════════════════════════════════════════════════════
    print("[11/11] Creating sold-out event for waitlist demo ...")
    from app.models.auditorium import Auditorium
    from app.models.speaker import Speaker

    micro_hall = db.query(Auditorium).filter(Auditorium.name == "Micro Hall").first()
    ev3_name = "TechTrek Exclusive AI Masterclass 2026"
    ev3 = None
    wl_e3_count = 0
    n_e3 = 0

    if micro_hall:
        sarah_speaker = db.query(Speaker).filter(Speaker.name == "Dr. Sarah Chen").first()

        ev3 = Event(
            name=ev3_name,
            description=(
                "An ultra-exclusive, hands-on AI masterclass limited to just 9 participants. "
                "Work directly with Dr. Sarah Chen on building and deploying a real AI agent "
                "in a single intensive session. Due to the intimate format, seats sell out "
                "instantly \u2014 join the waitlist to be notified if a spot opens up."
            ),
            banner_url="https://images.unsplash.com/photo-1620712943543-bcc4688e7485?w=1200&h=400&fit=crop",
            college_id=micro_hall.college_id,
            auditorium_id=micro_hall.id,
            start_date=(datetime.utcnow() + timedelta(days=21)).date(),
            end_date=(datetime.utcnow() + timedelta(days=21)).date(),
            price=200,
            status="published",
            cert_title="Certificate of Completion",
            cert_subtitle="TechTrek Exclusive AI Masterclass 2026",
            cert_footer="Issued by TechTrek Pvt Ltd",
        )
        db.add(ev3)
        db.flush()

        sess3 = SessionModel(
            title="Building & Deploying Your First AI Agent",
            speaker_id=sarah_speaker.id if sarah_speaker else None,
            speaker_name="Dr. Sarah Chen",
            description=(
                "A hands-on deep-dive into building an AI agent from scratch \u2014 from "
                "prompt engineering and tool integration to deployment and monitoring. "
                "Every participant walks away with a working agent they built themselves."
            ),
            duration_minutes=120,
        )
        db.add(sess3)
        db.flush()

        from app.models.event_session import EventSession as ES3
        db.add(ES3(
            event_id=ev3.id, session_id=sess3.id, order=0,
            start_time=datetime.combine(ev3.start_date, time_cls(10, 0)),
            speaker_id=sarah_speaker.id if sarah_speaker else None,
            speaker_name="Dr. Sarah Chen",
        ))
        db.flush()

        avail_e3 = _available_seats(db, ev3.id, micro_hall.id)
        n_e3 = len(avail_e3)
        users_e3 = demo_users[:n_e3]
        e3_book_start = datetime.combine(
            ev3.start_date - timedelta(days=7), time_cls(8, 0),
        )

        for i, (user, seat) in enumerate(zip(users_e3, avail_e3)):
            booked_at = e3_book_start + timedelta(
                days=int(i / max(n_e3, 1) * 5),
                hours=random.randint(8, 20),
                minutes=random.randint(0, 59),
            )
            db.add(Booking(
                user_id=user.id, event_id=ev3.id, seat_id=seat.id,
                payment_status="paid", booking_ref=_ref(), ticket_id=_ticket(),
                qr_code_data=uuid.uuid4().hex, booking_group=uuid.uuid4().hex,
                amount_paid=200, booked_at=booked_at, is_shared_ticket=False,
            ))
        db.flush()

        booked_ids_e3 = {u.id for u in users_e3}
        wl_pool_e3 = [u for u in demo_users if u.id not in booked_ids_e3]
        wl_e3_demo = min(len(wl_pool_e3), 12)
        for u in wl_pool_e3[:wl_e3_demo]:
            db.add(Waitlist(
                user_id=u.id, event_id=ev3.id,
                joined_at=datetime.utcnow() - timedelta(days=random.randint(0, 5)),
            ))
        wl_e3_count = wl_e3_demo

        for uname in ["alice", "charlie", "diana"]:
            u_hash = hash_lookup(uname, _key)
            u_obj = db.query(User).filter(User.username_hash == u_hash).first()
            if u_obj and u_obj.id not in booked_ids_e3:
                existing_wl = db.query(Waitlist).filter(
                    Waitlist.user_id == u_obj.id, Waitlist.event_id == ev3.id,
                ).first()
                if not existing_wl:
                    db.add(Waitlist(
                        user_id=u_obj.id, event_id=ev3.id,
                        joined_at=datetime.utcnow() - timedelta(days=random.randint(1, 3)),
                    ))
                    wl_e3_count += 1

        db.commit()
        print(f"  Created '{ev3.name}' in Micro Hall ({n_e3} seats, ALL booked)")
        print(f"  {wl_e3_count} users on the waitlist")
        print(f"  alice, charlie, diana are on the waitlist (login: user123)")
    else:
        print("  Micro Hall not found — skipping sold-out event")

    # ══════════════════════════════════════════════════════════════
    #  Summary
    # ══════════════════════════════════════════════════════════════
    total_paid_e1 = db.query(Booking).filter(
        Booking.event_id == ev1.id, Booking.payment_status == "paid",
        Booking.is_shared_ticket == False,
    ).count()
    total_paid_e2 = db.query(Booking).filter(
        Booking.event_id == ev2.id, Booking.payment_status == "paid",
        Booking.is_shared_ticket == False,
    ).count()
    revenue_e2 = float(db.query(func.coalesce(func.sum(Booking.amount_paid), 0)).filter(
        Booking.event_id == ev2.id, Booking.payment_status == "paid",
        Booking.is_shared_ticket == False,
    ).scalar() or 0)
    total_fb = (
        db.query(Feedback).count()
        + db.query(FeedbackResponse).count()
    )
    total_polls = db.query(Poll).count()
    total_votes = db.query(PollVote).count()

    print()
    print("=" * 52)
    print("    DEMO SEED COMPLETE")
    print("=" * 52)
    w = 24
    print()
    print(f"  {'Users (total)':<{w}} {db.query(User).count()}")
    print(f"  {'Event 1 bookings':<{w}} {total_paid_e1} paid")
    print(f"  {'Event 2 bookings':<{w}} {total_paid_e2} paid + {len(canc_e2)} cancelled")
    print(f"  {'Event 2 revenue':<{w}} Rs.{revenue_e2:,.0f}")
    print(f"  {'Feedback entries':<{w}} {total_fb}")
    print(f"  {'Session ratings':<{w}} {sf_count}")
    print(f"  {'Polls':<{w}} {total_polls}")
    print(f"  {'Poll votes':<{w}} {total_votes}")
    print(f"  {'Add-on purchases':<{w}} {addon_count}")
    print(f"  {'Waitlist entries':<{w}} {wl_e2 + wl_e1 + wl_e3_count}")
    if ev3:
        print(f"  {'Sold-out event':<{w}} {ev3.name} ({n_e3}/{n_e3} booked)")
    print()
    print("  Dashboard URLs:")
    print(f"    Event 1: /admin/event-management/{ev1.id}/report")
    print(f"    Event 2: /admin/event-management/{ev2.id}/report")
    if ev3:
        print(f"    Event 3 (sold out): /events/{ev3.id}")
    print()
    print("  Waitlist demo:")
    print("    Log in as alice / user123 -> visit the sold-out event -> see 'On Waitlist'")
    print("    Log out -> visit the sold-out event -> see 'Log in to Join Waitlist'")
    print("    Admin: /admin/waitlist -> see all waitlist entries with event filters")
    print()
    print("  All demo users login with password: demo123")
    print()

    db.close()


if __name__ == "__main__":
    main()

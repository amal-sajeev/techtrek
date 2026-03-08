# TechTrek — Lecture Booking Platform

A web application for booking seats at tech lecture programs. Features interactive movie-theatre-style seat selection, waitlisting, and an admin panel for managing auditoriums, sessions, and bookings.

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Seed the database (optional)

```bash
python seed.py
```

This creates sample users, auditoriums with seat layouts, and upcoming sessions.

**Default accounts:**
| Username | Email | Password | Role |
|----------|-------|----------|------|
| admin | admin@techtrek.dev | admin123 | Admin |
| alice | alice@example.com | user123 | User |
| bob | bob@example.com | user123 | User |

### 3. Run the server

```bash
uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

## Features

### Public
- Browse upcoming lecture sessions with availability indicators
- View session details (speaker, venue, time, price)
- Interactive seat selection with a visual auditorium map
- Mock checkout and booking confirmation with reference codes
- Personal booking history

### Waitlist
- Join the waitlist when a session is sold out
- Admin can grant priority booking access to waitlisted users for new sessions
- Priority users get an exclusive booking window before general availability

### Admin Panel (`/admin`)
- Dashboard with stats (users, bookings, revenue, upcoming sessions)
- Auditorium management with a visual seat layout designer
- Session management (create, edit, publish, cancel)
- Booking management (view, cancel, refund)
- Waitlist management with priority granting
- User management with admin role toggling

### UI/UX
- Light and dark theme with toggle (light is default)
- Fully responsive: mobile, tablet, and desktop
- Theme preference persisted in localStorage

## Configuration

Settings are loaded from `.env`:

```
DATABASE_URL=sqlite:///./techtrak.db
SECRET_KEY=your-secret-key
DEBUG=true
```

For PostgreSQL, change `DATABASE_URL`:

```
DATABASE_URL=postgresql://user:pass@localhost:5432/techtrek
```

And add `psycopg2-binary` to your dependencies:

```bash
pip install psycopg2-binary
```

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy, Jinja2
- **Frontend**: HTML/CSS/JS (no frameworks)
- **Database**: SQLite (development) / PostgreSQL (production)
- **Auth**: Session-based with bcrypt password hashing

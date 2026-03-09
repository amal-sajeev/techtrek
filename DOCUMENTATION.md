# TechTrek Documentation

> A full-stack lecture and event booking platform for tech conferences, built with FastAPI, SQLAlchemy, and Jinja2.

TechTrek enables universities and conference organizers to publish lecture sessions, manage auditorium seating layouts, and let students book seats with a real-time hold-and-pay flow. Attendees receive QR-coded tickets that supervisors scan at the door for check-in. An admin panel provides complete control over cities, colleges, auditoriums, speakers, sessions, bookings, waitlists, and user roles.

---

## Table of Contents

- [At a Glance](#at-a-glance)
- [Tech Stack](#tech-stack)
- [Architecture Diagrams](#architecture-diagrams)
  - [System Architecture](#system-architecture)
  - [Request Lifecycle](#request-lifecycle)
  - [User Flow](#user-flow)
  - [Booking State Machine](#booking-state-machine)
  - [Database Entity Relationships](#database-entity-relationships)
  - [Template Hierarchy](#template-hierarchy)
- [Features Overview](#features-overview)
- [Backend Architecture](#backend-architecture)
- [Database Schema](#database-schema)
- [API Endpoints Reference](#api-endpoints-reference)
- [Frontend Architecture](#frontend-architecture)
- [Getting Started](#getting-started)

---

## At a Glance

| Aspect | Detail |
|---|---|
| **Purpose** | Lecture/event booking platform for tech conferences and campus events |
| **Users** | Students (attendees), Supervisors (check-in staff), Admins (organizers) |
| **Core Flow** | Browse sessions &#8594; Select seats &#8594; Hold &#8594; Pay &#8594; Receive QR ticket |
| **Admin Capabilities** | Manage cities, colleges, auditoriums, speakers, sessions, bookings, waitlists, users |
| **Deployment** | Single Python process (uvicorn), PostgreSQL database, optional SMTP |

---

## Tech Stack

| Layer | Technology | Role |
|---|---|---|
| **Web Framework** | FastAPI | Async HTTP server, routing, middleware, dependency injection |
| **ORM** | SQLAlchemy | Database models, relationships, queries |
| **Templating** | Jinja2 | Server-side HTML rendering |
| **Database** | PostgreSQL | Primary data store (via `psycopg2-binary`) |
| **Auth** | bcrypt + Starlette Sessions | Password hashing and cookie-based session management |
| **QR Codes** | `qrcode[pil]` | Ticket QR generation for booking confirmations |
| **QR Scanner** | html5-qrcode (CDN) | Browser-based camera QR scanning for check-in |
| **Config** | pydantic-settings + `.env` | Type-safe configuration with environment variable overrides |
| **Email** | smtplib | Signup and booking confirmation emails |
| **Frontend** | Vanilla HTML/CSS/JS | No SPA framework; server-rendered with custom interactive components |

---

## Architecture Diagrams

### System Architecture

High-level overview of how TechTrek's components interact.

```mermaid
graph LR
    subgraph client [Client]
        Browser["Browser"]
    end

    subgraph server [FastAPI Server]
        Middleware["Session Middleware"]
        Routers["Routers"]
        Services["Services"]
        Templates["Jinja2 Templates"]
        StaticFiles["Static Files<br/>CSS / JS"]
    end

    subgraph data [Data Layer]
        PostgreSQL["PostgreSQL"]
    end

    subgraph external [External]
        SMTP["SMTP Server"]
    end

    Browser -->|"HTTP Requests"| Middleware
    Middleware --> Routers
    Routers --> Services
    Services --> PostgreSQL
    Routers --> Templates
    Templates --> Browser
    Browser -->|"/static/*"| StaticFiles
    Services -->|"Email notifications"| SMTP
```

### Request Lifecycle

Every HTTP request flows through these layers in order.

```mermaid
%%{init: {"sequence": {"useMaxWidth": true, "width": 900}}}%%
sequenceDiagram
    participant B as Browser
    participant M as SessionMiddleware
    participant R as Router
    participant D as Dependencies
    participant S as Service
    participant DB as PostgreSQL
    participant T as Jinja2 Template

    B->>M: HTTP Request
    M->>M: Load/create session cookie
    M->>R: Forward request
    R->>D: Resolve dependencies
    D->>DB: get_db() session
    D->>DB: get_current_user()
    D-->>R: db, user, template_ctx
    R->>S: Business logic call
    S->>DB: Query / mutate
    DB-->>S: Result
    S-->>R: Domain result
    R->>T: Render template with context
    T-->>B: HTML Response
```

### User Flow

End-to-end journey from browsing to attending a session.

```mermaid
flowchart LR
    Browse["Browse Sessions"] --> ViewDetail["View Session Detail"]
    ViewDetail --> Register["Register / Login"]
    Register --> SelectSeats["Select Seats"]
    SelectSeats --> Hold["Hold Seats<br/>5-min timer"]
    Hold --> Checkout["Checkout Page"]
    Checkout --> Pay["Confirm Payment"]
    Pay --> Ticket["Receive Ticket<br/>+ QR Code"]
    Ticket --> CheckIn["QR Scan<br/>at Venue"]

    ViewDetail -->|"Sold out"| Waitlist["Join Waitlist"]
    Waitlist -->|"Priority granted"| SelectSeats
```

### Booking State Machine

A booking transitions through these states during its lifecycle.

```mermaid
%%{init: {"state": {"useMaxWidth": true}}}%%
stateDiagram-v2
    direction LR
    [*] --> hold: User selects seats
    hold --> paid: Payment confirmed
    hold --> expired: Hold timer expires
    paid --> refunded: User cancels or admin refunds
    paid --> checkedIn: QR scanned at venue
    expired --> [*]
    refunded --> [*]
    checkedIn --> [*]

    note right of hold
        held_until = now + 5 min
        Existing holds replaced
    end note

    note right of paid
        ticket_id generated
        QR code created
        Email sent
    end note

    note right of refunded
        Refund = amount - 100 fee
        Seat becomes available
    end note
```

### Database Entity Relationships

All 12 models and how they relate to each other, split into three diagrams by domain. Full column details are in the [Database Schema](#database-schema) section below.

#### Core Booking Flow

Users book seats for lecture sessions. Each booking links a user, a session, and a seat.

```mermaid
erDiagram
    User ||--o{ Booking : "has many"
    LectureSession ||--o{ Booking : "has many"
    Booking }o--|| Seat : "reserves"
    Auditorium ||--o{ Seat : "has many"
    Auditorium ||--o{ LectureSession : "hosts"

    User {
        int id PK
        string email UK
        string username UK
        bool is_admin
        bool is_supervisor
    }

    Booking {
        int id PK
        int user_id FK
        int session_id FK
        int seat_id FK
        string payment_status
        string ticket_id UK
        string booking_group
        datetime held_until
    }

    LectureSession {
        int id PK
        int auditorium_id FK
        int speaker_id FK
        string title
        numeric price
        string status
    }

    Seat {
        int id PK
        int auditorium_id FK
        string label
        string seat_type
    }

    Auditorium {
        int id PK
        int college_id FK
        string name
    }
```

#### Location Hierarchy

Cities contain colleges, which contain auditoriums.

```mermaid
erDiagram
    City ||--o{ College : "has many"
    College ||--o{ Auditorium : "has many"
    Auditorium ||--o{ Seat : "has many"

    City {
        int id PK
        string name
        string state
        bool is_active
    }

    College {
        int id PK
        int city_id FK
        string name
        string address
        bool is_active
    }

    Auditorium {
        int id PK
        int college_id FK
        string name
        string location
        int total_rows
        int total_cols
    }

    Seat {
        int id PK
        int auditorium_id FK
        string label
        string seat_type
        bool is_active
    }
```

#### Supporting Models

Speakers, agenda items, waitlists, testimonials, and newsletter subscribers.

```mermaid
erDiagram
    Speaker ||--o{ LectureSession : "presents"
    LectureSession ||--o{ AgendaItem : "has many"
    LectureSession ||--o{ Waitlist : "has many"
    User ||--o{ Waitlist : "has many"

    Speaker {
        int id PK
        string name
        string title
        string email
    }

    LectureSession {
        int id PK
        int speaker_id FK
        string title
        string status
    }

    AgendaItem {
        int id PK
        int session_id FK
        int order
        string title
        int duration_minutes
    }

    Waitlist {
        int id PK
        int user_id FK
        int session_id FK
        int priority_session_id FK
        datetime priority_expires_at
    }

    User {
        int id PK
        string email UK
        string username UK
    }

    Testimonial {
        int id PK
        string student_name
        text quote
        bool is_active
    }

    NewsletterSubscriber {
        int id PK
        string email UK
    }
```

### Template Hierarchy

How Jinja2 templates inherit from base layouts, split by public/user-facing pages and admin pages.

#### Public, Auth, Booking, and Supervisor Templates

```mermaid
graph LR
    Base["base.html<br/>Navbar, Footer, Theme,<br/>Flash Messages, Modals"]

    Base --> Home["public/home.html"]
    Base --> Sessions["public/sessions.html"]
    Base --> SessionDetail["public/session_detail.html"]
    Base --> TicketView["public/ticket.html"]
    Base --> TicketGroup["public/ticket_group.html"]

    Base --> Login["auth/login.html"]
    Base --> RegisterPage["auth/register.html"]

    Base --> SelectSeat["booking/select_seat.html"]
    Base --> CheckoutPage["booking/checkout.html"]
    Base --> Confirmation["booking/confirmation.html"]
    Base --> MyBookings["booking/my_bookings.html"]
    Base --> BookingDetail["booking/booking_detail.html"]

    Base --> Err404["errors/404.html"]
    Base --> Err500["errors/500.html"]

    Base --> SupervisorCheckin["supervisor/checkin.html"]
```

#### Admin Panel Templates

```mermaid
graph LR
    Base["base.html"] --> BaseAdmin["admin/base_admin.html<br/>Sidebar Navigation"]

    BaseAdmin --> Dashboard["admin/dashboard.html"]
    BaseAdmin --> AdminSessions["admin/sessions.html"]
    BaseAdmin --> SessionForm["admin/session_form.html"]
    BaseAdmin --> AdminBookings["admin/bookings.html"]
    BaseAdmin --> AdminUsers["admin/users.html"]
    BaseAdmin --> Cities["admin/cities.html"]
    BaseAdmin --> CityForm["admin/city_form.html"]
    BaseAdmin --> Colleges["admin/colleges.html"]
    BaseAdmin --> CollegeForm["admin/college_form.html"]
    BaseAdmin --> Auditoriums["admin/auditoriums.html"]
    BaseAdmin --> AuditoriumForm["admin/auditorium_form.html"]
    BaseAdmin --> SeatLayout["admin/seat_layout.html"]
    BaseAdmin --> Speakers["admin/speakers.html"]
    BaseAdmin --> SpeakerForm["admin/speaker_form.html"]
    BaseAdmin --> CheckinPage["admin/checkin.html"]
    BaseAdmin --> WaitlistPage["admin/waitlist.html"]
```

---

## Features Overview

### Public Visitors (No Login Required)

| Feature | Description |
|---|---|
| **Browse Sessions** | View all published upcoming lecture sessions with search and filter by city |
| **Session Details** | See speaker info, agenda, venue, pricing tiers, and real-time seat availability |
| **Availability Badges** | Sessions display "Available", "Filling Up", "Sold Out", or "Priority Only" badges |
| **View Tickets** | Anyone with a ticket link or group link can view ticket details and QR codes |
| **Newsletter** | Subscribe to email updates from the home page |
| **Light/Dark Theme** | Toggle between a dark cyberpunk theme and a light Frutiger Aero theme |

### Registered Users

| Feature | Description |
|---|---|
| **Account Registration** | Sign up with email, username, password, and optional profile fields (college, discipline, domain, year) |
| **Interactive Seat Selection** | Visual seat map with real-time availability; supports standard, VIP, and accessible seat types |
| **Multi-Seat Booking** | Select multiple seats in one transaction; generates a group ticket with a shared QR code |
| **5-Minute Hold** | Selected seats are held for 5 minutes while the user completes checkout |
| **Tiered Pricing** | Different prices for standard, VIP, and accessible seats |
| **QR-Coded Tickets** | Each booking generates a unique ticket ID and QR code for venue check-in |
| **My Bookings** | Dashboard showing active bookings and archived (cancelled/refunded) history |
| **Booking Cancellation** | Cancel paid bookings with automatic refund calculation (amount minus a fixed cancellation fee of 100) |
| **Waitlist** | Join a waitlist for sold-out sessions; receive priority booking access when new sessions are added |

### Supervisors

| Feature | Description |
|---|---|
| **QR Check-In** | Scan attendee QR codes using the device camera to verify and mark check-in |
| **Manual Entry** | Enter a ticket ID manually when QR scanning is not possible |
| **Verification Feedback** | Immediate visual confirmation of valid/invalid/already-checked-in tickets |

### Administrators

| Feature | Description |
|---|---|
| **Dashboard** | Overview statistics: total users, active sessions, bookings, revenue |
| **City Management** | Create, edit, toggle active, and delete cities |
| **College Management** | Create, edit, and delete colleges linked to cities |
| **Auditorium Management** | Create and edit auditoriums with configurable row/column counts |
| **Seat Layout Designer** | Visual drag-and-paint tool for designing auditorium layouts with standard, VIP, accessible, and aisle seats; row/column gaps; stage width |
| **Speaker Management** | Create and edit speaker profiles with name, title, bio, photo, and email |
| **Session Management** | Create and edit lecture sessions with speaker, auditorium, schedule, pricing tiers, description, and banner; publish or keep as draft |
| **Agenda Builder** | Add ordered agenda items to sessions with speaker names and durations |
| **Booking Management** | View and filter all bookings; cancel or refund individual bookings |
| **CSV Export** | Export filtered booking data as CSV for reporting |
| **Check-In** | QR scanning and manual ticket verification (same as supervisor) |
| **Waitlist Management** | View waitlisted users; grant priority access to a target session for all waitlisted users of a source session |
| **User Management** | View all registered users; toggle admin and supervisor roles |

---

## Backend Architecture

### Project Structure

```
techtrak/
├── app/
│   ├── main.py                  # Application entry point, middleware, router registration
│   ├── config.py                # Pydantic-settings configuration
│   ├── database.py              # SQLAlchemy engine and session factory
│   ├── dependencies.py          # FastAPI dependencies (auth, templates, flash messages)
│   ├── models/
│   │   ├── __init__.py          # Re-exports all models
│   │   ├── user.py              # User model
│   │   ├── city.py              # City model
│   │   ├── college.py           # College model
│   │   ├── auditorium.py        # Auditorium model
│   │   ├── seat.py              # Seat model
│   │   ├── speaker.py           # Speaker model
│   │   ├── session.py           # LectureSession model
│   │   ├── agenda.py            # AgendaItem model
│   │   ├── booking.py           # Booking model
│   │   ├── waitlist.py          # Waitlist model
│   │   └── testimonial.py       # Testimonial and NewsletterSubscriber models
│   ├── routers/
│   │   ├── auth.py              # Authentication routes (/auth)
│   │   ├── public.py            # Public pages (/, /sessions, /ticket)
│   │   ├── booking.py           # Booking flow (/booking)
│   │   ├── admin.py             # Admin panel (/admin)
│   │   └── supervisor.py        # Supervisor check-in (/supervisor)
│   ├── services/
│   │   ├── booking.py           # Booking business logic
│   │   └── email.py             # Email sending service
│   ├── schemas/                 # (Reserved for Pydantic schemas)
│   ├── templates/               # Jinja2 HTML templates (33 files)
│   └── static/
│       ├── css/style.css        # Single stylesheet (~2,600 lines)
│       └── js/
│           ├── seat-picker.js   # Interactive seat selection
│           └── seat-designer.js # Admin seat layout editor
├── seed.py                      # Database seeding script
├── requirements.txt             # Python dependencies
├── .env                         # Environment overrides (not committed)
└── README.md                    # Quick-start guide
```

### Entry Point (`app/main.py`)

The application is created and configured in a single module:

1. **FastAPI instance** is created with the title `"TechTrek"`. API docs are available at `/api/docs` when `debug=True`.
2. **SessionMiddleware** is attached for cookie-based session management using the configured `secret_key`.
3. **Static files** are mounted at `/static` from `app/static/`.
4. **All models** are imported so SQLAlchemy registers them, then `Base.metadata.create_all()` creates tables.
5. **Schema migrations** run as `ALTER TABLE` statements inside a `try/except` block to add columns that were introduced after the initial schema (`price_vip`, `price_accessible`, `booking_group`, `group_qr_data`, `is_supervisor`).
6. **Routers** are included in order: auth, public, booking, admin, supervisor.
7. **Exception handlers** are registered for `AuthRedirect` (303 redirect to login), 404 (custom template), and 500 (custom template).

### Configuration (`app/config.py`)

Configuration uses pydantic-settings with automatic `.env` file loading.

| Setting | Type | Default | Description |
|---|---|---|---|
| `database_url` | `str` | `postgresql+psycopg2://postgres:root@localhost:5432/techtrek` | Database connection string |
| `secret_key` | `str` | `techtrek-dev-secret-change-in-production` | Session cookie signing key |
| `debug` | `bool` | `True` | Enables `/api/docs` endpoint |
| `hold_timeout_minutes` | `int` | `5` | Minutes a seat hold remains valid |
| `priority_window_hours` | `int` | `24` | Hours a waitlist priority grant lasts |
| `smtp_host` | `str` | `""` | SMTP server hostname (empty = emails skipped) |
| `smtp_port` | `int` | `587` | SMTP server port |
| `smtp_user` | `str` | `""` | SMTP authentication username |
| `smtp_password` | `str` | `""` | SMTP authentication password |
| `smtp_from_email` | `str` | `noreply@techtrek.in` | Sender email address |
| `smtp_from_name` | `str` | `TechTrek` | Sender display name |

### Database Layer (`app/database.py`)

Minimal setup using SQLAlchemy's synchronous API:

- `engine` is created from `settings.database_url` with echo disabled.
- `SessionLocal` is a `sessionmaker` bound to the engine, yielding standard ORM sessions.
- `Base` is a `DeclarativeBase` subclass that all models inherit from.

### Dependencies (`app/dependencies.py`)

FastAPI dependency functions provide shared functionality to all route handlers:

| Dependency | Signature | Purpose |
|---|---|---|
| `get_db()` | Generator yielding `Session` | Creates a database session per request and closes it after |
| `get_current_user()` | `(Request, Session) -> Optional[User]` | Reads `user_id` from the session cookie and returns the `User` or `None` |
| `require_auth()` | `(Request, Session) -> User` | Same as above but raises `AuthRedirect` if no user is logged in |
| `require_admin()` | `(Request, Session) -> User` | Requires the user to be logged in AND have `is_admin=True` |
| `flash()` | `(Request, str, str)` | Stores a flash message in the session for display on next page load |
| `get_flashes()` | `(Request) -> list` | Pops and returns all pending flash messages |
| `template_ctx()` | `(Request, **kwargs) -> dict` | Builds the standard template context (`request`, `user`, `flashes`, plus any extras) |

`AuthRedirect` is a custom exception that carries a redirect URL. When raised, the global exception handler returns a 303 redirect to the login page with a `next` query parameter preserving the intended destination.

### Services

#### Booking Service (`app/services/booking.py`)

Contains the core booking business logic:

| Function | Purpose |
|---|---|
| `get_seat_map(db, session_id, auditorium_id)` | Returns a list of seat dicts with `id`, `row`, `col`, `label`, `type`, and `status` (available/taken/aisle). A seat is "taken" if it has a paid booking or an active hold. |
| `hold_seats(db, user_id, session_id, seat_ids)` | Cancels any existing holds for the user on this session, then creates new `Booking` records with `payment_status="hold"` and `held_until` set to now + 5 minutes. Skips seats that are already taken. |
| `confirm_payment(db, user_id, session_id)` | Converts valid holds to paid bookings. Generates `ticket_id` (format: `TT-YYYYMMDD-XXXXXXXX`), QR code (base64 PNG), sets `amount_paid` based on seat type pricing, assigns `booking_group` and `group_qr_data` for multi-seat bookings, and sends confirmation emails. |
| `cancel_booking_user(db, booking_id, user_id)` | Cancels a paid booking. Applies a fixed cancellation fee of 100 and sets `payment_status="refunded"`. Returns the refund amount. |
| `cancel_existing_holds(db, user_id, session_id)` | Marks all hold-status bookings for a user/session as cancelled. |
| `get_user_bookings(db, user_id)` | Returns all paid and refunded bookings for a user, ordered by date descending. |

#### Email Service (`app/services/email.py`)

Handles transactional emails via SMTP:

| Function | Purpose |
|---|---|
| `send_signup_confirmation(email, username)` | Sends a welcome email after registration |
| `send_booking_confirmation(email, username, session_title, seat_label, ticket_id, booking_ref)` | Sends a booking confirmation with seat details, ticket ID, and cancellation policy |

If `smtp_host` is empty (the default), emails are logged but not sent, allowing development without an SMTP server.

### Authentication System

TechTrek uses **session-based authentication** with **bcrypt password hashing**:

1. **Registration**: User submits email, username, password, and optional profile fields. The password is hashed with `bcrypt.hashpw()` and stored. The first registered user is automatically granted admin privileges (`is_admin=True`). A signup confirmation email is sent.

2. **Login**: User submits username/email and password. The system looks up the user by username or email, then verifies with `bcrypt.checkpw()`. On success, `user_id` is stored in the session cookie.

3. **Session Management**: Starlette's `SessionMiddleware` handles cookie-based sessions. The session is signed with `secret_key` to prevent tampering.

4. **Authorization Levels**:
   - **Public**: No authentication required
   - **User**: `require_auth()` -- must be logged in
   - **Supervisor or Admin**: Checked via `user.is_supervisor or user.is_admin`
   - **Admin only**: `require_admin()` -- must have `is_admin=True`

5. **Logout**: Clears the entire session via `request.session.clear()`.

---

## Database Schema

All models inherit from `app.database.Base` (SQLAlchemy `DeclarativeBase`). Tables are created automatically on startup via `Base.metadata.create_all()`. There are no Alembic migrations; additional columns are added via raw `ALTER TABLE` statements in `app/main.py`.

### `users`

User accounts with role flags.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `Integer` | PK, indexed | Auto-increment primary key |
| `email` | `String(255)` | Unique, not null, indexed | Login email address |
| `username` | `String(100)` | Unique, not null, indexed | Login username |
| `password_hash` | `String(255)` | Not null | bcrypt password hash |
| `full_name` | `String(200)` | Nullable | Display name |
| `college` | `String(300)` | Nullable | College affiliation (free text) |
| `discipline` | `String(100)` | Nullable | Academic discipline |
| `domain` | `String(100)` | Nullable | Tech domain of interest |
| `year_of_study` | `Integer` | Nullable | Current year of study |
| `is_admin` | `Boolean` | Default `False` | Admin role flag |
| `is_supervisor` | `Boolean` | Default `False` | Supervisor role flag (added via ALTER) |
| `created_at` | `DateTime` | Default `utcnow` | Account creation timestamp |

**Relationships**: `bookings` (1:N Booking), `waitlist_entries` (1:N Waitlist)

---

### `cities`

Geographic cities that contain colleges.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `Integer` | PK, indexed | Auto-increment primary key |
| `name` | `String(200)` | Not null | City name |
| `state` | `String(200)` | Not null | State/province |
| `is_active` | `Boolean` | Default `True` | Soft-delete / visibility flag |
| `created_at` | `DateTime` | Default `utcnow` | Creation timestamp |

**Relationships**: `colleges` (1:N College, cascade delete)

---

### `colleges`

Educational institutions where events are held.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `Integer` | PK, indexed | Auto-increment primary key |
| `name` | `String(300)` | Not null | College name |
| `city_id` | `Integer` | FK -> `cities.id`, not null | Parent city |
| `address` | `String(500)` | Nullable | Physical address |
| `is_active` | `Boolean` | Default `True` | Soft-delete / visibility flag |
| `created_at` | `DateTime` | Default `utcnow` | Creation timestamp |

**Relationships**: `city` (N:1 City), `auditoriums` (1:N Auditorium)

---

### `auditoriums`

Venues within colleges that host lecture sessions.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `Integer` | PK, indexed | Auto-increment primary key |
| `name` | `String(200)` | Not null | Auditorium name |
| `college_id` | `Integer` | FK -> `colleges.id`, nullable | Parent college |
| `location` | `String(300)` | Not null | Location description |
| `description` | `Text` | Nullable | Additional details |
| `total_rows` | `Integer` | Not null, default `10` | Number of seat rows |
| `total_cols` | `Integer` | Not null, default `15` | Number of seat columns |
| `stage_cols` | `Integer` | Nullable | Stage width in columns (null = full width) |
| `row_gaps` | `Text` | Nullable | JSON array of row indices with a gap after them |
| `col_gaps` | `Text` | Nullable | JSON array of column indices with a gap after them |
| `layout_config` | `JSON` | Nullable | Full layout configuration (reserved) |

**Relationships**: `college` (N:1 College), `seats` (1:N Seat, cascade delete), `sessions` (1:N LectureSession)

---

### `seats`

Individual seats within an auditorium.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `Integer` | PK, indexed | Auto-increment primary key |
| `auditorium_id` | `Integer` | FK -> `auditoriums.id`, not null | Parent auditorium |
| `row_num` | `Integer` | Not null | Row position (1-based) |
| `col_num` | `Integer` | Not null | Column position (1-based) |
| `label` | `String(10)` | Not null | Display label (e.g., "A1", "B12") |
| `seat_type` | `String(20)` | Default `"standard"` | One of: `standard`, `vip`, `accessible`, `aisle` |
| `is_active` | `Boolean` | Default `True` | Whether the seat can be booked |

**Relationships**: `auditorium` (N:1 Auditorium), `bookings` (1:N Booking)

---

### `speakers`

Speaker profiles for lecture sessions.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `Integer` | PK, indexed | Auto-increment primary key |
| `name` | `String(200)` | Not null | Full name |
| `title` | `String(200)` | Nullable | Professional title |
| `bio` | `Text` | Nullable | Speaker biography |
| `photo_url` | `String(500)` | Nullable | Profile photo URL |
| `email` | `String(255)` | Nullable | Contact email |
| `created_at` | `DateTime` | Default `utcnow` | Creation timestamp |

**Relationships**: `sessions` (1:N LectureSession)

---

### `lecture_sessions`

Scheduled lecture/event sessions.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `Integer` | PK, indexed | Auto-increment primary key |
| `auditorium_id` | `Integer` | FK -> `auditoriums.id`, not null | Venue |
| `speaker_id` | `Integer` | FK -> `speakers.id`, nullable | Linked speaker profile |
| `title` | `String(300)` | Not null | Session title |
| `speaker` | `String(200)` | Not null | Speaker name (display text) |
| `description` | `Text` | Nullable | Session description |
| `banner_url` | `String(500)` | Nullable | Banner image URL |
| `start_time` | `DateTime` | Not null | Scheduled start time |
| `duration_minutes` | `Integer` | Default `30` | Session duration |
| `price` | `Numeric(10,2)` | Not null, default `0` | Standard seat price |
| `price_vip` | `Numeric(10,2)` | Nullable | VIP seat price (added via ALTER) |
| `price_accessible` | `Numeric(10,2)` | Nullable | Accessible seat price (added via ALTER) |
| `status` | `String(20)` | Default `"draft"` | One of: `draft`, `published`, `completed` |
| `created_at` | `DateTime` | Default `utcnow` | Creation timestamp |

**Relationships**: `auditorium` (N:1 Auditorium), `speaker_rel` (N:1 Speaker), `bookings` (1:N Booking), `agenda_items` (1:N AgendaItem, cascade delete, ordered), `waitlist_entries` (1:N Waitlist)

---

### `agenda_items`

Ordered items within a session's agenda.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `Integer` | PK, indexed | Auto-increment primary key |
| `session_id` | `Integer` | FK -> `lecture_sessions.id`, not null | Parent session |
| `order` | `Integer` | Default `0` | Display order |
| `title` | `String(300)` | Not null | Agenda item title |
| `speaker_name` | `String(200)` | Nullable | Speaker for this item |
| `duration_minutes` | `Integer` | Default `20` | Item duration |
| `description` | `Text` | Nullable | Item description |

**Relationships**: `session` (N:1 LectureSession)

---

### `bookings`

Seat bookings linking users, sessions, and seats.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `Integer` | PK, indexed | Auto-increment primary key |
| `user_id` | `Integer` | FK -> `users.id`, not null | Booking owner |
| `session_id` | `Integer` | FK -> `lecture_sessions.id`, not null | Target session |
| `seat_id` | `Integer` | FK -> `seats.id`, not null | Reserved seat |
| `payment_status` | `String(20)` | Default `"hold"` | One of: `hold`, `paid`, `refunded`, `cancelled` |
| `booking_ref` | `String(20)` | Unique | Auto-generated reference code (10 hex chars) |
| `ticket_id` | `String(30)` | Unique, nullable | Generated on payment (format: `TT-YYYYMMDD-XXXXXXXX`) |
| `qr_code_data` | `Text` | Nullable | Base64-encoded PNG QR code of the ticket ID |
| `booking_group` | `String(20)` | Nullable, indexed | Group identifier for multi-seat bookings (added via ALTER) |
| `group_qr_data` | `Text` | Nullable | Base64-encoded PNG QR code of the group ID (added via ALTER) |
| `amount_paid` | `Float` | Default `0` | Amount paid for the seat |
| `refund_amount` | `Float` | Nullable | Refund amount after cancellation |
| `cancellation_fee` | `Float` | Nullable | Fee deducted on cancellation (fixed at 100) |
| `checked_in` | `Boolean` | Default `False` | Whether the attendee has been checked in |
| `checked_in_at` | `DateTime` | Nullable | Check-in timestamp |
| `held_until` | `DateTime` | Nullable | Hold expiry time (null after payment) |
| `booked_at` | `DateTime` | Default `utcnow` | Booking creation / payment confirmation timestamp |

**Relationships**: `user` (N:1 User), `session` (N:1 LectureSession), `seat` (N:1 Seat)

---

### `waitlist`

Users waiting for seats on sold-out sessions.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `Integer` | PK, indexed | Auto-increment primary key |
| `user_id` | `Integer` | FK -> `users.id`, not null | Waitlisted user |
| `session_id` | `Integer` | FK -> `lecture_sessions.id`, not null | Original sold-out session |
| `priority_session_id` | `Integer` | FK -> `lecture_sessions.id`, nullable | Target session for priority booking (set by admin) |
| `joined_at` | `DateTime` | Default `utcnow` | Timestamp when user joined waitlist |
| `notified` | `Boolean` | Default `False` | Whether user has been notified |
| `priority_expires_at` | `DateTime` | Nullable | When the priority access window expires |

**Relationships**: `user` (N:1 User), `session` (N:1 LectureSession via `session_id`), `priority_session` (N:1 LectureSession via `priority_session_id`)

---

### `testimonials`

Student testimonials displayed on the home page.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `Integer` | PK, indexed | Auto-increment primary key |
| `student_name` | `String(200)` | Not null | Student name |
| `college` | `String(300)` | Nullable | College name |
| `quote` | `Text` | Not null | Testimonial text |
| `is_active` | `Boolean` | Default `True` | Visibility flag |
| `created_at` | `DateTime` | Default `utcnow` | Creation timestamp |

---

### `newsletter_subscribers`

Email newsletter subscriber list.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `Integer` | PK, indexed | Auto-increment primary key |
| `email` | `String(255)` | Unique, not null | Subscriber email |
| `subscribed_at` | `DateTime` | Default `utcnow` | Subscription timestamp |

---

## API Endpoints Reference

All endpoints are server-rendered (returning HTML via Jinja2 templates) unless otherwise noted. Form submissions use `POST` and redirect via 303. There are no JSON API endpoints -- the application is a traditional server-rendered web app.

**Auth levels:**
- **Public** -- no authentication required
- **User** -- must be logged in
- **Supervisor+** -- must be logged in with `is_supervisor` or `is_admin`
- **Admin** -- must be logged in with `is_admin`

### Auth Router (`/auth`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/auth/login` | Public | Render login form |
| `POST` | `/auth/login` | Public | Authenticate with username/email and password; set session; redirect to `next` or `/` |
| `GET` | `/auth/register` | Public | Render registration form |
| `POST` | `/auth/register` | Public | Create user account; auto-login; send welcome email; first user becomes admin |
| `GET` | `/auth/logout` | Public | Clear session; redirect to `/` |

### Public Router (no prefix)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | Public | Home page with up to 6 upcoming sessions and active testimonials |
| `POST` | `/newsletter` | Public | Subscribe an email to the newsletter |
| `GET` | `/sessions` | Public | List published upcoming sessions; supports query params: `q` (search), `sort` (date/price/title), `date`, `city_id`, `college_id` |
| `GET` | `/sessions/{session_id}` | Public | Session detail page with speaker, agenda, pricing, availability, and waitlist status |
| `GET` | `/ticket/{ticket_id}` | Public | View a single paid ticket by its ticket ID (shareable link) |
| `GET` | `/tickets/group/{group_id}` | Public | View all tickets in a booking group (shareable link) |

### Booking Router (`/booking`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/booking/select/{session_id}` | User | Interactive seat selection page with real-time seat map |
| `POST` | `/booking/hold/{session_id}` | User | Hold selected seats for 5 minutes; form field: `seat_ids` (comma-separated) |
| `GET` | `/booking/checkout/{session_id}` | User | Checkout page showing held seats, total price, and countdown timer |
| `POST` | `/booking/pay/{session_id}` | User | Confirm payment; generate ticket IDs, QR codes; send confirmation email |
| `GET` | `/booking/confirmation/{session_id}` | User | Booking confirmation page with ticket details and QR codes |
| `GET` | `/booking/my` | User | My Bookings dashboard with active and archived bookings |
| `GET` | `/booking/detail/group/{group_id}` | User | Booking detail for a multi-seat group booking |
| `GET` | `/booking/detail/{booking_id}` | User | Booking detail for a single booking |
| `POST` | `/booking/cancel/{booking_id}` | User | Cancel a paid booking; apply cancellation fee; calculate refund |
| `POST` | `/booking/waitlist/{session_id}` | User | Join the waitlist for a sold-out session |

### Admin Router (`/admin`)

#### Dashboard

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/admin/` | Supervisor+ | Dashboard with stats: total users, bookings, revenue, upcoming sessions, check-ins, refunds, event status breakdown, top cities, recent bookings |

#### Cities

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/admin/cities` | Admin | List all cities |
| `GET` | `/admin/cities/new` | Admin | New city form |
| `POST` | `/admin/cities/new` | Admin | Create city |
| `GET` | `/admin/cities/{city_id}/edit` | Admin | Edit city form |
| `POST` | `/admin/cities/{city_id}/edit` | Admin | Update city |
| `POST` | `/admin/cities/{city_id}/delete` | Admin | Delete city (cascades to colleges) |
| `POST` | `/admin/cities/{city_id}/toggle` | Admin | Toggle city active/inactive status |

#### Colleges

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/admin/colleges` | Admin | List all colleges with their city |
| `GET` | `/admin/colleges/new` | Admin | New college form (select city) |
| `POST` | `/admin/colleges/new` | Admin | Create college |
| `GET` | `/admin/colleges/{college_id}/edit` | Admin | Edit college form |
| `POST` | `/admin/colleges/{college_id}/edit` | Admin | Update college |
| `POST` | `/admin/colleges/{college_id}/delete` | Admin | Delete college |

#### Auditoriums

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/admin/auditoriums` | Admin | List all auditoriums |
| `GET` | `/admin/auditoriums/new` | Admin | New auditorium form (select college) |
| `POST` | `/admin/auditoriums/new` | Admin | Create auditorium; redirect to layout designer |
| `GET` | `/admin/auditoriums/{aud_id}/edit` | Admin | Edit auditorium form |
| `POST` | `/admin/auditoriums/{aud_id}/edit` | Admin | Update auditorium |
| `POST` | `/admin/auditoriums/{aud_id}/delete` | Admin | Delete auditorium (cascades to seats) |
| `GET` | `/admin/auditoriums/{aud_id}/layout` | Admin | Seat layout designer (visual editor) |
| `POST` | `/admin/auditoriums/{aud_id}/layout` | Admin | Save seat layout; replaces all seats; updates rows, cols, gaps, stage width |

#### Speakers

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/admin/speakers` | Admin | List all speakers |
| `GET` | `/admin/speakers/new` | Admin | New speaker form |
| `POST` | `/admin/speakers/new` | Admin | Create speaker |
| `GET` | `/admin/speakers/{speaker_id}/edit` | Admin | Edit speaker form |
| `POST` | `/admin/speakers/{speaker_id}/edit` | Admin | Update speaker |
| `POST` | `/admin/speakers/{speaker_id}/delete` | Admin | Delete speaker |

#### Sessions

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/admin/sessions` | Supervisor+ | List all sessions with auditorium and booking counts |
| `GET` | `/admin/sessions/new` | Admin | New session form (select auditorium, speaker; set pricing, agenda) |
| `POST` | `/admin/sessions/new` | Admin | Create session with agenda items |
| `GET` | `/admin/sessions/{sess_id}/edit` | Admin | Edit session form with existing agenda |
| `POST` | `/admin/sessions/{sess_id}/edit` | Admin | Update session and replace agenda items |
| `POST` | `/admin/sessions/{sess_id}/delete` | Admin | Delete session (cascades to agenda items) |

#### Bookings

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/admin/bookings` | Supervisor+ | List bookings with filters: `q` (search), `status` (paid/hold/refunded), `session_id` |
| `GET` | `/admin/bookings/export` | Supervisor+ | Export all bookings as CSV (columns: ref, ticket, user, email, session, seat, status, amount, refund, date, checked-in) |
| `POST` | `/admin/bookings/{booking_id}/cancel` | Admin | Cancel a booking (set status to cancelled) |
| `POST` | `/admin/bookings/{booking_id}/refund` | Admin | Refund a booking (set status to refunded) |

#### Check-in

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/admin/checkin` | Supervisor+ | Check-in page with session selector |
| `POST` | `/admin/checkin` | Supervisor+ | Verify ticket by ID or QR scan; supports individual and group check-in; returns live stats |

#### Waitlist

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/admin/waitlist` | Admin | List all waitlist entries with user and session info |
| `POST` | `/admin/waitlist/grant-priority` | Admin | Grant priority booking access: select source session (sold-out) and target session; sets 24-hour priority window for all waitlisted users |

#### Users

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/admin/users` | Supervisor+ | List all registered users |
| `POST` | `/admin/users/{user_id}/toggle-admin` | Admin | Toggle admin role for a user (cannot toggle self) |
| `POST` | `/admin/users/{user_id}/toggle-supervisor` | Admin | Toggle supervisor role for a user (cannot toggle self) |

### Supervisor Router (`/supervisor`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/supervisor/` | Supervisor+ | Standalone check-in page (simplified, no admin sidebar) |
| `POST` | `/supervisor/checkin` | Supervisor+ | Verify and check in tickets; supports individual and group QR codes; returns live stats |

---

## Frontend Architecture

### Templating

TechTrek uses **Jinja2** for server-side HTML rendering. There are no client-side SPA frameworks -- all pages are rendered on the server and returned as complete HTML documents.

**Template directory**: `app/templates/` (33 files total)

**Inheritance chain**:
- `base.html` -- Root layout used by all pages. Provides the navbar, footer, flash messages, theme toggle, modals, starfield background, and shared inline JavaScript.
- `admin/base_admin.html` -- Extends `base.html`. Adds a sidebar navigation for the admin panel. Admin templates extend this instead of `base.html` directly.
- All other templates extend either `base.html` or `admin/base_admin.html`.

**Template blocks** available for child templates:

| Block | Defined In | Purpose |
|---|---|---|
| `title` | `base.html` | Page title in `<title>` tag |
| `head_extra` | `base.html` | Additional `<head>` content (styles, meta) |
| `content` | `base.html` | Main page content |
| `scripts` | `base.html` | Additional `<script>` tags at bottom of body |
| `admin_content` | `base_admin.html` | Admin page content (wrapped inside `content` block with sidebar) |

### Design System

The entire design is contained in a single stylesheet: `app/static/css/style.css` (~2,600 lines).

#### Typography

| Variable | Font | Usage |
|---|---|---|
| `--font-display` | Orbitron | Headings, hero text, brand name |
| `--font-body` | Exo 2 | Body text, form labels, descriptions |
| `--font-mono` | JetBrains Mono | Code, ticket IDs, booking references |

All fonts are loaded from Google Fonts.

#### Color Palette

**Dark theme** (default -- cyberpunk aesthetic):

| Variable | Value | Usage |
|---|---|---|
| `--bg-void` | `#010409` | Page background |
| `--bg-primary` | `#0d1117` | Primary surfaces |
| `--bg-surface` | `#161b22` | Cards, panels |
| `--bg-elevated` | `#1c2128` | Elevated elements, card bodies |
| `--cyan` | `#00d4ff` | Primary accent, links, interactive elements |
| `--amber` | `#f59e0b` | Secondary accent, prices, VIP badges |
| `--violet` | `#8b5cf6` | Tertiary accent, user bookings |
| `--green` | `#10b981` | Success states, available seats |
| `--red` | `#f43f5e` | Danger states, errors, sold-out badges |
| `--text-primary` | `#e6edf3` | Main text |
| `--text-secondary` | `#c0cad4` | Secondary text |
| `--text-muted` | `#8b949e` | Muted/helper text |

**Light theme** (toggled via `data-theme="light"` on `<html>` -- Frutiger Aero style):

Overrides all CSS variables with lighter, sky-tinted values. Surfaces become translucent white (`rgba(255,255,255,0.62)`), text becomes dark (`#0c1e2e`), and accents are adjusted for legibility on light backgrounds.

#### Spacing and Layout

| Variable | Value | Purpose |
|---|---|---|
| `--nav-h` | `64px` | Navbar height |
| `--container` | `1200px` | Max content width |
| `--radius-sm` | `4px` | Small border radius |
| `--radius` | `8px` | Default border radius |
| `--radius-lg` | `14px` | Large border radius |
| `--radius-xl` | `20px` | Extra-large border radius |

#### Seat Colors

| Variable | Meaning |
|---|---|
| `--seat-available` | Available for selection (green) |
| `--seat-taken` | Already booked or held (dark gray / light gray) |
| `--seat-selected` | Currently selected by user (cyan) |
| `--seat-vip` | VIP seat (amber) |
| `--seat-accessible` | Accessible seat (purple) |
| `--seat-yours` | User's own booking (violet) |

### Component Library

All components are CSS-only (no JS framework). Key components:

| Component | Classes | Description |
|---|---|---|
| **Buttons** | `.btn`, `.btn-primary`, `.btn-outline`, `.btn-amber`, `.btn-danger`, `.btn-sm`, `.btn-lg`, `.btn-block`, `.btn-icon` | Full button system with variants, sizes, and states |
| **Cards** | `.card`, `.card-hover`, `.card-image`, `.card-body`, `.card-footer`, `.card-badge` | Content cards with hover effects and status badges (`available`, `filling-up`, `sold-out`, `priority-only`) |
| **Forms** | `.form-input`, `.form-select`, `.form-textarea`, `.form-group`, `.form-label`, `.form-card`, `.form-row`, `.form-actions` | Form controls with consistent styling |
| **Modals** | `.modal-wrapper`, `.modal-backdrop`, `.modal-dialog`, `.modal-icon-ring`, `.modal-footer` | Confirmation dialogs with focus trapping |
| **Flash Messages** | `.flash-container`, `.flash-message`, `.flash-success`, `.flash-error`, `.flash-warning`, `.flash-info` | Auto-dismissing notification bars (5-second timeout) |
| **Tables** | `.table`, `.table-striped`, `.actions-cell` | Data tables for admin views |
| **Badges** | `.card-badge`, `.badge-available`, `.badge-filling-up`, `.badge-sold-out`, `.badge-priority-only` | Status indicators on session cards |

### Interactive JavaScript

#### Inline Scripts (`base.html`)

The base template includes substantial inline JavaScript that provides global functionality:

| Feature | Description |
|---|---|
| **Starfield Canvas** | Animated particle background on dark theme; hidden on light theme. Draws small dots and connecting lines on a full-viewport `<canvas>`. |
| **Navbar Scroll Effect** | Adds `.scrolled` class to navbar after 20px of scroll for a more compact, opaque header. |
| **Mobile Navigation** | Hamburger menu toggles a slide-out drawer with overlay. Supports touch events and `Escape` key to close. |
| **Theme Toggle** | Persists to `localStorage` (`techtrek-theme`). Swaps `data-theme` attribute on `<html>` and toggles sun/moon icons. |
| **Flash Message Auto-dismiss** | Flash messages auto-hide after 5 seconds with a fade-out animation. Close button available. |
| **Scroll Reveal** | `IntersectionObserver` triggers `.visible` class on elements with `.reveal` or `.stagger` for entrance animations. |
| **Form Submit Loading** | On form submit, the submit button gets `.btn-loading` class with a spinner, preventing double-submission. |
| **Confirm Modal** | `data-confirm` attribute on forms/buttons triggers a confirmation dialog with focus trap and `Escape` key support. Exposed as `window.TechTrek.confirmAction()`. |
| **Toast Notifications** | Programmatic toast system. Exposed as `window.TechTrek.showToast(message, type)`. |
| **QR Zoom Modal** | Click on a ticket QR image to enlarge it in a centered modal. |
| **Admin Sidebar Toggle** | Mobile toggle button for the admin sidebar with overlay. |

#### `seat-picker.js` (Booking Flow)

Interactive seat selection component used on the booking page.

- **Initialization**: `SeatPicker.init(seatMap, pricing, sessionId, gaps, stageOpts)` -- receives seat data as JSON, pricing tiers, and layout config from the server.
- **Rendering**: Generates a grid of seat buttons with row labels (A-Z), column numbers, and visual gaps matching the auditorium layout.
- **Seat types**: Standard (green), VIP (amber), Accessible (purple), Aisle (spacer, non-clickable).
- **Selection**: Click available seats to toggle selection. Updates a summary panel showing selected seats, price per seat, and total cost.
- **Accessibility**: ARIA roles (`role="grid"`, `role="gridcell"`) and labels on all seat buttons.
- **Responsive**: `fitToViewport()` scales the grid to fit the screen width.
- **Output**: Populates a hidden `<input name="seat_ids">` with comma-separated seat IDs for form submission.

#### `seat-designer.js` (Admin Layout Editor)

Visual auditorium layout editor for administrators.

- **Initialization**: `SeatDesigner.init(rows, cols, existingSeats, stageCols, rowGaps, colGaps)` -- loads existing layout or starts fresh.
- **Toolbar**: Paint tools for Standard, VIP, Accessible, Aisle, and Eraser.
- **Interaction**: Click or click-and-drag to paint seats. Right-click to erase. Shift+click on row/column headers to toggle gaps.
- **Operations**: Fill row, fill column, fill all, center aisle, add/remove rows and columns, insert/delete via right-click context menu.
- **Stage control**: Adjustable stage width in columns.
- **Output**: On save, populates hidden form fields: `layout_data` (JSON), `total_rows`, `total_cols`, `stage_cols`, `row_gaps`, `col_gaps`.

#### External Library: html5-qrcode

Loaded from CDN (`html5-qrcode@2.3.8`) on check-in pages (both admin and supervisor). Provides browser-based camera QR code scanning for ticket verification.

---

## Getting Started

### Prerequisites

- **Python 3.10+**
- **PostgreSQL** running locally (or update `DATABASE_URL` to point elsewhere)

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd techtrek

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

### Database Setup

Ensure PostgreSQL is running and a database named `techtrek` exists:

```sql
CREATE DATABASE techtrek;
```

The application creates all tables automatically on startup. No manual migration step is needed.

### Seed Sample Data

```bash
python seed.py
```

This populates the database with sample cities, colleges, auditoriums, speakers, sessions, testimonials, and user accounts. It only runs if the `users` table is empty.

### Run the Application

```bash
uvicorn app.main:app --reload
```

The app will be available at `http://localhost:8000`. API docs (Swagger UI) are at `http://localhost:8000/api/docs` when `debug=True`.

### Default Accounts

| Username | Password | Role |
|---|---|---|
| `admin` | `admin123` | Admin |
| `alice` | `user123` | Regular user |
| `bob` | `user123` | Regular user |
| `charlie` | `user123` | Regular user |

### Environment Variables

Create a `.env` file in the project root to override any settings. All settings have sensible defaults for local development.

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://postgres:root@localhost:5432/techtrek` | PostgreSQL connection string |
| `SECRET_KEY` | `techtrek-dev-secret-change-in-production` | Session cookie signing key (change in production) |
| `DEBUG` | `True` | Enable debug mode and Swagger docs |
| `HOLD_TIMEOUT_MINUTES` | `5` | How long seat holds last before expiring |
| `PRIORITY_WINDOW_HOURS` | `24` | Duration of waitlist priority access window |
| `SMTP_HOST` | (empty) | SMTP server hostname; leave empty to skip emails |
| `SMTP_PORT` | `587` | SMTP server port |
| `SMTP_USER` | (empty) | SMTP login username |
| `SMTP_PASSWORD` | (empty) | SMTP login password |
| `SMTP_FROM_EMAIL` | `noreply@techtrek.in` | Sender email address |
| `SMTP_FROM_NAME` | `TechTrek` | Sender display name |

### Dependencies

```
fastapi
uvicorn[standard]
sqlalchemy
psycopg2-binary
jinja2
python-multipart
bcrypt
itsdangerous
python-dotenv
pydantic-settings
qrcode[pil]
```


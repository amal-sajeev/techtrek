# TechTrek — Development Summary
**Date:** Friday, 13 March 2026
**Session:** Full-day feature sprint

---

## Overview

Seven features were designed, planned, and fully implemented across the TechTrek event booking platform today. The changes span the entire application stack — database models, backend routes, service layer, Jinja2 templates, and client-side JavaScript.

---

## Feature Map

```mermaid
mindmap
  root((TechTrek Sprint))
    Booking Flow
      Processing Fee %
        Admin sets % per session
        Hidden during seat selection
        Shown as line item at checkout
        Included in Razorpay order
      Terms & Conditions
        Checkbox at checkout
        Blocks Pay button until accepted
        /terms static page
    Authentication
      Login → Redirect Back
        next= param in login GET
        next= param in register GET
        Register POST honours next=
        Cross-link next= preservation
    Platform
      Platform Logo
        SiteSetting DB model
        Admin Settings page
        Logo embedded in PDF invoices
        Company fields overrideable
    Access Control
      Recordings Gate
        Must be signed in
        Must have paid booking
        Cancelled bookings excluded
    Seat Types
      Icon Grid Picker
        20-emoji curated set
        Visual tile selector
        Shown in seat legend
        Rendered in seat cells
      Custom Pricing
        Price field on SeatType
        Shown on session detail page
        Used in booking calculations
        Seat picker live preview
```

---

## 1. Processing Fee Percentage

### Problem
Admins had no way to charge a platform/gateway processing fee on top of ticket prices. The fee needed to be invisible during seat selection but clearly broken out at checkout.

### Solution

```mermaid
flowchart LR
    A[Admin sets\nprocessing_fee_pct\non session] --> B[Seat Selection\nPage]
    B -- "Shows base\nprices only" --> C[Checkout Page]
    C -- "Fee line item\nappears here" --> D[Razorpay Order\ncreated with\nbase + fee total]
    D --> E[Payment\nConfirmed]

    style B fill:#1e293b,stroke:#334155,color:#94a3b8
    style C fill:#1e293b,stroke:#00d4ff,color:#e2e8f0
```

**Checkout breakdown (example):**
```
Seat A3 (VIP)          ₹800
Seat B7 (Standard)     ₹500
Processing Fee (2.5%)   ₹33
─────────────────────────────
Total                 ₹1,333
```

### Files Changed
| File | Change |
|------|--------|
| `app/models/session.py` | Added `processing_fee_pct NUMERIC(5,2)` column |
| `app/routers/admin.py` | Save fee % in session create/update handlers |
| `app/templates/admin/session_form.html` | New "Processing Fee (%)" input in Step 2 pricing |
| `app/routers/booking.py` | `checkout_page()` calculates `base_total`, `processing_fee`, `total` |
| `app/routers/booking.py` | `create_order()` includes fee in Razorpay paise amount |
| `app/templates/booking/checkout.html` | Conditional fee line item in summary |

---

## 2. Login / Signup → Redirect Back to Session

### Problem
When an unauthenticated user clicked a session's "Book" or "Sign in" button, they were sent to login/register, but after completing auth they always landed on the home page — losing their place.

### Root Cause Analysis

```mermaid
flowchart TD
    A[User on /sessions/42] --> B{Clicks Book}
    B --> C["/auth/login?next=/sessions/42"]
    C --> D{login_page GET}
    D -- "BUG: next param\nnot passed to template" --> E[login.html\nno next value]

    F["/auth/register?next=/sessions/42"] --> G{register_page GET}
    G -- "BUG: same issue" --> H[register.html\nno next value\nno hidden input\nno aware login link]

    I[register POST] -- "BUG: only checks\nspeaker_invite_next\nin session" --> J[Redirects to /]

    style D fill:#7f1d1d,stroke:#991b1b,color:#fca5a5
    style G fill:#7f1d1d,stroke:#991b1b,color:#fca5a5
    style I fill:#7f1d1d,stroke:#991b1b,color:#fca5a5
```

### Fixed Flow

```mermaid
flowchart TD
    A[User on /sessions/42] --> B[Clicks Book]
    B --> C["/auth/login?next=/sessions/42"]
    C --> D[login_page GET\nextracts next=\npasses to template]
    D --> E[login.html\nhidden input + next-aware\nCreate Account link]
    E --> F{User logs in}
    F --> G[Redirect to /sessions/42 ✓]

    H[User clicks Create Account] --> I["/auth/register?next=/sessions/42"]
    I --> J[register_page GET\nextracts next=\npasses to template]
    J --> K[register.html\nhidden input\nnext-aware Login link]
    K --> L{User registers}
    L --> M[Redirect to /sessions/42 ✓]

    style G fill:#14532d,stroke:#16a34a,color:#86efac
    style M fill:#14532d,stroke:#16a34a,color:#86efac
```

### Files Changed
| File | Change |
|------|--------|
| `app/routers/auth.py` | `login_page` GET extracts `?next=` and passes to template |
| `app/routers/auth.py` | `register_page` GET does the same |
| `app/routers/auth.py` | `register` POST checks form `next` → query param → session → `/` |
| `app/routers/auth.py` | Validation failure redirect preserves `?next=` |
| `app/templates/auth/register.html` | Hidden `<input name="next">` added to form |
| `app/templates/auth/register.html` | "Already have an account?" link is `next=`-aware |

---

## 3. Platform Logo on Invoices

### Architecture

A new `SiteSetting` key-value model was introduced to allow runtime configuration of platform branding without code changes or server restarts.

```mermaid
erDiagram
    SiteSetting {
        string key PK
        text value
    }
```

```mermaid
flowchart LR
    A[Admin\n/admin/settings] -- "POST platform_logo_url\ncompany_name etc." --> B[(site_settings\ntable)]
    B --> C[invoice.py\ngenerate_invoice_pdf]
    C -- "requests.get(logo_url)\nReportLab Image embed" --> D[PDF Invoice\nwith logo header]

    style D fill:#1e293b,stroke:#00d4ff,color:#e2e8f0
```

**Invoice header layout:**
```
┌──────────────────────────────────────────────────┐
│ [LOGO]  TechTrek Pvt Ltd          TAX INVOICE   │
│         Bangalore, Karnataka      #INV-20260313  │
│         GSTIN: ... | PAN: ...     Date: 13 Mar   │
│─────────────────────────────────────────────────│
```

### Files Changed
| File | Change |
|------|--------|
| `app/models/site_setting.py` | **New** — key/value DB model |
| `app/models/__init__.py` | Registered `SiteSetting` for `create_all` |
| `app/routers/admin.py` | `GET/POST /admin/settings` routes + `_load_settings()` helper |
| `app/templates/admin/settings.html` | **New** — settings form with logo preview |
| `app/templates/admin/base_admin.html` | "Settings" link in sidebar nav |
| `app/services/invoice.py` | Accepts `db`, loads settings from DB, embeds logo via ReportLab |
| `app/routers/booking.py` | Passes `db` to `generate_invoice_pdf()` |
| `app/routers/admin.py` | Passes `db` to `generate_invoice_pdf()` |

---

## 4. Recordings Page — Ticket Holders Only

### Problem
The `/recordings` page showed all public session recordings to anyone, including unauthenticated users and people who never bought a ticket.

### Access Control Logic

```mermaid
flowchart TD
    A[GET /recordings] --> B{Signed in?}
    B -- No --> C[Flash: Sign in to view recordings]
    C --> D[Redirect to /auth/login?next=/recordings]
    B -- Yes --> E[Query sessions with\npublic recordings]
    E --> F[Intersect with sessions\nwhere user has\npayment_status == 'paid']
    F --> G{Any results?}
    G -- Yes --> H[Show recordings grid]
    G -- No --> I[Show empty state\n"No recordings yet\nfor your bookings"]

    style D fill:#1e293b,stroke:#f59e0b,color:#fde68a
    style H fill:#14532d,stroke:#16a34a,color:#86efac
```

### Files Changed
| File | Change |
|------|--------|
| `app/routers/public.py` | `recordings_page()` — auth gate + paid-booking filter |

---

## 5. Terms & Conditions at Checkout

### Problem
Users could complete payment with no acknowledgement of refund policy or platform terms — a legal and operational risk.

### Implementation

```mermaid
sequenceDiagram
    participant U as User
    participant P as Checkout Page
    participant R as Razorpay

    U->>P: Arrives at /booking/checkout/{id}
    P-->>U: Renders with Pay button DISABLED
    U->>P: Checks "I agree to T&C" checkbox
    P-->>U: Pay button ENABLED
    U->>P: Clicks Pay
    P->>R: Creates order via /booking/create-order
    R-->>U: Opens payment modal
```

**Checkout UI:**
```
┌─────────────────────────────────────────────────┐
│  ☐  I agree to the Terms & Conditions and       │
│     understand that tickets are non-refundable  │
│     after payment.                              │
│                                                 │
│  [ Pay ₹1,333 ]  ← disabled until checked      │
└─────────────────────────────────────────────────┘
```

### Files Changed
| File | Change |
|------|--------|
| `app/templates/booking/checkout.html` | T&C checkbox + JS enable/disable logic |
| `app/templates/public/terms.html` | **New** — `/terms` page with boilerplate legal content |
| `app/routers/public.py` | `GET /terms` route |

---

## 6. Custom Seat Type Icon Grid Picker

### Problem
The admin icon field for custom seat types was a free-text input (`fa-star`, `fa-crown` etc.) with no visual feedback and no consistency.

### Before → After

```
BEFORE:                           AFTER:
┌──────────────────────┐         ┌───────────────────────────────────┐
│ Icon Class:          │         │ Icon:                             │
│ [fa-star___________] │         │ ⭐  👑  💎  🎭  🌟  🔥  🎪  🏆  │
└──────────────────────┘         │ ♿  🎟️  💺  🎯  🌙  ❄️  🌈  🎵  │
                                 │ 🏅  💡  🔑  🎨                   │
                                 │                                   │
                                 │ [✕ No icon]                       │
                                 │ Selected: 👑                      │
                                 └───────────────────────────────────┘
```

The selected icon is stored as the emoji character in `seat_types.icon` (fits in `VARCHAR(30)`).

### Icon Propagation

```mermaid
flowchart LR
    A[Admin selects 👑\nin icon grid] --> B[(seat_types.icon\n= '👑')]
    B --> C[Seat legend\nin select_seat.html\nshows colour + 👑 name]
    B --> D[Seat cell in\nseat-picker.js\nrenders 👑 on coloured bg]
```

### Files Changed
| File | Change |
|------|--------|
| `app/templates/admin/seat_type_form.html` | Replaced text input with emoji grid + JS tile selector |
| `app/templates/booking/select_seat.html` | Legend renders icon emoji next to type name |
| `app/static/js/seat-picker.js` | Custom seat cells render the icon emoji |

---

## 7. Custom Seat Type Pricing

### Problem
Custom seat types (e.g. "Premium", "Balcony") had no pricing — they always fell back to the session's standard price. They were also not visible on the session detail page.

### Data Model Change

```mermaid
erDiagram
    SeatType {
        int id PK
        string name
        string colour
        string icon
        numeric price "NEW — nullable"
        boolean is_custom
    }
    LectureSession {
        int id PK
        numeric price
        numeric price_vip
        numeric price_accessible
        numeric processing_fee_pct
    }
    Seat {
        int id PK
        string seat_type "e.g. custom_3"
        int auditorium_id FK
    }
    SeatType ||--o{ Seat : "identified by custom_{id}"
    LectureSession ||--o{ Seat : "via auditorium"
```

### Pricing Resolution (booking calculation)

```mermaid
flowchart TD
    A[_price_for_seat\nlecture, seat_type, db] --> B{seat_type == vip?}
    B -- Yes --> C[lecture.price_vip]
    B -- No --> D{seat_type == accessible?}
    D -- Yes --> E[lecture.price_accessible]
    D -- No --> F{starts with custom_?}
    F -- Yes --> G[Lookup SeatType by id\nfrom DB]
    G --> H{SeatType.price\nis set?}
    H -- Yes --> I[SeatType.price ✓]
    H -- No --> J[lecture.price fallback]
    F -- No --> J

    style I fill:#14532d,stroke:#16a34a,color:#86efac
    style J fill:#1e293b,stroke:#475569,color:#94a3b8
```

### Session Detail Price Display

```
Starting from  ₹500 per seat
  VIP · ₹900    Accessible · ₹400    👑 Premium · ₹750    🎟️ Balcony · ₹600
```

### Files Changed
| File | Change |
|------|--------|
| `app/models/seat_type.py` | Added `price NUMERIC(10,2)` column |
| `app/templates/admin/seat_type_form.html` | Price input field added |
| `app/routers/admin.py` | Saves price in `seat_type_create` and `seat_type_update` |
| `app/routers/public.py` | `session_detail()` queries custom types for the auditorium |
| `app/templates/public/session_detail.html` | Custom type price pills in pricing section |
| `app/services/booking.py` | `_price_for_seat()` looks up custom type DB price |
| `app/routers/booking.py` | `custom_types_data` includes `price`; passes `db` to `_seat_price` |
| `app/static/js/seat-picker.js` | `priceForType()` uses `ct.price` for live summary |

---

## Database Changes

```mermaid
flowchart LR
    subgraph New Tables
        A[site_settings\nkey PK / value]
        B[seat_types\nnow includes price col]
    end
    subgraph New Columns
        C[lecture_sessions\n+ processing_fee_pct]
        D[seat_types\n+ price]
    end
```

All migrations are handled in `app/main.py` via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` inside the startup `with engine.connect()` block, consistent with the project's existing migration pattern.

| Table | Column Added | Type |
|-------|-------------|------|
| `lecture_sessions` | `processing_fee_pct` | `NUMERIC(5,2) DEFAULT 0` |
| `seat_types` | `price` | `NUMERIC(10,2)` |
| `site_settings` | *(new table)* | `key VARCHAR(100) PK, value TEXT` |

---

## Full Change File Index

| File | Status | Feature(s) |
|------|--------|------------|
| `app/models/session.py` | Modified | Processing fee |
| `app/models/seat_type.py` | Modified | Custom pricing |
| `app/models/site_setting.py` | **Created** | Platform logo |
| `app/models/__init__.py` | Modified | Register SiteSetting |
| `app/main.py` | Modified | DB migrations |
| `app/routers/auth.py` | Modified | Login redirect |
| `app/routers/admin.py` | Modified | Fee, logo settings, seat type price |
| `app/routers/booking.py` | Modified | Fee calc, T&C, custom pricing |
| `app/routers/public.py` | Modified | Recordings gate, session detail, /terms |
| `app/services/invoice.py` | Modified | Logo in PDF |
| `app/services/booking.py` | Modified | Custom type price lookup |
| `app/static/js/seat-picker.js` | Modified | Icon render, custom price |
| `app/templates/admin/base_admin.html` | Modified | Settings nav link |
| `app/templates/admin/session_form.html` | Modified | Processing fee input |
| `app/templates/admin/seat_type_form.html` | Modified | Icon grid, price input |
| `app/templates/admin/settings.html` | **Created** | Platform settings page |
| `app/templates/auth/login.html` | *(already handled next=)* | Login redirect |
| `app/templates/auth/register.html` | Modified | Login redirect |
| `app/templates/booking/checkout.html` | Modified | Fee display, T&C checkbox |
| `app/templates/booking/select_seat.html` | Modified | Icon in legend |
| `app/templates/public/session_detail.html` | Modified | Custom type price pills |
| `app/templates/public/terms.html` | **Created** | T&C page |

---

*Generated 13 March 2026 — TechTrek internal development log*

# SaaS Platform Architecture

> **Last updated:** 2026-03-08
> This document is updated incrementally after every major change.

## Overview

A multi-tenant SaaS marketplace platform where business owners can deploy isolated instances of pluggable applications. Each tenant gets its own PostgreSQL schema inside a shared Neon database and runs independently. End users (clients/followers) discover businesses, follow them, and interact through app-specific interfaces.

---

## Technology Stack

| Layer | Technology |
|---|---|
| **Backend** | Flask 3.1, Python 3.14 |
| **Platform DB** | PostgreSQL on Neon (shared `neondb`, SQLAlchemy 2.0 + psycopg2) |
| **Tenant DB** | PostgreSQL on Neon (schema-per-tenant, psycopg 3.3 with `dict_row`) |
| **Auth** | JWT (platform level), Flask sessions (app level), SSO auto-login bridge |
| **Frontend** | Bootstrap 5.3, Font Awesome 6.5, vanilla JS, Fabric.js (canvas editor) |
| **i18n** | Client-side JSON dictionaries (EN, FR, AR), RTL support, `data-i18n` attributes |
| **AI** | OpenAI GPT-4o-mini (ad copy, image analysis), DALL-E 3 (image generation) |
| **Payments** | Stripe Connect (platform fee model) |
| **Deployment** | Gunicorn, Heroku-ready (Procfile), dev server on LAN (`0.0.0.0:5000`) |
| **File uploads** | Werkzeug `secure_filename`, 20MB limit, stored in `static/uploads/` |

---

## Architecture Layers

```
┌──────────────────────────────────────────────────────────────────┐
│  PLATFORM LAYER (core/)                                          │
│                                                                  │
│  Responsibilities:                                               │
│  - User registration & login (JWT)                               │
│  - Unified home page (role-aware: owner vs client views)         │
│  - App marketplace (browse, deploy, manage apps)                 │
│  - Tenant provisioning (create isolated schemas per business)    │
│  - Cross-tenant search (businesses + items)                      │
│  - Stripe billing & subscription management                      │
│  - Platform admin dashboard                                      │
│                                                                  │
│  Database: Neon PostgreSQL → public schema (SQLAlchemy)          │
│  Tables: users, app_definitions, tenants,                        │
│          tenant_memberships, subscriptions                        │
│                                                                  │
│  Auth: JWT tokens (Authorization header or httpOnly cookie)      │
│  Roles: platform_admin, business_owner, client                   │
└──────────────────┬───────────────────────────────────────────────┘
                   │
                   │ provisions & manages
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│  TENANT LAYER (apps/)                                            │
│                                                                  │
│  Each tenant is an isolated instance of a pluggable app.         │
│  Accessed via: /t/<tenant_slug>/<app_type>/                      │
│                                                                  │
│  Apps:                                                           │
│  - MyFOMO   /t/<slug>/myfomo/   — Social commerce & advertising │
│  - School   /t/<slug>/school/   — Arabic school management       │
│  - Barber   /t/<slug>/barber/   — Barbershop management          │
│  - Shop     /t/<slug>/shop/     — E-commerce storefront          │
│                                                                  │
│  Database: Neon PostgreSQL → schema "tenant_<slug>" (psycopg 3)  │
│  Each app has its OWN users table inside its tenant schema       │
│                                                                  │
│  Auth: Flask session, per-app keys (e.g. myfomo_user_id)         │
│  SSO: Platform JWT cookie auto-logs into tenant apps             │
└──────────────────────────────────────────────────────────────────┘
```

---

## Multi-Tenancy Model

### Schema-per-Tenant (PostgreSQL)
Each tenant gets a dedicated PostgreSQL **schema** inside the single Neon `neondb` database. This avoids `CREATE DATABASE` (unsupported by Neon's pooler) while providing full data isolation.

```
neondb (Neon database)
├── public           → Platform tables (SQLAlchemy): users, tenants, follows
├── tenant_halalio   → MyFOMO tenant: posts, users, bookings, store_settings, ...
├── tenant_niro      → School tenant: users, teachers, classes, students, ...
└── tenant_xxx       → Each new tenant gets its own schema
```

**Slug → Schema mapping:** `al-noor-academy` → `tenant_al_noor_academy`

### Connection Management
- **Platform DB:** SQLAlchemy connection pool (`psycopg2`, pool_size=5, pool_pre_ping=True)
- **Tenant DB:** Direct `psycopg` (v3) connections with `dict_row` factory
- Connections cached on Flask's `g` object (one per request per tenant)
- **Teardown handler** (`close_all_connections`) closes all psycopg connections after every request to prevent pool exhaustion
- `connect_timeout=10` on all connections
- IPv4 resolution enforced in `db_manager.py` (fixes IPv6 routing issues with Neon)

### URL Routing
All tenant app routes are prefixed: `/t/<tenant_slug>/<app_type>/`
- The `tenant_slug` is extracted from the URL by Flask
- Every route function receives `tenant_slug` as a parameter
- The slug resolves to the correct PostgreSQL schema

---

## Authentication Model (Dual Auth + SSO Bridge)

### Platform Auth
- **Location:** `core/auth/routes.py`
- **Database:** Platform DB → `users` table (SQLAlchemy)
- **Mechanism:** JWT token (localStorage + httpOnly cookie)
- **Roles:** `platform_admin`, `business_owner`, `client`
- **Endpoints:** `/api/auth/register`, `/api/auth/login`, `/api/auth/me`, `/api/auth/logout`

### App-Level Auth
- **Location:** Each app's `routes.py` (e.g. `apps/myfomo/routes.py`)
- **Database:** Tenant DB → `users` table (psycopg, separate from platform users)
- **Mechanism:** Flask session keys prefixed per-app (e.g. `myfomo_user_id`, `school_user_id`)
- **Roles vary per app:**
  - MyFOMO: `admin`, `follower`
  - School: `super_admin`, `local_admin`, `teacher`, `student`
  - Barber: `admin`, `staff`
  - Shop: `admin`, `staff`

### SSO Auto-Login Bridge
When a platform user (with JWT cookie) visits a tenant app URL:
1. `_sso_auto_login(tenant_slug)` reads the JWT cookie
2. Decodes the platform email from the JWT
3. Looks up the user in the tenant's `users` table
4. If found, sets the app-level session automatically
5. Redirects to the appropriate dashboard (admin → dashboard, follower → store)

This allows platform clients to seamlessly access followed businesses without separate logins.

### Cross-Tenant Follows (MyFOMO)
- Platform-level `follows` table in public schema: `(user_email, tenant_slug)`
- When a client follows a business, a row is inserted via `get_follows_db()`
- The platform home page queries this table to show all followed businesses

---

## Directory Structure

```
platform/
├── main.py                          # Entry point, IPv4 fix, Flask app factory
├── config.py                        # Dev/Prod/Test config (env vars)
├── requirements.txt                 # Python dependencies
├── .env                             # Environment variables (secrets, DB URIs)
├── ARCHITECTURE.md                  # This file
│
├── core/                            # Platform-level modules
│   ├── __init__.py                  # App factory (create_app), teardown registration
│   ├── extensions.py                # Flask extensions (db, migrate, mail, cache, csrf)
│   ├── models.py                    # Platform models (User, Tenant, AppDefinition,
│   │                                #   TenantMembership, Subscription)
│   ├── auth/                        # Platform authentication (JWT)
│   │   ├── __init__.py              # Blueprint: url_prefix="/api/auth"
│   │   └── routes.py                # register, login, me, logout, auth_required decorator
│   ├── marketplace/                 # App marketplace & tenant CRUD
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── portal/                      # Unified home, search, dashboard
│   │   ├── __init__.py              # Blueprint: no prefix
│   │   └── routes.py                # /home, /api/home-data, /api/search, /dashboard
│   ├── admin/                       # Platform admin panel
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── stripe/                      # Stripe Connect billing
│   │   ├── __init__.py
│   │   └── routes.py
│   └── tenants/                     # Multi-tenancy infrastructure
│       ├── __init__.py
│       ├── service.py               # Tenant provisioning logic
│       └── db_manager.py            # Schema-per-tenant connections, IPv4 resolution,
│                                    #   teardown handler, platform connection
│
├── apps/                            # Pluggable application modules
│   ├── __init__.py                  # AppRegistry, discover_apps()
│   ├── base.py                      # BaseApp abstract class
│   ├── myfomo/                      # Social commerce / advertising app
│   │   ├── __init__.py              # MyFomoApp class
│   │   ├── routes.py                # ~1170 lines: posts, bookings, events, analytics,
│   │   │                            #   store settings, AI image/copy generation
│   │   ├── db_utils.py              # get_myfomo_db(), get_follows_db(), schema setup
│   │   ├── ai_utils.py              # OpenAI integration (GPT-4o-mini, DALL-E 3)
│   │   └── models.py
│   ├── school/                      # Arabic school management app
│   │   ├── __init__.py              # SchoolApp class
│   │   ├── routes.py                # ~1900 lines: full school management
│   │   ├── routes_raw.py            # Legacy raw SQL routes
│   │   ├── routes_super_badges.py   # Super badges system
│   │   ├── db_utils.py              # get_school_db(), schema setup
│   │   └── models.py
│   ├── barber/                      # Barbershop management app
│   │   ├── __init__.py
│   │   ├── routes.py                # Services, staff, clients, appointments, hours
│   │   ├── db_utils.py
│   │   └── models.py
│   └── shop/                        # E-commerce storefront app
│       ├── __init__.py
│       ├── routes.py                # Categories, products, orders, inventory
│       ├── db_utils.py
│       └── models.py
│
├── templates/
│   ├── auth/
│   │   ├── entry.html               # Combined login/register (landing page at /)
│   │   ├── login.html               # Legacy login page
│   │   └── register.html            # Legacy register page
│   ├── dashboard/
│   │   ├── home.html                # Unified platform home (role-aware, search, categories)
│   │   ├── portal.html              # Client portal
│   │   └── owner.html               # Owner dashboard
│   ├── myfomo/
│   │   ├── dashboard.html           # Admin: post/event management, Fabric.js text editor,
│   │   │                            #   AI image generation, store settings, analytics
│   │   ├── store.html               # Follower: browse posts, book items, profile
│   │   ├── explore.html             # Public: preview store, follow button
│   │   └── home.html                # Follower hub: all followed businesses by category
│   ├── school/
│   │   └── dashboard.html           # School management UI
│   ├── barber/
│   │   └── dashboard.html           # Barber management UI
│   ├── shop/
│   │   └── dashboard.html           # Shop management UI
│   └── marketplace/
│       └── app_detail.html          # App detail page
│
├── static/
│   ├── style.css                    # Global styles
│   ├── i18n/                        # Internationalization
│   │   ├── i18n.js                  # Client-side i18n module (data-i18n, i18n.t(),
│   │   │                            #   locale switcher, RTL auto-detection)
│   │   ├── en.json                  # English translations (~250 keys)
│   │   ├── fr.json                  # French translations
│   │   ├── ar.json                  # Arabic translations
│   │   └── rtl.css                  # RTL overrides for Arabic
│   └── uploads/                     # User-uploaded files (logos, post images)
│       └── myfomo/<tenant_slug>/
│
└── instance/                        # (Legacy — SQLite was replaced by Neon PostgreSQL)
```

---

## Key Data Flows

### 1. User Registration & Login
```
User visits / (entry.html)
  → Fills login or register form
  → POST /api/auth/login or /api/auth/register
    → Server validates, creates JWT token
    → Token stored in localStorage + httpOnly cookie
    → Redirect: platform_admin → /admin, others → /home
```

### 2. Platform Home Page
```
GET /home → dashboard/home.html
  → JS reads token from localStorage
  → GET /api/home-data (Authorization: Bearer <token>)
    → Server checks user role:
      → business_owner: returns owned tenants with logos/colors
      → client: returns followed businesses (memberships + follows table)
    → JS renders business cards grouped by category
    → Category sidebar for navigation
    → Search bar (clients) for discovering businesses/items
```

### 3. Client Follows a Business (MyFOMO)
```
Client discovers business via search → visits /t/<slug>/myfomo/explore
  → Sees public posts (no login required)
  → Clicks "Follow" button
    → POST /t/<slug>/myfomo/api/follow (Authorization: Bearer <token>)
      → Server decodes JWT, creates user in tenant DB
      → Inserts row in platform follows table
      → Sets myfomo session
    → Redirect to /t/<slug>/myfomo/home (follower hub)
```

### 4. Business Owner Creates a Post (MyFOMO)
```
Owner visits /t/<slug>/myfomo/ → auto-redirects to dashboard
  → Uploads product image
  → (Optional) AI analyzes image → generates ad copy & edited image
  → (Optional) Uses Fabric.js canvas editor for text overlays
  → POST /t/<slug>/myfomo/api/posts
    → Saves post with original_image_path + edited image_path
    → Sets status: draft or published
```

### 5. Tenant Provisioning
```
Owner logs in (platform JWT)
  → POST /api/tenants {name: "My Business", app_type: "myfomo"}
    → Creates Tenant record in platform DB
    → Creates PostgreSQL schema: tenant_my_business
    → Runs app-specific schema setup (tables created)
    → Seeds initial admin user in tenant DB
    → Creates TenantMembership (owner → tenant, role: admin)
    → Creates Subscription (plan: free)
  → Returns tenant slug
```

---

## Pluggable App System

### Adding a New App

1. Create `apps/new_app/` directory
2. Create `__init__.py` with a class inheriting from `BaseApp`:
   ```python
   class NewApp(BaseApp):
       name = "New App"
       slug = "new-app"
       description = "..."
       icon = "fas fa-icon"

       def setup_schema(self, engine): ...
       def get_blueprint(self): ...
   ```
3. Register in `apps/__init__.py` → `discover_apps()`
4. Create `routes.py`, `db_utils.py`, `models.py`, templates
5. The platform auto-discovers it on startup, registers the blueprint, and seeds the AppDefinition

### BaseApp Interface
- `name` — Human-readable name
- `slug` — Unique identifier (used in URLs and schema names)
- `description` — Shown in marketplace
- `icon` — Font Awesome icon class
- `setup_schema(engine)` — Create tables in tenant schema
- `get_blueprint()` — Return Flask Blueprint with all routes

---

## Internationalization (i18n)

### Architecture
- **Client-side only** — no server-side translation needed
- JSON dictionaries per language (`static/i18n/{locale}.json`)
- `i18n.js` module handles:
  - `data-i18n` attribute → sets `textContent`
  - `data-i18n-placeholder` → sets `placeholder`
  - `data-i18n-title` → sets `title`
  - `data-i18n-html` → sets `innerHTML`
  - `i18n.t(key)` → programmatic translation in JS
  - `i18n.setLocale(code)` → switch language
  - `i18n.renderSwitcher(container)` → dropdown UI
  - Auto-sets `dir="rtl"` for Arabic, loads `rtl.css`
  - Persists locale in `localStorage`

### Adding a New Language
1. Copy `en.json` → `xx.json`
2. Translate all ~250 keys
3. Add the locale to `SUPPORTED` array in `i18n.js`
4. If RTL, add to the RTL list in `i18n.js`

---

## Infrastructure Notes

### IPv4 Enforcement
Neon's hostname resolves to both IPv4 and IPv6. Many networks (especially home/LAN) don't route IPv6 properly, causing `psycopg.connect()` to hang indefinitely. Fixed at two levels:
1. **`main.py`:** Monkey-patches `socket.getaddrinfo` to prefer IPv4; injects `hostaddr=<IPv4>` into `DATABASE_URL` and `TENANT_DB_BASE_URI` for libpq/psycopg2
2. **`db_manager.py`:** Resolves hostname to IPv4 once and caches it; appends `hostaddr` to connection string for all psycopg3 connections

### Environment Variables (.env)
| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask secret key (JWT signing) |
| `DATABASE_URL` | Platform DB (Neon PostgreSQL) |
| `TENANT_DB_BASE_URI` | Tenant DB base (same Neon instance) |
| `OPENAI_API_KEY` | OpenAI API for AI features |
| `STRIPE_SECRET_KEY` | Stripe secret key |
| `STRIPE_PUBLISHABLE_KEY` | Stripe publishable key |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook verification |
| `JWT_EXPIRATION_HOURS` | Token expiry (default: 24) |
| `FLASK_ENV` | dev / prod |

---

## App-Specific Details

### MyFOMO Routes Summary
All routes under `/t/<tenant_slug>/myfomo/`:

| Category | Key Endpoints |
|---|---|
| Public | `/explore` (browse), `/api/public/posts` |
| Auth | `/login`, `/logout`, `/api/follow` |
| Navigation | `/` (index → redirect), `/home` (follower hub), `/store` (follower store) |
| Posts | `/api/posts` (CRUD), image upload, AI generation |
| Events | `/api/events` (CRUD) |
| Bookings | `/api/book/<post_id>`, `/api/bookings`, `/api/bookings/<id>/status` |
| Store Settings | `/api/settings/branding`, `/api/settings/profile`, logo upload |
| Analytics | `/api/analytics/track`, `/api/analytics/summary` |
| AI | `/api/ai/analyze-image`, `/api/ai/generate-copy`, `/api/ai/generate-image` |
| My Businesses | `/api/my-businesses` (follower's followed stores) |

### School Routes Summary
All routes under `/t/<tenant_slug>/school/` — full school management with ~50+ endpoints covering users, teachers, levels, classes, students, attendance, grades, exams, homework, events, announcements, curriculum, super badges, and support materials.

### Barber Routes Summary
All routes under `/t/<tenant_slug>/barber/` — services, staff, clients, appointments, and working hours CRUD.

### Shop Routes Summary
All routes under `/t/<tenant_slug>/shop/` — categories, products, orders, and inventory management.

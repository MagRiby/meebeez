# SaaS Platform Architecture

## Overview

A multi-tenant SaaS platform where business owners can deploy isolated instances of pluggable applications (School, Barber, etc.). Each tenant gets its own database and runs independently.

---

## Layers

```
┌──────────────────────────────────────────────────────────────┐
│  PLATFORM LAYER (core/)                                      │
│                                                              │
│  Responsibilities:                                           │
│  - Platform user registration & login (JWT)                  │
│  - App marketplace (browse & select apps)                    │
│  - Tenant provisioning (create isolated DBs per business)    │
│  - Tenant membership management                              │
│  - Subscription & billing tracking                           │
│                                                              │
│  Database: Platform DB (PostgreSQL)                           │
│  Tables: users, app_definitions, tenants,                    │
│          tenant_memberships, subscriptions                    │
│                                                              │
│  Auth: JWT tokens (Authorization header or cookie)           │
│  Roles: platform_admin, business_owner, client               │
└──────────────────┬───────────────────────────────────────────┘
                   │
                   │ provisions & manages
                   ▼
┌──────────────────────────────────────────────────────────────┐
│  TENANT LAYER (apps/)                                        │
│                                                              │
│  Each tenant is an isolated instance of a pluggable app.     │
│  Accessed via: /t/<tenant_slug>/<app_type>/                  │
│                                                              │
│  Examples:                                                   │
│  - /t/al-noor-academy/school/                                │
│  - /t/jeddah-barbers/barber/                                 │
│                                                              │
│  Database: One SQLite file per tenant                         │
│            (instance/tenants/<slug>.db)                       │
│                                                              │
│  Auth: Flask session, managed internally by each app         │
│  Each app has its OWN users table inside its tenant DB       │
└──────────────────────────────────────────────────────────────┘
```

---

## Authentication Model (Option A — Dual Auth)

There are two independent authentication systems. They do not share users or sessions.

### Platform Auth
- **Location:** `core/auth/routes.py`
- **Database:** Platform DB → `users` table
- **Mechanism:** JWT token (stored in localStorage or cookie)
- **Roles:** `platform_admin`, `business_owner`, `client`
- **Purpose:** Register on the platform, browse marketplace, create/manage tenants, join tenants
- **Endpoints:** `/api/auth/register`, `/api/auth/login`, `/api/auth/me`, `/api/auth/logout`

### App-Level Auth (e.g. School)
- **Location:** `apps/school/routes.py` → `/t/<slug>/school/login`
- **Database:** Tenant DB → `users` table (separate from platform users)
- **Mechanism:** Flask session keys prefixed with `school_`
- **Roles:** `super_admin`, `local_admin`, `teacher`, `student`
- **Purpose:** Manage the school internally — classes, students, grades, attendance
- **Session keys:** `school_user_id`, `school_role`, `school_username`, `school_teacher_id`, `school_tenant`

### Why Two Auth Systems
The school app was originally a standalone application. It manages its own users (teachers, students, admins) inside the tenant database. A business owner creates a tenant via the platform, then sets up internal users within the school app. End users (teachers, parents) log in directly at the school app URL without needing a platform account.

---

## Directory Structure

```
platform/
├── main.py                          # Entry point (Flask app factory)
├── config.py                        # Dev/Prod/Test configuration
├── requirements.txt                 # Python dependencies
├── Procfile                         # Heroku/production deployment
├── ARCHITECTURE.md                  # This file
│
├── core/                            # Platform-level modules
│   ├── __init__.py                  # App factory (create_app)
│   ├── extensions.py                # Flask extensions (db, migrate, mail, cache)
│   ├── models.py                    # Platform models (User, Tenant, AppDefinition, etc.)
│   ├── auth/                        # Platform authentication (JWT)
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── marketplace/                 # App marketplace & tenant CRUD
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── portal/                      # Client portal view
│   │   ├── __init__.py
│   │   └── routes.py
│   └── tenants/                     # Multi-tenancy infrastructure
│       ├── __init__.py
│       ├── service.py               # Tenant provisioning logic
│       └── db_manager.py            # PostgreSQL/SQLite DB operations
│
├── apps/                            # Pluggable application modules
│   ├── __init__.py                  # App registry & auto-discovery
│   ├── base.py                      # BaseApp abstract class
│   ├── school/                      # School management app
│   │   ├── __init__.py              # SchoolApp class
│   │   ├── models.py                # SQLAlchemy models (for PostgreSQL)
│   │   ├── routes.py                # All school routes (ported from arabicschool)
│   │   ├── auth_utils.py            # login_required decorator
│   │   ├── db_utils.py              # get_school_db(), init_school_db()
│   │   └── homework_utils.py        # File upload helpers
│   └── barber/                      # Barber shop app (placeholder)
│       ├── __init__.py
│       ├── models.py
│       └── routes.py
│
├── templates/                       # HTML templates
│   ├── base.html                    # Platform base layout
│   ├── landing.html                 # Marketplace homepage
│   ├── auth/                        # Platform auth pages
│   ├── dashboard/                   # Owner/client dashboards
│   ├── marketplace/                 # App detail pages
│   └── school/                      # School app templates
│
├── static/                          # Static assets (CSS, images)
│   ├── style.css
│   └── school/
│
├── uploads/                         # Homework file uploads (per class)
├── support_material/                # Level support material files
└── instance/
    └── tenants/                     # SQLite databases (one per tenant)
        ├── al-noor-academy.db
        └── another-school.db
```

---

## Data Flow

### 1. Business Owner Creates a Tenant

```
Owner logs in (platform JWT)
  → POST /api/tenants {name: "Al Noor Academy", app_type: "school"}
    → Platform creates Tenant record in platform DB
    → Platform creates SQLite file: instance/tenants/al-noor-academy.db
    → Platform runs school schema setup (all tables created)
    → Platform seeds initial super_admin user in tenant DB
    → Platform creates TenantMembership (owner → tenant, role: admin)
    → Platform creates Subscription (plan: free)
  → Returns tenant slug: "al-noor-academy"
```

### 2. School Admin Sets Up the School

```
Admin visits /t/al-noor-academy/school/login
  → Logs in with credentials seeded during provisioning
  → Creates local admins, teachers, levels, classes, students
  → All data stored in al-noor-academy.db (isolated)
```

### 3. Teacher Uses the School

```
Teacher visits /t/al-noor-academy/school/login
  → Logs in with credentials created by admin
  → Sees only classes assigned to them
  → Records attendance, grades, homework
  → All queries scoped to al-noor-academy.db
```

### 4. Parent/Student Views Abilities

```
Student visits /t/al-noor-academy/school/login
  → Logs in → redirected to student_abilities page
  → Sees grades, homework, super badges
  → Read-only view (no editing)
```

---

## Multi-Tenancy Model

### Database-per-Tenant
Each tenant gets a completely isolated SQLite database file. No data leaks between tenants. The tenant slug is part of every URL and is used to resolve the correct database.

### Connection Management
- `get_school_db(tenant_slug)` returns a SQLite connection for the tenant
- Connections are cached per-request using Flask's `g` object
- Connections are automatically closed at the end of each request
- WAL mode and foreign keys are enabled on every connection

### URL Routing
All tenant app routes are prefixed: `/t/<tenant_slug>/<app_type>/`
- The `tenant_slug` is extracted from the URL by Flask
- Every route function receives `tenant_slug` as a parameter
- The slug is used to open the correct database

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
4. Create routes, models, templates
5. The platform auto-discovers it on startup, registers the blueprint, and seeds the AppDefinition

### BaseApp Interface
- `name` — Human-readable name
- `slug` — Unique identifier (used in URLs and DB names)
- `description` — Shown in marketplace
- `icon` — Font Awesome icon class
- `setup_schema(engine)` — Create tables in tenant DB (PostgreSQL/SQLAlchemy)
- `setup_schema_sqlite(tenant_slug)` — Create tables in tenant DB (SQLite/raw SQL)
- `get_blueprint()` — Return Flask Blueprint with all routes

---

## School App Routes Summary

All routes under `/t/<tenant_slug>/school/`:

| Category | Endpoints |
|---|---|
| Auth | `login`, `logout`, `register_super_admin` |
| Dashboard | `/`, `/dashboard` |
| Local Admins | `api/local_admins` (CRUD + set_director) |
| Users | `create_user`, `list_users`, `update_user`, `delete_user`, `api/check_user_exists` |
| Teachers | `teachers` (GET/POST), `teachers/<id>` (PUT/DELETE) |
| Curriculum Groups | `curriculum_groups` (GET/POST), `curriculum_groups/<id>` (PUT/DELETE) |
| Curriculum Items | `curriculum_items/<group_id>` (GET), `curriculum_items` (POST), `curriculum_items/<id>` (PUT/DELETE) |
| Levels | `levels` (GET/POST), `delete_level/<id>`, `edit_level_name` |
| Classes | `classes` (GET/POST), `classes/<id>` (GET/PUT/DELETE) |
| Class Courses | `class_courses/<class_id>` (GET/POST), `class_courses/<class_id>/<item_id>` (DELETE) |
| Students | `students` (GET), `students/search`, `create_student`, `update_student/<id>` (PUT/POST), `students/<class_id>` (GET/POST), `students/<class_id>/<id>` (DELETE), `delete_student` |
| Student Card | `student_card/<id>` |
| Student Abilities | `student_abilities/<student_id>/<class_id>` (GET/POST) |
| Comments | `save_comment` |
| Events | `api/events/<class_id>` (GET), `api/events` (POST), `api/events/<id>` (PUT/DELETE) |
| Announcements | `api/class/<class_id>/announcement` (GET/POST) |
| Homework | `api/homework/list/<class_id>`, `api/homework` (POST), `api/homework/edit/<id>`, `api/homework/delete/<id>`, `uploads/class_<id>/<filename>` |
| Exams | `api/exams/<class_id>` (GET/POST), `api/exams/<id>` (PUT/DELETE) |
| Grades | `api/grades/<class_id>` (GET/POST) |
| Attendance | `attendance/<class_id>`, `api/attendance/<class_id>` (GET/POST) |
| Continuous Monitoring | `continuous_monitoring/<class_id>` |
| Super Badges | `api/super_badges` (CRUD), `api/super_badges/<id>/active` (PATCH) |
| Student Badges | `api/student/<id>/super_badges` (GET), `api/student/<id>/super_badges/<badge>/toggle`, `api/student/<id>/super_badges/batch_update`, `api/student/<id>/super_badges/notes` (GET/POST) |
| Support Material | `levels/<id>/support_material` (GET/POST), `support_material/<filename>`, `support_material/<id>` (PUT/DELETE) |

---

## Technology Stack

- **Backend:** Flask 3.1, SQLAlchemy 2.0, Flask-Migrate
- **Platform DB:** PostgreSQL (via psycopg)
- **Tenant DB:** SQLite (one file per tenant, WAL mode)
- **Auth:** JWT (platform), Flask sessions (apps)
- **Frontend:** Bootstrap 5.3, Font Awesome 6.5, vanilla JS
- **Deployment:** Gunicorn, Heroku-ready (Procfile)
- **File uploads:** Werkzeug secure_filename, 20MB limit

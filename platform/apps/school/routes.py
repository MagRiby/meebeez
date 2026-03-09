"""School app routes – ported from arabicschool/main.py.

Every route is scoped under /t/<tenant_slug>/school/ and uses the
tenant-aware get_school_db() helper instead of a hardcoded DB path.
Session keys are prefixed with ``school_`` so they don't collide with
the platform-level session.
"""

import os
import uuid
import json
import time
import datetime as _dt
from datetime import datetime, timedelta
from functools import wraps

import jwt as pyjwt
from flask import (
    Blueprint, request, jsonify, session, redirect, url_for,
    render_template, send_from_directory, current_app, g,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from apps.school.db_utils import get_school_db
from apps.school.homework_utils import save_homework_files

# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------
school_bp = Blueprint(
    "school",
    __name__,
    url_prefix="/t/<tenant_slug>/school",
    template_folder=os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "templates", "school",
    ),
    static_folder=os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "static", "school",
    ),
    static_url_path="/static/school",
)

# ---------------------------------------------------------------------------
# SSO helper
# ---------------------------------------------------------------------------

def _sso_auto_login(tenant_slug):
    """Auto-login using the platform JWT cookie. Returns True on success."""
    token = request.cookies.get("token")
    if not token:
        return False
    try:
        payload = pyjwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
        email = payload.get("email")
        if not email:
            return False
    except Exception:
        return False
    db = get_school_db(tenant_slug)
    user = db.execute("SELECT * FROM users WHERE username=%s", (email,)).fetchone()
    if not user:
        return False
    session["school_user_id"] = user["id"]
    session["school_role"] = user["role"]
    session["school_username"] = user["username"]
    session["school_tenant"] = tenant_slug
    return True


# ---------------------------------------------------------------------------
# Auth decorator (tenant-scoped session)
# ---------------------------------------------------------------------------

def login_required(*roles):
    """Require the user to be logged into the school tenant app."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            tenant_slug = kwargs.get("tenant_slug", "")
            if "school_user_id" not in session or session.get("school_tenant") != tenant_slug:
                if not _sso_auto_login(tenant_slug):
                    return redirect("/")
            if roles and session.get("school_role") not in roles:
                return "Unauthorized", 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _none_if_empty(val):
    return val if val not in ("", None, "null", "undefined") else None


def _int_or_none(val):
    return int(val) if val not in (None, "", "null", "undefined") else None


# Column whitelists for safe dynamic UPDATE queries
_TEACHER_COLUMNS = frozenset({"phone", "notes", "alerts", "name"})
_CLASS_COLUMNS = frozenset({
    "name", "level_id", "teacher_id", "backup_teacher_id",
    "dawra1_pub_start", "dawra1_pub_end", "dawra2_pub_start", "dawra2_pub_end",
    "dawra3_pub_start", "dawra3_pub_end", "year_pub_start", "year_pub_end",
})
_STUDENT_COLUMNS = frozenset({
    "email", "phone", "notes", "alerts", "name",
    "date_of_birth", "secondary_email", "sex",
})


def _safe_update(cursor, table, allowed_columns, field_values, where_clause, where_params):
    """Build and execute a safe UPDATE with whitelisted column names."""
    updates, params = [], []
    for field, val in field_values:
        if field not in allowed_columns:
            raise ValueError(f"Invalid column: {field}")
        if val is not None:
            updates.append(f"{field} = %s")
            params.append(val)
    if updates:
        params.extend(where_params)
        cursor.execute(f"UPDATE {table} SET {', '.join(updates)} {where_clause}", params)
    return len(updates) > 0


def _school_info(tenant_slug):
    """Return school_info dict (name, logo) from a JSON file if present."""
    info_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "instance", "tenants", f"{tenant_slug}_school_info.json",
    )
    if os.path.exists(info_path):
        with open(info_path, encoding="utf-8") as f:
            return json.load(f)
    return {"name": "", "logo": "school_logo.png"}


def _upload_folder():
    base = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "uploads",
    )
    os.makedirs(base, exist_ok=True)
    return base


def _support_material_folder():
    base = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "support_material",
    )
    os.makedirs(base, exist_ok=True)
    return base


# ---------------------------------------------------------------------------
# Teardown – close cached tenant DB connections
# ---------------------------------------------------------------------------
@school_bp.teardown_app_request
def _close_school_dbs(exc):
    keys = [k for k in g.__dict__ if k.startswith("school_db_")]
    for k in keys:
        conn = g.__dict__.pop(k, None)
        if conn is not None:
            conn.close()


# ===================================================================
#  AUTH ROUTES
# ===================================================================

@school_bp.route("/register_super_admin", methods=["GET", "POST"])
def register_super_admin(tenant_slug):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT * FROM users WHERE role='super_admin'")
    if c.fetchone():
        return "Super admin already exists!", 403
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        password_hash = generate_password_hash(password)
        c.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) RETURNING id",
            (username, password_hash, "super_admin"),
        )
        db.commit()
        return redirect(url_for("school.school_login", tenant_slug=tenant_slug))
    return render_template("register_super_admin.html", tenant_slug=tenant_slug)


@school_bp.route("/login", methods=["GET", "POST"])
def school_login(tenant_slug):
    error = None
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        db = get_school_db(tenant_slug)
        c = db.cursor()
        c.execute("SELECT id, password_hash, role FROM users WHERE username=%s", (username,))
        user = c.fetchone()
        if user and check_password_hash(user[1], password):
            session["school_user_id"] = user[0]
            session["school_role"] = user[2]
            session["school_username"] = username
            session["school_tenant"] = tenant_slug
            if user[2] == "teacher":
                c.execute("SELECT id FROM teachers WHERE user_id=%s", (user[0],))
                teacher_row = c.fetchone()
                if teacher_row:
                    session["school_teacher_id"] = teacher_row[0]
            if user[2] == "student":
                c.execute(
                    """SELECT s.id, s.class_id, s.name, c.name as class_name,
                              l.name as level_name, s.email
                       FROM students s
                       LEFT JOIN classes c ON s.class_id = c.id
                       LEFT JOIN levels l ON c.level_id = l.id
                       WHERE s.email=%s""",
                    (username,),
                )
                students = c.fetchall()
                if not students:
                    error = "Student record not found for this user."
                    return render_template("login.html", error=error, tenant_slug=tenant_slug)
                students_with_class = [s for s in students if s[1] is not None]
                if len(students_with_class) == 1:
                    sid, cid = students_with_class[0][:2]
                    return redirect(
                        url_for("school.student_abilities", tenant_slug=tenant_slug,
                                student_id=sid, class_id=cid)
                    )
                elif len(students_with_class) > 1:
                    student_cards = [
                        {
                            "id": s[0], "class_id": s[1], "name": s[2],
                            "class_name": s[3] or "\u0628\u062f\u0648\u0646 \u0635\u0641",
                            "level_name": s[4] or "", "username": s[5],
                        }
                        for s in students_with_class
                    ]
                    return render_template("select_student.html", students=student_cards, tenant_slug=tenant_slug)
                else:
                    error = "You are not assigned to a class yet. Please contact admin."
                    return render_template("login.html", error=error, tenant_slug=tenant_slug)
            return redirect(url_for("school.dashboard", tenant_slug=tenant_slug))
        error = "Invalid credentials"
        return render_template("login.html", error=error, tenant_slug=tenant_slug)
    return render_template("login.html", tenant_slug=tenant_slug)


@school_bp.route("/logout")
def school_logout(tenant_slug):
    for key in list(session.keys()):
        if key.startswith("school_"):
            session.pop(key, None)
    return redirect("/signout")


# ===================================================================
#  DASHBOARD
# ===================================================================

@school_bp.route("/dashboard")
@login_required("super_admin", "local_admin", "teacher")
def dashboard(tenant_slug):
    school_info = _school_info(tenant_slug)
    return render_template(
        "dashboard.html",
        role=session.get("school_role"),
        username=session.get("school_username"),
        school_info=school_info,
        tenant_slug=tenant_slug,
    )


@school_bp.route("/")
def index(tenant_slug):
    if "school_user_id" in session and session.get("school_tenant") == tenant_slug:
        return redirect(url_for("school.dashboard", tenant_slug=tenant_slug))
    if _sso_auto_login(tenant_slug):
        return redirect(url_for("school.dashboard", tenant_slug=tenant_slug))
    # If coming from platform (has JWT cookie), go home; otherwise show school login
    if request.cookies.get("token"):
        return redirect("/home")
    return redirect(url_for("school.school_login", tenant_slug=tenant_slug))


# ===================================================================
#  LOCAL ADMIN MANAGEMENT
# ===================================================================

@school_bp.route("/manage_local_admins")
@login_required("local_admin")
def manage_local_admins(tenant_slug):
    return render_template("manage_local_admins.html", tenant_slug=tenant_slug)


@school_bp.route("/api/local_admins", methods=["GET"])
@login_required("local_admin")
def api_list_local_admins(tenant_slug):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT id, username, name, is_director FROM users WHERE role='local_admin'")
    admins = [{"id": r[0], "username": r[1], "name": r[2], "is_director": r[3]} for r in c.fetchall()]
    return jsonify(admins)


@school_bp.route("/api/local_admins/<int:admin_id>/set_director", methods=["POST"])
@login_required("local_admin")
def set_local_admin_director(tenant_slug, admin_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("UPDATE users SET is_director=0 WHERE role='local_admin'")
    c.execute("UPDATE users SET is_director=1 WHERE id=%s AND role='local_admin'", (admin_id,))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/api/local_admins", methods=["POST"])
@login_required("local_admin")
def api_add_local_admin(tenant_slug):
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    name = data.get("name", "")
    if not name or not username or not password:
        return jsonify({"success": False, "error": "\u0627\u0644\u0631\u062c\u0627\u0621 \u062a\u0639\u0628\u0626\u0629 \u062c\u0645\u064a\u0639 \u0627\u0644\u062d\u0642\u0648\u0644"}), 400
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT id FROM users WHERE username=%s", (username,))
    if c.fetchone():
        return jsonify({"success": False, "error": "\u0627\u0633\u0645 \u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645 \u0645\u0633\u062a\u062e\u062f\u0645 \u0628\u0627\u0644\u0641\u0639\u0644"}), 400
    password_hash = generate_password_hash(password)
    c.execute("INSERT INTO users (name, username, password_hash, role) VALUES (%s, %s, %s, 'local_admin')",
              (name, username, password_hash))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/api/local_admins/<int:admin_id>", methods=["PUT"])
@login_required("local_admin")
def api_edit_local_admin(tenant_slug, admin_id):
    data = request.get_json()
    name = data.get("name")
    username = data.get("username")
    if not name or not username:
        return jsonify({"success": False, "error": "\u0627\u0644\u0631\u062c\u0627\u0621 \u062a\u0639\u0628\u0626\u0629 \u062c\u0645\u064a\u0639 \u0627\u0644\u062d\u0642\u0648\u0644"}), 400
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute('SELECT id FROM users WHERE id=%s AND role="local_admin"', (admin_id,))
    if not c.fetchone():
        return jsonify({"success": False, "error": "\u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f"}), 404
    c.execute("SELECT id FROM users WHERE username=%s AND id!=%s", (username, admin_id))
    if c.fetchone():
        return jsonify({"success": False, "error": "\u0627\u0633\u0645 \u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645 \u0645\u0633\u062a\u062e\u062f\u0645 \u0628\u0627\u0644\u0641\u0639\u0644"}), 400
    c.execute("UPDATE users SET name=%s, username=%s WHERE id=%s", (name, username, admin_id))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/api/local_admins/<int:admin_id>", methods=["DELETE"])
@login_required("local_admin")
def api_delete_local_admin(tenant_slug, admin_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute('SELECT id FROM users WHERE id=%s AND role="local_admin"', (admin_id,))
    if not c.fetchone():
        return jsonify({"success": False, "error": "\u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f"}), 404
    c.execute("DELETE FROM users WHERE id=%s", (admin_id,))
    db.commit()
    return jsonify({"success": True})


# ===================================================================
#  USER MANAGEMENT (super_admin)
# ===================================================================

@school_bp.route("/api/check_user_exists", methods=["GET", "POST"])
@login_required()
def api_check_user_exists(tenant_slug):
    if request.method == "POST":
        data = request.get_json(force=True)
        username = data.get("username")
    else:
        username = request.args.get("username")
    exists = False
    if username:
        db = get_school_db(tenant_slug)
        c = db.cursor()
        c.execute("SELECT 1 FROM users WHERE username=%s", (username,))
        exists = c.fetchone() is not None
    return jsonify({"exists": exists})


@school_bp.route("/create_user", methods=["POST"])
@login_required("super_admin")
def create_user(tenant_slug):
    data = request.json
    username = data["username"]
    password = data["password"]
    role = data["role"]
    if role not in ("local_admin", "teacher", "student"):
        return jsonify({"error": "Invalid role"}), 400
    password_hash = generate_password_hash(password)
    db = get_school_db(tenant_slug)
    c = db.cursor()
    try:
        c.execute(
            "INSERT INTO users (username, password_hash, role, created_by) VALUES (%s, %s, %s, %s) RETURNING id",
            (username, password_hash, role, session["school_user_id"]),
        )
        db.commit()
    except Exception:
        return jsonify({"error": "Username already exists"}), 400
    return jsonify({"success": True})


@school_bp.route("/list_users")
@login_required("super_admin")
def list_users(tenant_slug):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT id, username, role FROM users")
    users = [{"id": r[0], "username": r[1], "role": r[2]} for r in c.fetchall()]
    return jsonify(users)


@school_bp.route("/update_user", methods=["POST"])
@login_required("super_admin")
def update_user(tenant_slug):
    data = request.json
    user_id = data.get("id")
    new_role = data.get("role")
    new_password = data.get("password")
    if not user_id:
        return jsonify({"error": "Missing user id"}), 400
    db = get_school_db(tenant_slug)
    c = db.cursor()
    if new_role:
        c.execute("UPDATE users SET role=%s WHERE id=%s", (new_role, user_id))
    if new_password:
        password_hash = generate_password_hash(new_password)
        c.execute("UPDATE users SET password_hash=%s WHERE id=%s", (password_hash, user_id))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/delete_user", methods=["POST"])
@login_required("super_admin")
def delete_user(tenant_slug):
    data = request.json
    user_id = data.get("id")
    if not user_id:
        return jsonify({"error": "Missing user id"}), 400
    if user_id == session["school_user_id"]:
        return jsonify({"error": "Cannot delete yourself"}), 400
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute('SELECT COUNT(*) FROM users WHERE role="super_admin"')
    sa_count = c.fetchone()[0]
    c.execute("SELECT role FROM users WHERE id=%s", (user_id,))
    row = c.fetchone()
    if row and row[0] == "super_admin" and sa_count <= 1:
        return jsonify({"error": "Cannot delete the last super admin"}), 400
    c.execute("DELETE FROM users WHERE id=%s", (user_id,))
    db.commit()
    return jsonify({"success": True})


# ===================================================================
#  EVENTS / CALENDAR
# ===================================================================

@school_bp.route("/api/events/<int:class_id>", methods=["GET"])
def get_events(tenant_slug, class_id):
    db = get_school_db(tenant_slug)
    cur = db.execute("SELECT * FROM events WHERE class_id = %s", (class_id,))
    events = [dict(row) for row in cur.fetchall()]
    return jsonify(events)


@school_bp.route("/api/events", methods=["POST"])
def create_event(tenant_slug):
    data = request.json
    db = get_school_db(tenant_slug)
    recurrence = data.get("recurrence", "none")
    recurrence_end = data.get("recurrence_end")
    start = data["start"]
    end = data.get("end")

    if recurrence in ("weekly", "monthly") and recurrence_end:
        recurrence_group_id = f"rec_{int(time.time() * 1000)}"
        dt_start = datetime.fromisoformat(start)
        dt_end = datetime.fromisoformat(recurrence_end)

        def add_months(dt, n):
            month = dt.month - 1 + n
            year = dt.year + month // 12
            month = month % 12 + 1
            day = min(dt.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                               31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
            return dt.replace(year=year, month=month, day=day)

        events_to_create = []
        dt_current = dt_start
        delta = timedelta(weeks=1) if recurrence == "weekly" else None
        while dt_current <= dt_end:
            events_to_create.append(dt_current)
            dt_current = dt_current + delta if recurrence == "weekly" else add_months(dt_current, 1)

        event_rows = []
        for dt in events_to_create:
            cursor = db.execute(
                "INSERT INTO events (class_id, title, description, start, end, color, recurrence, recurrence_group_id, recurrence_end) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (data["class_id"], data["title"], data.get("description"), dt.isoformat(), end,
                 data.get("color"), recurrence, recurrence_group_id, recurrence_end),
            )
            event_rows.append(cursor.fetchone()[0])
        db.commit()
        cur_result = db.execute(
            "SELECT id, class_id, title, description, start, end, color, recurrence, recurrence_group_id, recurrence_end FROM events WHERE id=%s",
            (event_rows[0],),
        )
        row = cur.fetchone()
        return jsonify({"success": True, "event": dict(row) if row else {}}), 201
    else:
        cursor = db.execute(
            "INSERT INTO events (class_id, title, description, start, end, color, recurrence, recurrence_group_id, recurrence_end) VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, NULL)",
            (data["class_id"], data["title"], data.get("description"), start, end, data.get("color"), recurrence),
        )
        db.commit()
        cur_result = db.execute(
            "SELECT id, class_id, title, description, start, end, color, recurrence, recurrence_group_id, recurrence_end FROM events WHERE id=%s",
            (cursor.fetchone()[0],),
        )
        row = cur.fetchone()
        return jsonify({"success": True, "event": dict(row) if row else {}}), 201


@school_bp.route("/api/events/<int:event_id>", methods=["DELETE"])
def delete_event(tenant_slug, event_id):
    db = get_school_db(tenant_slug)
    if request.args.get("all") == "1":
        cur = db.execute("SELECT recurrence_group_id FROM events WHERE id=%s", (event_id,))
        row = cur.fetchone()
        if row and row[0]:
            db.execute("DELETE FROM events WHERE recurrence_group_id=%s", (row[0],))
        else:
            db.execute("DELETE FROM events WHERE id=%s", (event_id,))
    else:
        db.execute("DELETE FROM events WHERE id=%s", (event_id,))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/api/events/<int:event_id>", methods=["PUT"])
def update_event(tenant_slug, event_id):
    data = request.json
    db = get_school_db(tenant_slug)
    c = db.cursor()
    if request.args.get("all") == "1":
        c.execute("SELECT recurrence_group_id FROM events WHERE id=%s", (event_id,))
        row = c.fetchone()
        if row and row[0]:
            group_id = row[0]
            c.execute(
                "UPDATE events SET title=%s, description=%s, color=%s, recurrence=%s, recurrence_end=%s WHERE recurrence_group_id=%s",
                (data["title"], data.get("description"), data.get("color"), data.get("recurrence"), data.get("recurrence_end"), group_id),
            )
            db.commit()
            c.execute(
                "SELECT id, class_id, title, description, start, end, color, recurrence, recurrence_group_id, recurrence_end FROM events WHERE recurrence_group_id=%s LIMIT 1",
                (group_id,),
            )
            row = c.fetchone()
            return jsonify(dict(row)) if row else (jsonify({"error": "Event not found"}), 404)
        return jsonify({"error": "No recurrence group found"}), 404
    else:
        c.execute(
            "UPDATE events SET title=%s, description=%s, start=%s, end=%s, color=%s, recurrence=%s, recurrence_end=%s WHERE id=%s",
            (data["title"], data.get("description"), data["start"], data.get("end"), data.get("color"), data.get("recurrence"), data.get("recurrence_end"), event_id),
        )
        db.commit()
        c.execute(
            "SELECT id, class_id, title, description, start, end, color, recurrence, recurrence_group_id, recurrence_end FROM events WHERE id=%s",
            (event_id,),
        )
        row = c.fetchone()
        return jsonify(dict(row)) if row else (jsonify({"error": "Event not found"}), 404)


# ===================================================================
#  TEACHERS
# ===================================================================

@school_bp.route("/teachers", methods=["GET"])
@login_required("local_admin")
def list_teachers(tenant_slug):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT t.id, u.username, t.email, t.phone, t.notes, t.alerts, t.name FROM teachers t JOIN users u ON t.user_id = u.id")
    teachers = [{"id": r[0], "username": r[1], "email": r[2] or "", "phone": r[3] or "", "notes": r[4] or "", "alerts": r[5] or "", "name": r[6] or ""} for r in c.fetchall()]
    return jsonify(teachers)


@school_bp.route("/teachers", methods=["POST"])
@login_required("local_admin")
def add_teacher(tenant_slug):
    data = request.json
    username = data["username"]
    password = data["password"]
    name = data.get("name", "")
    password_hash = generate_password_hash(password)
    db = get_school_db(tenant_slug)
    c = db.cursor()
    try:
        c.execute(
            "INSERT INTO users (username, password_hash, role, created_by) VALUES (%s, %s, %s, %s) RETURNING id RETURNING id",
            (username, password_hash, "teacher", session["school_user_id"]),
        )
        user_id = c.fetchone()[0]
        c.execute(
            "INSERT INTO teachers (user_id, local_admin_id, name, email) VALUES (%s, %s, %s, %s)",
            (user_id, session["school_user_id"], name, username),
        )
        db.commit()
    except Exception:
        return jsonify({"error": "Username already exists"}), 400
    return jsonify({"success": True})


@school_bp.route("/teachers/<int:teacher_id>", methods=["DELETE"])
@login_required("local_admin")
def delete_teacher(tenant_slug, teacher_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT user_id FROM teachers WHERE id=%s AND local_admin_id=%s", (teacher_id, session["school_user_id"]))
    row = c.fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    user_id = row[0]
    c.execute("DELETE FROM teachers WHERE id=%s", (teacher_id,))
    c.execute("DELETE FROM users WHERE id=%s", (user_id,))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/teachers/<int:teacher_id>", methods=["PUT"])
@login_required("local_admin")
def update_teacher(tenant_slug, teacher_id):
    data = request.json
    new_username = data.get("username")
    new_password = data.get("password")
    phone = data.get("phone")
    notes = data.get("notes")
    alerts = data.get("alerts")
    name = data.get("name")
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT user_id FROM teachers WHERE id=%s AND local_admin_id=%s", (teacher_id, session["school_user_id"]))
    row = c.fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    user_id = row[0]
    if new_username:
        c.execute("SELECT id FROM users WHERE username=%s AND id<>%s", (new_username, user_id))
        if c.fetchone():
            return jsonify({"error": "\u0627\u0633\u0645 \u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645 \u0645\u0633\u062a\u062e\u062f\u0645 \u0628\u0627\u0644\u0641\u0639\u0644"}), 400
        c.execute("UPDATE users SET username=%s WHERE id=%s", (new_username, user_id))
        c.execute("UPDATE teachers SET email=%s WHERE id=%s", (new_username, teacher_id))
    if new_password:
        c.execute("UPDATE users SET password_hash=%s WHERE id=%s", (generate_password_hash(new_password), user_id))
    _safe_update(c, "teachers", _TEACHER_COLUMNS,
                 [("phone", phone), ("notes", notes), ("alerts", alerts), ("name", name)],
                 "WHERE id=%s", [teacher_id])
    db.commit()
    return jsonify({"success": True})


# ===================================================================
#  CURRICULUM GROUPS / ITEMS
# ===================================================================

@school_bp.route("/curriculum_groups", methods=["GET"])
@login_required("local_admin", "teacher")
def list_curriculum_groups(tenant_slug):
    level_id = request.args.get("level_id")
    db = get_school_db(tenant_slug)
    c = db.cursor()
    if level_id:
        c.execute("SELECT id, name FROM curriculum_groups WHERE level_id=%s", (level_id,))
    else:
        c.execute("SELECT id, name FROM curriculum_groups")
    return jsonify([{"id": r[0], "name": r[1]} for r in c.fetchall()])


@school_bp.route("/curriculum_groups", methods=["POST"])
@login_required("local_admin")
def add_curriculum_group(tenant_slug):
    data = request.json
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("INSERT INTO curriculum_groups (name, local_admin_id, level_id) VALUES (%s, %s, %s)",
              (data["name"], session["school_user_id"], data["level_id"]))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/curriculum_groups/<int:group_id>", methods=["DELETE", "PUT"])
@login_required("local_admin")
def modify_curriculum_group(tenant_slug, group_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    if request.method == "DELETE":
        level_id = request.args.get("level_id")
        if level_id:
            c.execute("DELETE FROM curriculum_groups WHERE id=%s AND local_admin_id=%s AND level_id=%s",
                      (group_id, session["school_user_id"], level_id))
        else:
            c.execute("DELETE FROM curriculum_groups WHERE id=%s AND local_admin_id=%s",
                      (group_id, session["school_user_id"]))
        db.commit()
        return jsonify({"success": True})
    else:
        data = request.json
        name = data.get("name")
        if name:
            c.execute("UPDATE curriculum_groups SET name=%s WHERE id=%s AND local_admin_id=%s",
                      (name, group_id, session["school_user_id"]))
            db.commit()
        return jsonify({"success": True})


@school_bp.route("/curriculum_items/<int:group_id>", methods=["GET"])
@login_required("local_admin", "teacher")
def list_curriculum_items(tenant_slug, group_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT id, name FROM curriculum_items WHERE group_id=%s", (group_id,))
    return jsonify([{"id": r[0], "name": r[1]} for r in c.fetchall()])


@school_bp.route("/curriculum_items", methods=["POST"])
@login_required("local_admin")
def add_curriculum_item(tenant_slug):
    data = request.json
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("INSERT INTO curriculum_items (group_id, name) VALUES (%s, %s)", (data["group_id"], data["name"]))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/curriculum_items/<int:item_id>", methods=["PUT", "DELETE"])
@login_required("local_admin")
def modify_curriculum_item(tenant_slug, item_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    if request.method == "PUT":
        data = request.json
        name = data.get("name")
        if name:
            c.execute("UPDATE curriculum_items SET name=%s WHERE id=%s", (name, item_id))
            db.commit()
        return jsonify({"success": True})
    else:
        c.execute("DELETE FROM curriculum_items WHERE id=%s", (item_id,))
        db.commit()
        return jsonify({"success": True})


@school_bp.route("/update_group_name", methods=["POST"])
@login_required("local_admin")
def update_group_name(tenant_slug):
    data = request.json
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("UPDATE curriculum_groups SET name=%s WHERE id=%s AND local_admin_id=%s",
              (data["new_name"], data["group_id"], session["school_user_id"]))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/update_subject_name", methods=["POST"])
@login_required("local_admin")
def update_subject_name(tenant_slug):
    data = request.json
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("UPDATE curriculum_items SET name=%s WHERE id=%s", (data["new_name"], data["subject_id"]))
    db.commit()
    return jsonify({"success": True})


# ===================================================================
#  LEVELS
# ===================================================================

@school_bp.route("/levels", methods=["GET"])
@login_required("local_admin")
def list_levels(tenant_slug):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT id, name FROM levels")
    return jsonify([{"id": r[0], "name": r[1]} for r in c.fetchall()])


@school_bp.route("/levels", methods=["POST"])
@login_required("local_admin")
def add_level(tenant_slug):
    data = request.json
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("INSERT INTO levels (name, local_admin_id) VALUES (%s, %s)",
              (data["name"], session["school_user_id"]))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/delete_level/<int:level_id>", methods=["DELETE"])
@login_required("local_admin")
def delete_level(tenant_slug, level_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("DELETE FROM levels WHERE id=%s AND local_admin_id=%s", (level_id, session["school_user_id"]))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/edit_level_name", methods=["POST"])
@login_required("local_admin")
def edit_level_name(tenant_slug):
    data = request.get_json()
    level_id = data.get("level_id")
    new_name = data.get("new_name")
    if not (level_id and new_name):
        return jsonify(success=False, error="Missing data")
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("UPDATE levels SET name = %s WHERE id = %s AND local_admin_id = %s",
              (new_name, level_id, session["school_user_id"]))
    db.commit()
    return jsonify(success=True)


# ===================================================================
#  ANNOUNCEMENTS
# ===================================================================

@school_bp.route("/api/class/<int:class_id>/announcement", methods=["GET"])
def get_class_announcement(tenant_slug, class_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT text, created_at, user_id, expiry FROM announcements WHERE class_id=%s ORDER BY id DESC LIMIT 1", (class_id,))
    row = c.fetchone()
    if row:
        return jsonify({"success": True, "text": row[0], "created_at": row[1], "user_id": row[2], "expiry": row[3]})
    return jsonify({"success": False, "text": "", "expiry": ""})


@school_bp.route("/api/class/<int:class_id>/announcement", methods=["POST"])
def add_class_announcement(tenant_slug, class_id):
    data = request.get_json()
    text = data.get("text", "").strip()
    user_id = session.get("school_user_id")
    if not text or not user_id:
        return jsonify({"success": False, "error": "Missing data"}), 400
    timestamp = datetime.now().isoformat(sep=" ", timespec="seconds")
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("INSERT INTO announcements (class_id, text, created_at, user_id, expiry) VALUES (%s, %s, %s, %s, %s)",
              (class_id, text, timestamp, user_id, data.get("expiry")))
    db.commit()
    return jsonify({"success": True})


# ===================================================================
#  CLASSES
# ===================================================================

@school_bp.route("/classes", methods=["GET"])
@login_required("super_admin", "local_admin", "teacher")
def list_classes(tenant_slug):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    role = session.get("school_role")
    group_by = request.args.get("group_by", "level")

    sql = """
        SELECT classes.id, classes.name, classes.level_id, l.name as level_name,
               classes.teacher_id, t.name as teacher_name,
               classes.backup_teacher_id, tb.name as backup_teacher_name,
               classes.dawra1_pub_start, classes.dawra1_pub_end,
               classes.dawra2_pub_start, classes.dawra2_pub_end,
               classes.dawra3_pub_start, classes.dawra3_pub_end,
               classes.year_pub_start, classes.year_pub_end
        FROM classes
        LEFT JOIN levels l ON classes.level_id = l.id
        LEFT JOIN teachers t ON classes.teacher_id = t.id
        LEFT JOIN teachers tb ON classes.backup_teacher_id = tb.id
    """
    params = ()
    if role == "teacher":
        teacher_id = session.get("school_teacher_id")
        if teacher_id is None:
            return jsonify([])
        sql += " WHERE classes.teacher_id = %s OR classes.backup_teacher_id = %s"
        params = (teacher_id, teacher_id)

    c.execute(sql, params)
    classes = []
    for row in c.fetchall():
        classes.append({
            "id": row[0], "name": row[1], "level_id": row[2], "level_name": row[3],
            "teacher_id": row[4], "teacher_name": row[5],
            "backup_teacher_id": row[6], "backup_teacher_name": row[7],
            "dawra1_pub_start": row[8], "dawra1_pub_end": row[9],
            "dawra2_pub_start": row[10], "dawra2_pub_end": row[11],
            "dawra3_pub_start": row[12], "dawra3_pub_end": row[13],
            "year_pub_start": row[14], "year_pub_end": row[15],
        })

    if group_by == "none":
        return jsonify({"flat": classes, "group_by": group_by})
    key_map = {"level": "level_name", "teacher": "teacher_name", "assistant": "backup_teacher_name"}
    key = key_map.get(group_by, "level_name")
    grouped = {}
    for cls in classes:
        group_val = cls.get(key) or "\u063a\u064a\u0631 \u0645\u062d\u062f\u062f"
        grouped.setdefault(group_val, []).append(cls)
    return jsonify({"grouped": grouped, "group_by": group_by})


@school_bp.route("/classes", methods=["POST"])
@login_required("local_admin")
def add_class(tenant_slug):
    data = request.json
    name = data["name"]
    level_id = _int_or_none(data.get("level_id"))
    teacher_id = _int_or_none(data.get("teacher_id"))
    backup_teacher_id = _int_or_none(data.get("backup_teacher_id"))
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute(
        "INSERT INTO classes (name, local_admin_id, level_id, teacher_id, backup_teacher_id) VALUES (%s, %s, %s, %s, %s)",
        (name, session["school_user_id"], level_id, teacher_id, backup_teacher_id),
    )
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/classes/<int:class_id>", methods=["DELETE"])
@login_required("local_admin")
def delete_class(tenant_slug, class_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("DELETE FROM classes WHERE id=%s AND local_admin_id=%s", (class_id, session["school_user_id"]))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/classes/<int:class_id>", methods=["GET", "PUT"])
@login_required("local_admin", "teacher")
def class_detail(tenant_slug, class_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    if request.method == "GET":
        c.execute(
            """SELECT classes.id, classes.name, classes.level_id, l.name as level_name,
                      classes.teacher_id, ut.username as teacher_name,
                      classes.backup_teacher_id, ub.username as backup_teacher_name,
                      classes.dawra1_pub_start, classes.dawra1_pub_end,
                      classes.dawra2_pub_start, classes.dawra2_pub_end,
                      classes.dawra3_pub_start, classes.dawra3_pub_end,
                      classes.year_pub_start, classes.year_pub_end
               FROM classes
               LEFT JOIN levels l ON classes.level_id = l.id
               LEFT JOIN teachers t ON classes.teacher_id = t.id
               LEFT JOIN users ut ON t.user_id = ut.id
               LEFT JOIN teachers bt ON classes.backup_teacher_id = bt.id
               LEFT JOIN users ub ON bt.user_id = ub.id
               WHERE classes.id=%s""",
            (class_id,),
        )
        row = c.fetchone()
        if not row:
            return jsonify({"error": "Class not found"}), 404
        return jsonify({
            "id": row[0], "name": row[1], "level_id": row[2], "level_name": row[3],
            "teacher_id": row[4], "teacher_name": row[5],
            "backup_teacher_id": row[6], "backup_teacher_name": row[7],
            "dawra1_pub_start": row[8], "dawra1_pub_end": row[9],
            "dawra2_pub_start": row[10], "dawra2_pub_end": row[11],
            "dawra3_pub_start": row[12], "dawra3_pub_end": row[13],
            "year_pub_start": row[14], "year_pub_end": row[15],
        })

    # PUT
    data = request.json
    field_values = [
        ("name", data.get("name")),
        ("level_id", _none_if_empty(data.get("level_id"))),
        ("teacher_id", _none_if_empty(data.get("teacher_id"))),
        ("backup_teacher_id", _none_if_empty(data.get("backup_teacher_id"))),
    ]
    for field in ("dawra1_pub_start", "dawra1_pub_end", "dawra2_pub_start", "dawra2_pub_end",
                   "dawra3_pub_start", "dawra3_pub_end", "year_pub_start", "year_pub_end"):
        field_values.append((field, _none_if_empty(data.get(field))))
    _safe_update(c, "classes", _CLASS_COLUMNS, field_values, "WHERE id = %s", [class_id])
    db.commit()
    return jsonify({"success": True})


# ===================================================================
#  CLASS COURSES
# ===================================================================

@school_bp.route("/class_courses/<int:class_id>", methods=["GET"])
@login_required("local_admin")
def get_class_courses(tenant_slug, class_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT ci.id, ci.name FROM class_courses cc JOIN curriculum_items ci ON cc.curriculum_item_id=ci.id WHERE cc.class_id=%s", (class_id,))
    return jsonify([{"id": r[0], "name": r[1]} for r in c.fetchall()])


@school_bp.route("/class_courses/<int:class_id>", methods=["POST"])
@login_required("local_admin")
def add_course_to_class(tenant_slug, class_id):
    data = request.json
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("INSERT INTO class_courses (class_id, curriculum_item_id) VALUES (%s, %s)", (class_id, data["curriculum_item_id"]))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/class_courses/<int:class_id>/<int:curriculum_item_id>", methods=["DELETE"])
@login_required("local_admin")
def remove_course_from_class(tenant_slug, class_id, curriculum_item_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("DELETE FROM class_courses WHERE class_id=%s AND curriculum_item_id=%s", (class_id, curriculum_item_id))
    db.commit()
    return jsonify({"success": True})


# ===================================================================
#  STUDENTS
# ===================================================================

@school_bp.route("/students", methods=["GET"])
@login_required("super_admin", "local_admin", "teacher")
def get_students(tenant_slug):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    role = session.get("school_role")
    if role == "teacher":
        teacher_id = session.get("school_teacher_id")
        c.execute(
            """SELECT s.id, u.username as parent_username, s.name, s.email, s.phone, s.notes,
                      s.alerts, s.date_of_birth, s.secondary_email, c.name as class_name, c.id as class_id, s.sex
               FROM students s
               LEFT JOIN users u ON s.email = u.username
               LEFT JOIN classes c ON s.class_id = c.id
               WHERE c.teacher_id = %s OR c.backup_teacher_id = %s
               ORDER BY s.id DESC""",
            (teacher_id, teacher_id),
        )
    else:
        c.execute(
            """SELECT s.id, u.username as parent_username, s.name, s.email, s.phone, s.notes,
                      s.alerts, s.date_of_birth, s.secondary_email, c.name as class_name, c.id as class_id, s.sex
               FROM students s
               LEFT JOIN users u ON s.email = u.username
               LEFT JOIN classes c ON s.class_id = c.id
               ORDER BY s.id DESC""",
        )
    students = [
        {
            "id": r[0], "parent_username": r[1] or "", "name": r[2] or "",
            "email": r[3] or "", "phone": r[4] or "", "notes": r[5] or "",
            "alerts": r[6] or "", "date_of_birth": r[7] or "",
            "secondary_email": r[8] or "",
            "class_name": r[9] or "\u0628\u062f\u0648\u0646 \u0635\u0641",
            "class_id": r[10], "sex": r[11] or "",
        }
        for r in c.fetchall()
    ]
    return jsonify(students)


@school_bp.route("/students/search", methods=["GET"])
@login_required("super_admin", "local_admin", "teacher")
def search_students(tenant_slug):
    query = request.args.get("query", "").strip()
    db = get_school_db(tenant_slug)
    c = db.cursor()
    role = session.get("school_role")
    like_query = f"%{query}%"

    base = """SELECT s.id, u.username as parent_username, s.name, s.email, s.phone, s.notes,
                     s.alerts, s.date_of_birth, s.secondary_email, c.name as class_name, s.class_id, s.sex
              FROM students s
              LEFT JOIN users u ON s.email = u.username
              LEFT JOIN classes c ON s.class_id = c.id"""

    if role == "teacher":
        teacher_id = session.get("school_teacher_id")
        where = " WHERE (c.teacher_id = %s OR c.backup_teacher_id = %s)"
        params = [teacher_id, teacher_id]
        if query:
            where += " AND (s.name LIKE %s OR u.username LIKE %s OR s.email LIKE %s OR s.phone LIKE %s)"
            params += [like_query] * 4
    else:
        where = ""
        params = []
        if query:
            where = " WHERE s.name LIKE %s OR u.username LIKE %s OR s.email LIKE %s OR s.phone LIKE %s"
            params = [like_query] * 4

    c.execute(base + where + " ORDER BY s.id DESC", params)
    students = [
        {
            "id": r[0], "parent_username": r[1] or "", "name": r[2] or "",
            "email": r[3] or "", "phone": r[4] or "", "notes": r[5] or "",
            "alerts": r[6] or "", "date_of_birth": r[7] or "",
            "secondary_email": r[8] or "",
            "class_name": r[9] or "\u0628\u062f\u0648\u0646 \u0635\u0641",
            "class_id": r[10], "sex": r[11] or "",
        }
        for r in c.fetchall()
    ]
    return jsonify(students)


@school_bp.route("/create_student", methods=["POST"])
@login_required("super_admin", "local_admin")
def create_student(tenant_slug):
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    name = data.get("name")
    email = data.get("email") or username
    phone = data.get("phone")
    notes = data.get("notes")
    alerts = data.get("alerts")
    class_id = data.get("class_id")
    date_of_birth = data.get("date_of_birth")
    secondary_email = data.get("secondary_email")
    if not username or not password or not name:
        return jsonify({"success": False, "error": "\u0627\u0644\u0631\u062c\u0627\u0621 \u062a\u0639\u0628\u0626\u0629 \u062c\u0645\u064a\u0639 \u0627\u0644\u062d\u0642\u0648\u0644"}), 400
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT id FROM users WHERE username=%s", (username,))
    user = c.fetchone()
    if user:
        user_id = user[0]
    else:
        password_hash = generate_password_hash(password)
        c.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) RETURNING id", (username, password_hash, "student"))
    c.execute(
        "INSERT INTO students (name, class_id, email, phone, notes, alerts, date_of_birth, secondary_email) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (name, class_id, email or "", phone or "", notes or "", alerts or "", date_of_birth or "", secondary_email or ""),
    )
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/update_student/<int:student_id>", methods=["PUT"])
@login_required("super_admin", "local_admin")
def update_student(tenant_slug, student_id):
    data = request.json
    new_username = data.get("username")
    email = data.get("email")
    phone = data.get("phone")
    notes = data.get("notes")
    alerts = data.get("alerts")
    name = data.get("name")
    date_of_birth = data.get("date_of_birth")
    secondary_email = data.get("secondary_email")
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT email FROM students WHERE id=%s", (student_id,))
    row = c.fetchone()
    old_email = row[0] if row else None

    if new_username and new_username != old_email:
        c.execute("SELECT id FROM users WHERE username=%s", (new_username,))
        user = c.fetchone()
        if not user:
            new_password = data.get("new_password") or data.get("password")
            if not new_password:
                return jsonify({"success": False, "error": "\u064a\u062c\u0628 \u0625\u062f\u062e\u0627\u0644 \u0643\u0644\u0645\u0629 \u0645\u0631\u0648\u0631 \u0644\u0644\u0645\u0633\u062a\u062e\u062f\u0645 \u0627\u0644\u062c\u062f\u064a\u062f"}), 400
            c.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) RETURNING id",
                      (new_username, generate_password_hash(new_password), "student"))
        email = new_username

    field_values = [
        ("email", email), ("phone", phone), ("notes", notes), ("alerts", alerts),
        ("name", name), ("date_of_birth", date_of_birth), ("secondary_email", secondary_email),
    ]
    if "sex" in data:
        field_values.append(("sex", data["sex"]))
    _safe_update(c, "students", _STUDENT_COLUMNS, field_values, "WHERE id=%s", [student_id])

    if old_email and email and old_email != email:
        c.execute("SELECT COUNT(*) FROM students WHERE email=%s", (old_email,))
        if c.fetchone()[0] == 0:
            c.execute("DELETE FROM users WHERE username=%s", (old_email,))
        c.execute("SELECT id FROM users WHERE username=%s", (email,))
        if not c.fetchone():
            new_password = data.get("new_password") or data.get("password")
            if not new_password:
                db.commit()
                return jsonify({"success": False, "error": "Password required for new user"}), 400
            c.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) RETURNING id",
                      (email, generate_password_hash(new_password), "student"))

    if data.get("new_password"):
        c.execute("UPDATE users SET password_hash=%s WHERE username=%s",
                  (generate_password_hash(data["new_password"]), email))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/update_student/<int:student_id>", methods=["POST"])
@login_required("local_admin")
def update_student_post(tenant_slug, student_id):
    data = request.get_json()
    db = get_school_db(tenant_slug)
    c = db.cursor()
    for field in ("class_id", "email", "phone", "notes", "alerts"):
        val = data.get(field)
        if val is not None:
            c.execute(f"UPDATE students SET {field}=%s WHERE id=%s", (val, student_id))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/students/<int:class_id>", methods=["GET"])
@login_required("super_admin", "local_admin", "teacher")
def list_students(tenant_slug, class_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute(
        """SELECT s.id, u.username, s.name, s.email, s.phone, s.notes, s.alerts
           FROM students s LEFT JOIN users u ON s.id = u.id
           WHERE s.class_id=%s""",
        (class_id,),
    )
    students = [
        {"id": r[0], "username": r[1], "name": r[2] or "", "email": r[3] or "",
         "phone": r[4] or "", "notes": r[5] or "", "alerts": r[6] or ""}
        for r in c.fetchall()
    ]
    return jsonify(students)


@school_bp.route("/students/<int:class_id>", methods=["POST"])
@login_required("local_admin")
def add_student(tenant_slug, class_id):
    data = request.json
    name = data["name"]
    sex = data.get("sex")
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("INSERT INTO students (name, class_id, sex) VALUES (%s, %s, %s)", (name, class_id, sex))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/students/<int:class_id>/<int:student_id>", methods=["DELETE"])
@login_required("local_admin")
def delete_student(tenant_slug, class_id, student_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("DELETE FROM students WHERE id=%s AND class_id=%s", (student_id, class_id))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/delete_student", methods=["POST"])
@login_required("super_admin", "local_admin")
def delete_student_api(tenant_slug):
    data = request.get_json()
    student_id = data.get("id")
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute('SELECT * FROM users WHERE id=%s AND role="student"', (student_id,))
    if not c.fetchone():
        return jsonify({"success": False, "error": "\u0627\u0644\u0637\u0627\u0644\u0628 \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f"}), 404
    c.execute("DELETE FROM users WHERE id=%s", (student_id,))
    db.commit()
    return jsonify({"success": True})


# ===================================================================
#  STUDENT CARD / ABILITIES
# ===================================================================

@school_bp.route("/student_card/<int:student_id>", methods=["GET"])
@login_required()
def get_student_card(tenant_slug, student_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT class_id FROM students WHERE id=%s", (student_id,))
    row = c.fetchone()
    if not row:
        return jsonify({"error": "Student not found"}), 404
    class_id = row[0]
    c.execute("SELECT ci.id, ci.name FROM class_courses cc JOIN curriculum_items ci ON cc.curriculum_item_id=ci.id WHERE cc.class_id=%s", (class_id,))
    courses = [{"id": r[0], "name": r[1]} for r in c.fetchall()]
    c.execute("SELECT curriculum_item_id, level, comment FROM student_grades WHERE student_id=%s", (student_id,))
    rows = c.fetchall()
    scores = {r[0]: r[1] for r in rows}
    comments = {r[0]: r[2] or "" for r in rows}
    return jsonify({"courses": courses, "grades": scores, "comments": comments})


@school_bp.route("/student_abilities/<int:student_id>/<int:class_id>", methods=["GET", "POST"])
def student_abilities(tenant_slug, student_id, class_id):
    if "school_user_id" not in session:
        return redirect(url_for("school.school_login", tenant_slug=tenant_slug))

    db = get_school_db(tenant_slug)
    c = db.cursor()
    school_info = _school_info(tenant_slug)

    c.execute("SELECT name, level_id FROM classes WHERE id=%s", (class_id,))
    row = c.fetchone()
    if not row or not row[0] or not row[1]:
        return render_template("student_abilities.html", school_info=school_info,
                               error_message="\u0644\u0645 \u064a\u062a\u0645 \u0627\u0644\u0639\u062b\u0648\u0631 \u0639\u0644\u0649 \u0627\u0644\u0635\u0641 \u0623\u0648 \u0627\u0644\u0645\u0633\u062a\u0648\u0649 \u0627\u0644\u0645\u0637\u0644\u0648\u0628.",
                               tenant_slug=tenant_slug)
    class_name, level_id = row[0], row[1]

    c.execute("SELECT name FROM levels WHERE id=%s", (level_id,))
    level_row = c.fetchone()
    class_level = level_row[0] if level_row else ""

    c.execute("SELECT cg.id, cg.name FROM curriculum_groups cg WHERE cg.level_id=%s", (level_id,))
    groups = []
    for group_id, group_name in c.fetchall():
        c.execute("SELECT ci.id, ci.name FROM curriculum_items ci WHERE ci.group_id=%s", (group_id,))
        items = [{"id": cid, "name": n} for cid, n in c.fetchall()]
        groups.append({"group_name": group_name, "items": items})

    c.execute("SELECT curriculum_item_id, level, comment, comment_updated_at, comment_user FROM student_grades WHERE student_id=%s", (student_id,))
    rows = c.fetchall()
    scores = {r[0]: r[1] for r in rows}
    comments = {r[0]: r[2] or "" for r in rows}
    comment_meta = {r[0]: {"updated_at": r[3], "user": r[4]} for r in rows}

    if request.method == "POST":
        if session.get("school_role") not in ("teacher", "local_admin"):
            return jsonify({"success": False, "error": "Not authorized"}), 403
        data = request.get_json()
        comment_user = session.get("school_username", "unknown")
        comment_updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for group in groups:
            for item in group["items"]:
                cid = item["id"]
                val = data.get(str(cid))
                comment_in_request = f"comment_{cid}" in data
                comment = data.get(f"comment_{cid}")
                c.execute("SELECT id, comment FROM student_grades WHERE student_id=%s AND curriculum_item_id=%s", (student_id, cid))
                existing = c.fetchone()
                if (val is None or val == "") and (not comment_in_request or not comment):
                    c.execute("DELETE FROM student_grades WHERE student_id=%s AND curriculum_item_id=%s", (student_id, cid))
                else:
                    try:
                        val_int = int(val) if val not in (None, "") else None
                    except (ValueError, TypeError):
                        val_int = None
                    if existing:
                        if comment_in_request:
                            c.execute("UPDATE student_grades SET level=%s, comment=%s, comment_updated_at=%s, comment_user=%s WHERE student_id=%s AND curriculum_item_id=%s",
                                      (val_int, comment, comment_updated_at, comment_user, student_id, cid))
                        else:
                            c.execute("UPDATE student_grades SET level=%s WHERE student_id=%s AND curriculum_item_id=%s",
                                      (val_int, student_id, cid))
                    else:
                        c.execute("INSERT INTO student_grades (student_id, curriculum_item_id, level, comment, comment_updated_at, comment_user) VALUES (%s, %s, %s, %s, %s, %s)",
                                  (student_id, cid, val_int, comment if comment is not None else "", comment_updated_at, comment_user))
        db.commit()
        return jsonify({"success": True})

    # GET
    editable = session.get("school_role") in ("teacher", "local_admin")
    level_badges = [
        {"label": "\u0628\u062d\u0627\u062c\u0629 \u0644\u0645\u062a\u0627\u0628\u0639\u0629", "class": "level-none", "icon": "\U0001f4a1"},
        {"label": "\u0645\u062a\u0648\u0633\u0637", "class": "level-intermediate", "icon": "\U0001f44d"},
        {"label": "\u0645\u062a\u0645\u064a\u0632", "class": "level-master", "icon": "\U0001f3c6"},
    ]
    c.execute("SELECT name FROM students WHERE id=%s", (student_id,))
    row = c.fetchone()
    student_name = row[0] if row else ""

    today_str = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT id, due_date, description, files FROM homework WHERE class_id=%s AND due_date >= %s ORDER BY due_date ASC", (class_id, today_str))
    homeworks = []
    for r in c.fetchall():
        files = r[3].split(";") if r[3] else []
        homeworks.append({"id": r[0], "due_date": r[1], "description": r[2], "files": files})

    return render_template(
        "student_abilities.html",
        school_info=school_info, groups=groups, scores=scores, comments=comments,
        comment_meta=comment_meta, editable=editable, level_badges=level_badges,
        student_name=student_name, student_id=student_id, class_id=class_id,
        class_name=class_name, class_level=class_level, homeworks=homeworks,
        tenant_slug=tenant_slug,
    )


@school_bp.route("/save_comment", methods=["POST"])
def save_comment(tenant_slug):
    if session.get("school_role") not in ("teacher", "local_admin"):
        return jsonify({"success": False, "error": "Not authorized"}), 403
    data = request.get_json()
    student_id = data.get("student_id")
    course_id = data.get("course_id")
    comment = data.get("comment", "")
    if not student_id or not course_id:
        return jsonify({"success": False, "error": "Missing data"}), 400
    db = get_school_db(tenant_slug)
    c = db.cursor()
    comment_user = session.get("school_username", "unknown")
    comment_updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("SELECT id FROM student_grades WHERE student_id=%s AND curriculum_item_id=%s", (student_id, course_id))
    if c.fetchone():
        c.execute("UPDATE student_grades SET comment=%s, comment_updated_at=%s, comment_user=%s WHERE student_id=%s AND curriculum_item_id=%s",
                  (comment, comment_updated_at, comment_user, student_id, course_id))
    else:
        c.execute("INSERT INTO student_grades (student_id, curriculum_item_id, level, comment, comment_updated_at, comment_user) VALUES (%s, %s, %s, %s, %s, %s)",
                  (student_id, course_id, 0, comment, comment_updated_at, comment_user))
    db.commit()
    return jsonify({"success": True, "comment": comment, "comment_updated_at": comment_updated_at, "comment_user": comment_user})


# ===================================================================
#  HOMEWORK
# ===================================================================

@school_bp.route("/api/homework/list/<int:class_id>", methods=["GET"])
def list_homework(tenant_slug, class_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT id, due_date, description, files FROM homework WHERE class_id=%s ORDER BY due_date DESC", (class_id,))
    result = []
    for r in c.fetchall():
        files = r[3].split(";") if r[3] else []
        result.append({"id": r[0], "due_date": r[1], "description": r[2], "files": files})
    return jsonify({"success": True, "homeworks": result})


@school_bp.route("/api/homework", methods=["POST"])
@login_required()
def upload_homework(tenant_slug):
    due_date = request.form.get("due_date")
    description = request.form.get("description")
    class_id = request.form.get("class_id")
    files = request.files.getlist("documents")
    if not (due_date and description and class_id):
        return jsonify({"success": False, "error": "\u062c\u0645\u064a\u0639 \u0627\u0644\u062d\u0642\u0648\u0644 \u0645\u0637\u0644\u0648\u0628\u0629"}), 400
    saved_files = save_homework_files(files, class_id)
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("INSERT INTO homework (class_id, due_date, description, files) VALUES (%s, %s, %s, %s)",
              (class_id, due_date, description, ";".join(saved_files)))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/api/homework/edit/<int:homework_id>", methods=["POST"])
def edit_homework(tenant_slug, homework_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT class_id, files FROM homework WHERE id=%s", (homework_id,))
    row = c.fetchone()
    if not row:
        return jsonify({"success": False, "error": "Homework not found"}), 404
    class_id, old_files = row[0], row[1]
    due_date = request.form.get("due_date")
    description = request.form.get("description")
    files = request.files.getlist("documents")
    new_files = save_homework_files(files, class_id) if files else []
    all_files = (old_files.split(";") if old_files else []) + new_files
    all_files_str = ";".join([f for f in all_files if f])
    c.execute("UPDATE homework SET due_date=%s, description=%s, files=%s WHERE id=%s",
              (due_date, description, all_files_str, homework_id))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/api/homework/delete/<int:homework_id>", methods=["POST"])
def delete_homework(tenant_slug, homework_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT class_id, files FROM homework WHERE id=%s", (homework_id,))
    row = c.fetchone()
    if not row:
        return jsonify({"success": False, "error": "Homework not found"}), 404
    class_id, files = row[0], row[1]
    if files:
        upload_folder = os.path.join(_upload_folder(), f"class_{class_id}")
        for fname in files.split(";"):
            fpath = os.path.join(upload_folder, fname)
            if os.path.isfile(fpath):
                try:
                    os.remove(fpath)
                except Exception:
                    pass
    c.execute("DELETE FROM homework WHERE id=%s", (homework_id,))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/uploads/class_<int:class_id>/<filename>")
@login_required()
def uploaded_file(tenant_slug, class_id, filename):
    upload_folder = os.path.join(_upload_folder(), f"class_{class_id}")
    return send_from_directory(upload_folder, filename)


# ===================================================================
#  EXAMS
# ===================================================================

@school_bp.route("/api/exams/<int:class_id>", methods=["GET"])
@login_required("local_admin")
def list_exams(tenant_slug, class_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute(
        """SELECT exams.id, exams.name, exams.status, exams.curriculum_group_id,
                  cg.name as subject_name, exams.is_final, exams.weight, exams.dawra, exams.is_year_final
           FROM exams LEFT JOIN curriculum_groups cg ON exams.curriculum_group_id = cg.id
           WHERE exams.class_id = %s ORDER BY exams.id""",
        (class_id,),
    )
    exams = []
    for r in c.fetchall():
        exams.append({
            "id": r[0], "name": r[1], "status": r[2], "curriculum_group_id": r[3],
            "subject_name": r[4] or "", "is_final": r[5] or 0,
            "weight": r[6] if r[6] is not None else 1.0,
            "dawra": r[7] if r[7] is not None else 1,
            "is_year_final": r[8] or 0,
        })
    return jsonify({"exams": exams})


@school_bp.route("/api/exams/<int:class_id>", methods=["POST"])
@login_required("local_admin", "teacher")
def add_exam(tenant_slug, class_id):
    data = request.get_json()
    name = data.get("name")
    curriculum_group_id = data.get("curriculum_group_id")
    status = data.get("status", "active")
    is_final = data.get("is_final", 0)
    weight = data.get("weight", 1.0)
    dawra = data.get("dawra", 1)
    is_year_final = int(data.get("is_year_final", 0))
    dawra_to_save = None if is_year_final else dawra
    if not name:
        return jsonify({"error": "Name is required"}), 400
    if not curriculum_group_id:
        return jsonify({"error": "Subject is required"}), 400
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute(
        "INSERT INTO exams (class_id, name, status, curriculum_group_id, is_final, weight, dawra, is_year_final) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (class_id, name, status, curriculum_group_id, is_final, weight, dawra_to_save, is_year_final),
    )
    db.commit()
    exam_id = c.fetchone()[0]
    return jsonify({"id": exam_id, "name": name, "status": status, "curriculum_group_id": curriculum_group_id,
                    "is_final": is_final, "weight": weight, "dawra": dawra_to_save, "is_year_final": is_year_final})


@school_bp.route("/api/exams/<int:exam_id>", methods=["PUT"])
@login_required("local_admin", "teacher")
def edit_exam(tenant_slug, exam_id):
    data = request.get_json()
    db = get_school_db(tenant_slug)
    c = db.cursor()
    for field in ("name", "curriculum_group_id", "status", "is_final", "weight"):
        val = data.get(field)
        if val is not None:
            c.execute(f"UPDATE exams SET {field} = %s WHERE id = %s", (val, exam_id))
    is_year_final = data.get("is_year_final")
    dawra = data.get("dawra")
    if is_year_final is not None:
        c.execute("UPDATE exams SET is_year_final = %s WHERE id = %s", (int(is_year_final), exam_id))
        if int(is_year_final):
            c.execute("UPDATE exams SET dawra = NULL WHERE id = %s", (exam_id,))
        elif dawra is not None:
            c.execute("UPDATE exams SET dawra = %s WHERE id = %s", (dawra, exam_id))
    elif dawra is not None:
        c.execute("UPDATE exams SET dawra = %s WHERE id = %s", (dawra, exam_id))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/api/exams/<int:exam_id>", methods=["DELETE"])
@login_required("local_admin", "teacher")
def delete_exam(tenant_slug, exam_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("DELETE FROM exams WHERE id = %s", (exam_id,))
    c.execute("DELETE FROM grades WHERE exam_id = %s", (exam_id,))
    db.commit()
    return jsonify({"success": True})


# ===================================================================
#  GRADES
# ===================================================================

@school_bp.route("/api/grades/<int:class_id>", methods=["GET"])
@login_required("local_admin", "teacher")
def list_grades(tenant_slug, class_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT id, name FROM students WHERE class_id = %s ORDER BY id", (class_id,))
    students = [{"id": r[0], "name": r[1]} for r in c.fetchall()]
    c.execute(
        """SELECT exams.id, exams.name, exams.curriculum_group_id, cg.name as subject_name,
                  exams.is_final, exams.weight, exams.dawra, exams.is_year_final
           FROM exams LEFT JOIN curriculum_groups cg ON exams.curriculum_group_id = cg.id
           WHERE exams.class_id = %s ORDER BY exams.id""",
        (class_id,),
    )
    exams = [
        {"id": r[0], "name": r[1], "curriculum_group_id": r[2], "subject_name": r[3] or "",
         "is_final": r[4] or 0, "weight": r[5] if r[5] is not None else 1.0,
         "dawra": r[6] if r[6] is not None else 1, "is_year_final": r[7] or 0}
        for r in c.fetchall()
    ]
    c.execute("SELECT student_id, exam_id, grade FROM grades WHERE exam_id IN (SELECT id FROM exams WHERE class_id = %s)", (class_id,))
    grade_map = {}
    for sid, eid, grade in c.fetchall():
        grade_map[(sid, eid)] = grade
    for student in students:
        student["grades"] = {}
        for exam in exams:
            student["grades"][str(exam["id"])] = grade_map.get((student["id"], exam["id"]), "")
    return jsonify({"students": students, "exams": exams})


@school_bp.route("/api/grades/<int:class_id>", methods=["POST"])
@login_required("local_admin", "teacher")
def update_grades(tenant_slug, class_id):
    data = request.get_json()
    grades = data.get("grades", [])
    db = get_school_db(tenant_slug)
    c = db.cursor()
    for entry in grades:
        sid = entry.get("student_id")
        eid = entry.get("exam_id")
        grade = entry.get("grade")
        if not (sid and eid):
            continue
        c.execute(
            """INSERT INTO grades (student_id, exam_id, grade) VALUES (%s, %s, %s)
               ON CONFLICT(student_id, exam_id) DO UPDATE SET grade=excluded.grade, updated_at=CURRENT_TIMESTAMP""",
            (sid, eid, grade),
        )
    db.commit()
    return jsonify({"success": True})


# ===================================================================
#  CONTINUOUS MONITORING & ATTENDANCE
# ===================================================================

@school_bp.route("/continuous_monitoring/<int:class_id>")
@login_required("local_admin", "teacher")
def continuous_monitoring(tenant_slug, class_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT name FROM classes WHERE id=%s", (class_id,))
    row = c.fetchone()
    class_name = row[0] if row else ""
    return render_template("continuous_monitoring.html", class_id=class_id, class_name=class_name, tenant_slug=tenant_slug)


@school_bp.route("/attendance/<int:class_id>")
@login_required("local_admin", "teacher")
def attendance_page(tenant_slug, class_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT name FROM classes WHERE id=%s", (class_id,))
    row = c.fetchone()
    class_name = row[0] if row else ""
    return render_template("attendance.html", class_id=class_id, class_name=class_name, tenant_slug=tenant_slug)


@school_bp.route("/api/attendance/<int:class_id>", methods=["GET"])
@login_required("local_admin", "teacher")
def get_attendance(tenant_slug, class_id):
    week_start_str = request.args.get("week_start")
    if week_start_str:
        week_start = _dt.datetime.strptime(week_start_str, "%Y-%m-%d").date()
    else:
        today = _dt.date.today()
        week_start = today - _dt.timedelta(days=today.weekday() + 1 if today.weekday() < 6 else 0)
    week_dates = [(week_start + _dt.timedelta(days=i)).isoformat() for i in range(7)]
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT id, name FROM students WHERE class_id=%s ORDER BY id", (class_id,))
    students = [{"id": r[0], "name": r[1]} for r in c.fetchall()]
    q_marks = ",".join(["?"] * len(week_dates))
    c.execute(f"SELECT student_id, day, present FROM attendance WHERE class_id=%s AND day IN ({q_marks})",
              (class_id, *week_dates))
    att = {f"{r[0]}_{r[1]}": r[2] for r in c.fetchall()}
    return jsonify({"students": students, "attendance": att})


@school_bp.route("/api/attendance/<int:class_id>", methods=["POST"])
@login_required("local_admin", "teacher")
def update_attendance(tenant_slug, class_id):
    data = request.get_json()
    student_id = data.get("student_id")
    day = data.get("day")
    present = 1 if data.get("present") else 0
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute(
        """INSERT INTO attendance (student_id, class_id, day, present) VALUES (%s, %s, %s, %s)
           ON CONFLICT(student_id, class_id, day) DO UPDATE SET present=excluded.present""",
        (student_id, class_id, day, present),
    )
    db.commit()
    return jsonify({"success": True})


# ===================================================================
#  SUPER BADGES (management)
# ===================================================================

@school_bp.route("/super_badges")
@login_required()
def super_badges_page(tenant_slug):
    return render_template("super_badges.html", tenant_slug=tenant_slug)


@school_bp.route("/api/super_badges", methods=["GET"])
def get_super_badges(tenant_slug):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT id, name, icon_type, icon_value, active FROM super_badges")
    badges = [{"id": r[0], "name": r[1], "icon_type": r[2], "icon_value": r[3], "active": r[4]} for r in c.fetchall()]
    return jsonify(badges)


@school_bp.route("/api/super_badges", methods=["POST"])
def add_super_badge(tenant_slug):
    data = request.get_json()
    name = data.get("name")
    icon_type = data.get("icon_type")
    icon_value = data.get("icon_value")
    if not name or not icon_type or not icon_value:
        return jsonify({"error": "Missing required fields"}), 400
    badge_id = str(uuid.uuid4())
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("INSERT INTO super_badges (id, name, icon_type, icon_value, active) VALUES (%s, %s, %s, %s, %s)",
              (badge_id, name, icon_type, icon_value, 1))
    db.commit()
    return jsonify({"id": badge_id, "name": name, "icon_type": icon_type, "icon_value": icon_value, "active": 1})


@school_bp.route("/api/super_badges/<badge_id>", methods=["GET"])
def get_super_badge(tenant_slug, badge_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT id, name, icon_type, icon_value, active FROM super_badges WHERE id = %s", (badge_id,))
    r = c.fetchone()
    if r:
        return jsonify({"id": r[0], "name": r[1], "icon_type": r[2], "icon_value": r[3], "active": r[4]})
    return jsonify({"error": "Not found"}), 404


@school_bp.route("/api/super_badges/<badge_id>", methods=["PUT"])
def update_super_badge(tenant_slug, badge_id):
    data = request.get_json()
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT id FROM super_badges WHERE id = %s", (badge_id,))
    if not c.fetchone():
        return jsonify({"error": "Not found"}), 404
    c.execute("UPDATE super_badges SET name = %s, icon_type = %s, icon_value = %s WHERE id = %s",
              (data.get("name"), data.get("icon_type"), data.get("icon_value"), badge_id))
    db.commit()
    return jsonify({"id": badge_id, "name": data.get("name"), "icon_type": data.get("icon_type"), "icon_value": data.get("icon_value")})


@school_bp.route("/api/super_badges/<badge_id>/active", methods=["PATCH"])
def toggle_super_badge_active(tenant_slug, badge_id):
    data = request.get_json(force=True, silent=True) or {}
    set_active = data.get("active")
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT active FROM super_badges WHERE id = %s", (badge_id,))
    row = c.fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    new_active = (0 if row[0] else 1) if set_active is None else (1 if set_active else 0)
    c.execute("UPDATE super_badges SET active = %s WHERE id = %s", (new_active, badge_id))
    db.commit()
    return jsonify({"id": badge_id, "active": new_active})


@school_bp.route("/api/super_badges/<badge_id>", methods=["DELETE"])
def delete_super_badge(tenant_slug, badge_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT id FROM super_badges WHERE id = %s", (badge_id,))
    if not c.fetchone():
        return jsonify({"error": "Not found"}), 404
    c.execute("DELETE FROM super_badges WHERE id = %s", (badge_id,))
    db.commit()
    return jsonify({"success": True})


# ===================================================================
#  SUPER BADGES (student-facing)
# ===================================================================

@school_bp.route("/api/student/<int:student_id>/super_badges", methods=["GET"])
@login_required()
def get_student_super_badges(tenant_slug, student_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT id, name, icon_type, icon_value FROM super_badges WHERE active=1 ORDER BY created_at DESC")
    all_badges = c.fetchall()
    c.execute("SELECT super_badge_id, created_at FROM student_super_badges WHERE student_id=%s AND active=1", (student_id,))
    active_info = {r[0]: r[1] for r in c.fetchall()}
    badges = []
    for b in all_badges:
        badge_id = str(b[0])
        badges.append({
            "id": badge_id, "name": b[1], "icon_type": b[2], "icon_value": b[3],
            "active": badge_id in active_info,
            "awarded_at": active_info.get(badge_id),
        })
    return jsonify(badges)


@school_bp.route("/api/student/<int:student_id>/super_badges/<badge_id>/toggle", methods=["POST"])
@login_required()
def toggle_student_super_badge(tenant_slug, student_id, badge_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT id, active FROM student_super_badges WHERE student_id=%s AND super_badge_id=%s", (student_id, badge_id))
    row = c.fetchone()
    if row:
        new_active = 0 if row[1] else 1
        c.execute("UPDATE student_super_badges SET active=%s WHERE id=%s", (new_active, row[0]))
    else:
        new_active = 1
        c.execute("INSERT INTO student_super_badges (student_id, super_badge_id, active) VALUES (%s, %s, %s)",
                  (student_id, badge_id, new_active))
    db.commit()
    return jsonify({"success": True, "active": bool(new_active)})


@school_bp.route("/api/student/<int:student_id>/super_badges/batch_update", methods=["POST"])
def batch_update_student_super_badges(tenant_slug, student_id):
    data = request.get_json()
    badge_states = data.get("badges", {})
    if not isinstance(badge_states, dict):
        return jsonify({"success": False, "error": "Invalid data"}), 400
    db = get_school_db(tenant_slug)
    c = db.cursor()
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    for badge_id, is_active in badge_states.items():
        c.execute("SELECT id FROM student_super_badges WHERE student_id=%s AND super_badge_id=%s", (student_id, badge_id))
        row = c.fetchone()
        if row:
            if is_active:
                c.execute("UPDATE student_super_badges SET active=%s, created_at=%s WHERE id=%s", (1, now_str, row[0]))
            else:
                c.execute("UPDATE student_super_badges SET active=%s WHERE id=%s", (0, row[0]))
        else:
            c.execute("INSERT INTO student_super_badges (student_id, super_badge_id, active, created_at) VALUES (%s, %s, %s, %s)",
                      (student_id, badge_id, 1 if is_active else 0, now_str))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/api/student/<int:student_id>/super_badges/notes", methods=["GET"])
@login_required()
def get_super_badges_notes(tenant_slug, student_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT note, updated_at, user FROM student_super_badges_notes WHERE student_id=%s", (student_id,))
    row = c.fetchone()
    display_name = ""
    if row and row[2]:
        user_id = row[2]
        c.execute("SELECT name FROM users WHERE id=%s", (user_id,))
        user_row = c.fetchone()
        if user_row and user_row[0]:
            display_name = user_row[0]
        else:
            c.execute("SELECT name FROM teachers WHERE id=%s", (user_id,))
            teacher_row = c.fetchone()
            display_name = teacher_row[0] if teacher_row and teacher_row[0] else user_id
    return jsonify({"note": row[0] if row else "", "updated_at": row[1] if row else "", "user": display_name})


@school_bp.route("/api/student/<int:student_id>/super_badges/notes", methods=["POST"])
@login_required()
def save_super_badges_notes(tenant_slug, student_id):
    data = request.get_json()
    note = data.get("note", "").strip()
    user_id = session.get("school_user_id")
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT student_id FROM student_super_badges_notes WHERE student_id=%s", (student_id,))
    if c.fetchone():
        c.execute("UPDATE student_super_badges_notes SET note=%s, updated_at=%s, user=%s WHERE student_id=%s",
                  (note, updated_at, str(user_id), student_id))
    else:
        c.execute("INSERT INTO student_super_badges_notes (student_id, note, updated_at, user) VALUES (%s, %s, %s, %s)",
                  (student_id, note, updated_at, str(user_id)))
    db.commit()
    return jsonify({"success": True, "updated_at": updated_at, "user": user_id})


# ===================================================================
#  SUPPORT MATERIAL
# ===================================================================

@school_bp.route("/levels/<int:level_id>/support_material", methods=["POST"])
def upload_support_material(tenant_slug, level_id):
    if "file" not in request.files:
        return jsonify({"success": False, "error": "\u0644\u0645 \u064a\u062a\u0645 \u0627\u062e\u062a\u064a\u0627\u0631 \u0645\u0644\u0641"}), 400
    file = request.files["file"]
    description = request.form.get("description", "").strip()
    if not file or file.filename == "":
        return jsonify({"success": False, "error": "\u0627\u0633\u0645 \u0627\u0644\u0645\u0644\u0641 \u0641\u0627\u0631\u063a"}), 400
    if not description:
        return jsonify({"success": False, "error": "\u0627\u0644\u0648\u0635\u0641 \u0645\u0637\u0644\u0648\u0628"}), 400
    original_filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"level{level_id}_{timestamp}_{original_filename}"
    folder = _support_material_folder()
    file_path = os.path.join(folder, filename)
    file.save(file_path)
    uploader = session.get("school_username", "Admin")
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("INSERT INTO support_material (level_id, filename, original_filename, description, uploader, date) VALUES (%s, %s, %s, %s, %s, %s)",
              (level_id, filename, original_filename, description, uploader, date))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/levels/<int:level_id>/support_material", methods=["GET"])
def list_support_material(tenant_slug, level_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT id, filename, original_filename, description, uploader, date FROM support_material WHERE level_id=%s ORDER BY id DESC", (level_id,))
    files = [
        {
            "id": r[0], "filename": r[2],
            "url": url_for("school.serve_support_material", tenant_slug=tenant_slug, filename=r[1]),
            "description": r[3], "uploader": r[4], "date": r[5],
        }
        for r in c.fetchall()
    ]
    return jsonify(files)


@school_bp.route("/support_material/<filename>")
@login_required()
def serve_support_material(tenant_slug, filename):
    return send_from_directory(_support_material_folder(), filename, as_attachment=False)


@school_bp.route("/support_material/<int:support_id>", methods=["DELETE"])
def delete_support_material(tenant_slug, support_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    c.execute("SELECT filename FROM support_material WHERE id=%s", (support_id,))
    row = c.fetchone()
    if not row:
        return jsonify({"success": False, "error": "\u0644\u0645 \u064a\u062a\u0645 \u0627\u0644\u0639\u062b\u0648\u0631 \u0639\u0644\u0649 \u0627\u0644\u0645\u0644\u0641"}), 404
    fpath = os.path.join(_support_material_folder(), row[0])
    if os.path.exists(fpath):
        try:
            os.remove(fpath)
        except Exception:
            pass
    c.execute("DELETE FROM support_material WHERE id=%s", (support_id,))
    db.commit()
    return jsonify({"success": True})


@school_bp.route("/support_material/<int:support_id>", methods=["PUT"])
def edit_support_material(tenant_slug, support_id):
    db = get_school_db(tenant_slug)
    c = db.cursor()
    if request.content_type and request.content_type.startswith("multipart/form-data"):
        new_desc = request.form.get("description", "").strip()
        file = request.files.get("file")
    else:
        data = request.get_json()
        new_desc = data.get("description", "").strip() if data else ""
        file = None
    if not new_desc:
        return jsonify({"success": False, "error": "\u0627\u0644\u0648\u0635\u0641 \u0645\u0637\u0644\u0648\u0628"}), 400
    c.execute("SELECT filename, level_id FROM support_material WHERE id=%s", (support_id,))
    row = c.fetchone()
    if not row:
        return jsonify({"success": False, "error": "\u0644\u0645 \u064a\u062a\u0645 \u0627\u0644\u0639\u062b\u0648\u0631 \u0639\u0644\u0649 \u0627\u0644\u0645\u0644\u0641"}), 404
    old_filename, level_id = row[0], row[1]
    folder = _support_material_folder()
    if file and file.filename:
        old_path = os.path.join(folder, old_filename)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass
        original_filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        new_filename = f"level{level_id}_{timestamp}_{original_filename}"
        file.save(os.path.join(folder, new_filename))
        c.execute("UPDATE support_material SET description=%s, filename=%s, original_filename=%s WHERE id=%s",
                  (new_desc, new_filename, original_filename, support_id))
    else:
        c.execute("UPDATE support_material SET description=%s WHERE id=%s", (new_desc, support_id))
    db.commit()
    return jsonify({"success": True})


# ===================================================================
#  ERROR HANDLER
# ===================================================================

@school_bp.app_errorhandler(413)
def file_too_large(e):
    if request.accept_mimetypes["application/json"] or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": False, "error": "\u0627\u0644\u0645\u0644\u0641 \u0623\u0643\u0628\u0631 \u0645\u0646 \u0627\u0644\u062d\u062c\u0645 \u0627\u0644\u0645\u0633\u0645\u0648\u062d (20MB)"}), 413
    return "<h3 style=\"color:red\">\u0627\u0644\u0645\u0644\u0641 \u0623\u0643\u0628\u0631 \u0645\u0646 \u0627\u0644\u062d\u062c\u0645 \u0627\u0644\u0645\u0633\u0645\u0648\u062d (20MB)</h3>", 413

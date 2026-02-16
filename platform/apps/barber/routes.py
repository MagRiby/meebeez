"""Barber app blueprint — full CRUD endpoints."""

import os
from functools import wraps

from flask import (
    Blueprint, jsonify, request, session, redirect, url_for,
    render_template,
)
from werkzeug.security import generate_password_hash, check_password_hash

from apps.barber.db_utils import get_barber_db

barber_bp = Blueprint(
    "barber",
    __name__,
    url_prefix="/t/<tenant_slug>/barber",
)


# ── Auth decorator ──────────────────────────────────────────────────

def login_required(*roles):
    """Require the user to be logged into the barber tenant app."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            tenant_slug = kwargs.get("tenant_slug", "")
            if "barber_user_id" not in session:
                return redirect(url_for("barber.barber_login", tenant_slug=tenant_slug))
            if session.get("barber_tenant") != tenant_slug:
                return redirect(url_for("barber.barber_login", tenant_slug=tenant_slug))
            if roles and session.get("barber_role") not in roles:
                return "Unauthorized", 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ── Auth routes ─────────────────────────────────────────────────────

@barber_bp.route("/")
def index(tenant_slug):
    if "barber_user_id" in session and session.get("barber_tenant") == tenant_slug:
        return redirect(url_for("barber.dashboard", tenant_slug=tenant_slug))
    return redirect(url_for("barber.barber_login", tenant_slug=tenant_slug))


@barber_bp.route("/login", methods=["GET", "POST"])
def barber_login(tenant_slug):
    if request.method == "GET":
        return render_template("barber/login.html", tenant_slug=tenant_slug)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        return render_template("barber/login.html", tenant_slug=tenant_slug, error="Username and password are required")

    db = get_barber_db(tenant_slug)
    user = db.execute("SELECT * FROM users WHERE username=? AND is_active=1", (username,)).fetchone()

    if not user or not check_password_hash(user["password_hash"], password):
        return render_template("barber/login.html", tenant_slug=tenant_slug, error="Invalid credentials")

    session["barber_user_id"] = user["id"]
    session["barber_role"] = user["role"]
    session["barber_username"] = user["username"]
    session["barber_tenant"] = tenant_slug
    return redirect(url_for("barber.dashboard", tenant_slug=tenant_slug))


@barber_bp.route("/logout")
def barber_logout(tenant_slug):
    session.pop("barber_user_id", None)
    session.pop("barber_role", None)
    session.pop("barber_username", None)
    session.pop("barber_tenant", None)
    return redirect(url_for("barber.barber_login", tenant_slug=tenant_slug))


# ── Dashboard ───────────────────────────────────────────────────────

@barber_bp.route("/dashboard")
@login_required()
def dashboard(tenant_slug):
    return render_template(
        "barber/dashboard.html",
        tenant_slug=tenant_slug,
        role=session.get("barber_role"),
        username=session.get("barber_username"),
    )


# ── Services CRUD ───────────────────────────────────────────────────

@barber_bp.route("/api/services", methods=["GET"])
@login_required()
def list_services(tenant_slug):
    db = get_barber_db(tenant_slug)
    rows = db.execute("SELECT * FROM services ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])


@barber_bp.route("/api/services", methods=["POST"])
@login_required("admin")
def create_service(tenant_slug):
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    db = get_barber_db(tenant_slug)
    db.execute(
        "INSERT INTO services (name, description, duration_minutes, price, is_active) VALUES (?, ?, ?, ?, ?)",
        (name, data.get("description", ""), data.get("duration_minutes", 30),
         data.get("price", 0.0), 1),
    )
    db.commit()
    return jsonify({"message": "Service created"}), 201


@barber_bp.route("/api/services/<int:service_id>", methods=["PUT"])
@login_required("admin")
def update_service(tenant_slug, service_id):
    data = request.get_json() or {}
    db = get_barber_db(tenant_slug)
    existing = db.execute("SELECT id FROM services WHERE id=?", (service_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Service not found"}), 404

    db.execute(
        "UPDATE services SET name=?, description=?, duration_minutes=?, price=?, is_active=? WHERE id=?",
        (data.get("name", ""), data.get("description", ""),
         data.get("duration_minutes", 30), data.get("price", 0.0),
         1 if data.get("is_active", True) else 0, service_id),
    )
    db.commit()
    return jsonify({"message": "Service updated"})


@barber_bp.route("/api/services/<int:service_id>", methods=["DELETE"])
@login_required("admin")
def delete_service(tenant_slug, service_id):
    db = get_barber_db(tenant_slug)
    db.execute("DELETE FROM services WHERE id=?", (service_id,))
    db.commit()
    return jsonify({"message": "Service deleted"})


# ── Staff CRUD ──────────────────────────────────────────────────────

@barber_bp.route("/api/staff", methods=["GET"])
@login_required()
def list_staff(tenant_slug):
    db = get_barber_db(tenant_slug)
    rows = db.execute("SELECT * FROM staff ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])


@barber_bp.route("/api/staff", methods=["POST"])
@login_required("admin")
def create_staff(tenant_slug):
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    db = get_barber_db(tenant_slug)
    db.execute(
        "INSERT INTO staff (user_id, name, email, phone, specialization, is_active) VALUES (?, ?, ?, ?, ?, ?)",
        (data.get("user_id"), name, data.get("email", ""),
         data.get("phone", ""), data.get("specialization", ""), 1),
    )
    db.commit()
    return jsonify({"message": "Staff created"}), 201


@barber_bp.route("/api/staff/<int:staff_id>", methods=["PUT"])
@login_required("admin")
def update_staff(tenant_slug, staff_id):
    data = request.get_json() or {}
    db = get_barber_db(tenant_slug)
    existing = db.execute("SELECT id FROM staff WHERE id=?", (staff_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Staff not found"}), 404

    db.execute(
        "UPDATE staff SET name=?, email=?, phone=?, specialization=?, is_active=? WHERE id=?",
        (data.get("name", ""), data.get("email", ""),
         data.get("phone", ""), data.get("specialization", ""),
         1 if data.get("is_active", True) else 0, staff_id),
    )
    db.commit()
    return jsonify({"message": "Staff updated"})


@barber_bp.route("/api/staff/<int:staff_id>", methods=["DELETE"])
@login_required("admin")
def delete_staff(tenant_slug, staff_id):
    db = get_barber_db(tenant_slug)
    db.execute("DELETE FROM staff WHERE id=?", (staff_id,))
    db.commit()
    return jsonify({"message": "Staff deleted"})


# ── Clients CRUD ────────────────────────────────────────────────────

@barber_bp.route("/api/clients", methods=["GET"])
@login_required()
def list_clients(tenant_slug):
    db = get_barber_db(tenant_slug)
    search = request.args.get("search", "").strip()
    if search:
        like = f"%{search}%"
        rows = db.execute(
            "SELECT * FROM clients WHERE name LIKE ? OR email LIKE ? OR phone LIKE ? ORDER BY id",
            (like, like, like),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM clients ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])


@barber_bp.route("/api/clients", methods=["POST"])
@login_required()
def create_client(tenant_slug):
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    db = get_barber_db(tenant_slug)
    db.execute(
        "INSERT INTO clients (name, email, phone, notes) VALUES (?, ?, ?, ?)",
        (name, data.get("email", ""), data.get("phone", ""), data.get("notes", "")),
    )
    db.commit()
    return jsonify({"message": "Client created"}), 201


@barber_bp.route("/api/clients/<int:client_id>", methods=["PUT"])
@login_required()
def update_client(tenant_slug, client_id):
    data = request.get_json() or {}
    db = get_barber_db(tenant_slug)
    existing = db.execute("SELECT id FROM clients WHERE id=?", (client_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Client not found"}), 404

    db.execute(
        "UPDATE clients SET name=?, email=?, phone=?, notes=? WHERE id=?",
        (data.get("name", ""), data.get("email", ""),
         data.get("phone", ""), data.get("notes", ""), client_id),
    )
    db.commit()
    return jsonify({"message": "Client updated"})


@barber_bp.route("/api/clients/<int:client_id>", methods=["DELETE"])
@login_required("admin")
def delete_client(tenant_slug, client_id):
    db = get_barber_db(tenant_slug)
    db.execute("DELETE FROM clients WHERE id=?", (client_id,))
    db.commit()
    return jsonify({"message": "Client deleted"})


# ── Appointments CRUD ───────────────────────────────────────────────

@barber_bp.route("/api/appointments", methods=["GET"])
@login_required()
def list_appointments(tenant_slug):
    db = get_barber_db(tenant_slug)
    query = """
        SELECT a.*, c.name AS client_name, s.name AS staff_name, sv.name AS service_name
        FROM appointments a
        LEFT JOIN clients c ON a.client_id = c.id
        LEFT JOIN staff s ON a.staff_id = s.id
        LEFT JOIN services sv ON a.service_id = sv.id
        WHERE 1=1
    """
    params = []

    date_filter = request.args.get("date")
    if date_filter:
        query += " AND a.date = ?"
        params.append(date_filter)

    staff_filter = request.args.get("staff_id")
    if staff_filter:
        query += " AND a.staff_id = ?"
        params.append(staff_filter)

    status_filter = request.args.get("status")
    if status_filter:
        query += " AND a.status = ?"
        params.append(status_filter)

    query += " ORDER BY a.date, a.time"
    rows = db.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@barber_bp.route("/api/appointments", methods=["POST"])
@login_required()
def create_appointment(tenant_slug):
    data = request.get_json() or {}
    required = ["client_id", "staff_id", "service_id", "date", "time"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"{field} is required"}), 400

    db = get_barber_db(tenant_slug)
    db.execute(
        """INSERT INTO appointments (client_id, staff_id, service_id, date, time, duration, status, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (data["client_id"], data["staff_id"], data["service_id"],
         data["date"], data["time"], data.get("duration", 30),
         data.get("status", "scheduled"), data.get("notes", "")),
    )
    db.commit()
    return jsonify({"message": "Appointment created"}), 201


@barber_bp.route("/api/appointments/<int:appt_id>", methods=["PUT"])
@login_required()
def update_appointment(tenant_slug, appt_id):
    data = request.get_json() or {}
    db = get_barber_db(tenant_slug)
    existing = db.execute("SELECT id FROM appointments WHERE id=?", (appt_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Appointment not found"}), 404

    db.execute(
        """UPDATE appointments SET client_id=?, staff_id=?, service_id=?, date=?, time=?,
           duration=?, status=?, notes=? WHERE id=?""",
        (data.get("client_id"), data.get("staff_id"), data.get("service_id"),
         data.get("date"), data.get("time"), data.get("duration", 30),
         data.get("status", "scheduled"), data.get("notes", ""), appt_id),
    )
    db.commit()
    return jsonify({"message": "Appointment updated"})


@barber_bp.route("/api/appointments/<int:appt_id>", methods=["DELETE"])
@login_required("admin")
def delete_appointment(tenant_slug, appt_id):
    db = get_barber_db(tenant_slug)
    db.execute("DELETE FROM appointments WHERE id=?", (appt_id,))
    db.commit()
    return jsonify({"message": "Appointment deleted"})


# ── Working Hours CRUD ──────────────────────────────────────────────

@barber_bp.route("/api/working-hours/<int:staff_id>", methods=["GET"])
@login_required()
def get_working_hours(tenant_slug, staff_id):
    db = get_barber_db(tenant_slug)
    rows = db.execute(
        "SELECT * FROM working_hours WHERE staff_id=? ORDER BY day_of_week, start_time",
        (staff_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@barber_bp.route("/api/working-hours", methods=["POST"])
@login_required("admin")
def create_working_hours(tenant_slug):
    data = request.get_json() or {}
    required = ["staff_id", "day_of_week", "start_time", "end_time"]
    for field in required:
        if data.get(field) is None:
            return jsonify({"error": f"{field} is required"}), 400

    db = get_barber_db(tenant_slug)
    db.execute(
        "INSERT INTO working_hours (staff_id, day_of_week, start_time, end_time, is_active) VALUES (?, ?, ?, ?, ?)",
        (data["staff_id"], data["day_of_week"], data["start_time"],
         data["end_time"], 1),
    )
    db.commit()
    return jsonify({"message": "Working hours created"}), 201


@barber_bp.route("/api/working-hours/<int:wh_id>", methods=["DELETE"])
@login_required("admin")
def delete_working_hours(tenant_slug, wh_id):
    db = get_barber_db(tenant_slug)
    db.execute("DELETE FROM working_hours WHERE id=?", (wh_id,))
    db.commit()
    return jsonify({"message": "Working hours deleted"})

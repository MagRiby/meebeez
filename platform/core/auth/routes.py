from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import request, jsonify, current_app
from werkzeug.security import generate_password_hash, check_password_hash

from core.auth import auth_bp
from core.extensions import db
from core.models import User


def create_token(user):
    payload = {
        "user_id": user.id,
        "email": user.email,
        "role": user.role,
        "exp": datetime.now(timezone.utc)
        + timedelta(hours=current_app.config["JWT_EXPIRATION_HOURS"]),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        # Check Authorization header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        # Fall back to cookie
        if not token:
            token = request.cookies.get("token")

        if not token:
            return jsonify({"error": "Authentication required"}), 401

        try:
            payload = jwt.decode(
                token, current_app.config["SECRET_KEY"], algorithms=["HS256"]
            )
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

        user = db.session.get(User, payload["user_id"])
        if not user or not user.is_active:
            return jsonify({"error": "User not found or inactive"}), 401

        request.current_user = user
        return f(*args, **kwargs)

    return decorated


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    name = data.get("name", "").strip()
    role = data.get("role", "client")

    if not email or not password or not name:
        return jsonify({"error": "email, password, and name are required"}), 400

    if role not in ("business_owner", "client"):
        return jsonify({"error": "role must be business_owner or client"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 409

    user = User(
        email=email,
        password_hash=generate_password_hash(password),
        name=name,
        role=role,
    )
    db.session.add(user)
    db.session.commit()

    token = create_token(user)
    response = jsonify(
        {
            "message": "User registered successfully",
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "role": user.role,
            },
            "token": token,
        }
    )
    response.set_cookie(
        "token", token, httponly=True, samesite="Lax", max_age=86400
    )
    return response, 201


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid email or password"}), 401

    if not user.is_active:
        return jsonify({"error": "Account is disabled"}), 403

    token = create_token(user)
    response = jsonify(
        {
            "message": "Login successful",
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "role": user.role,
            },
            "token": token,
        }
    )
    response.set_cookie(
        "token", token, httponly=True, samesite="Lax", max_age=86400
    )
    return response, 200


@auth_bp.route("/me", methods=["GET"])
@auth_required
def me():
    user = request.current_user
    return jsonify(
        {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat(),
        }
    )


@auth_bp.route("/logout", methods=["POST"])
def logout():
    response = jsonify({"message": "Logged out"})
    response.delete_cookie("token")
    return response, 200

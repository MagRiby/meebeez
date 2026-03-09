from flask import Blueprint

stripe_bp = Blueprint("stripe", __name__)

from core.stripe import routes  # noqa: E402, F401

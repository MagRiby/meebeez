from flask import Blueprint

marketplace_bp = Blueprint("marketplace", __name__)

from core.marketplace import routes  # noqa: E402, F401

"""School app blueprint.

TODO: Migrate routes from arabicschool/main.py in a future phase.
"""

from flask import Blueprint, jsonify

school_bp = Blueprint("school", __name__, url_prefix="/t/<tenant_slug>/school")


@school_bp.route("/", methods=["GET"])
def index(tenant_slug):
    return jsonify({"app": "school", "tenant": tenant_slug, "status": "placeholder"})

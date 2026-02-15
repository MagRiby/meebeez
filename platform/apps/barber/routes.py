"""Barber app blueprint — placeholder endpoints."""

from flask import Blueprint, jsonify

barber_bp = Blueprint("barber", __name__, url_prefix="/t/<tenant_slug>/barber")


@barber_bp.route("/", methods=["GET"])
def index(tenant_slug):
    return jsonify({"app": "barber", "tenant": tenant_slug, "status": "placeholder"})

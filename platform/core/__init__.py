import os

from flask import Flask, render_template, session, make_response

from config import config_by_name
from core.extensions import db, migrate, mail, cache, csrf


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "dev")

    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
        static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"),
    )
    app.config.from_object(config_by_name[config_name])

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    cache.init_app(app)
    csrf.init_app(app)

    # Register blueprints
    from core.auth import auth_bp
    from core.marketplace import marketplace_bp
    from core.portal import portal_bp
    from core.admin import admin_bp
    from core.stripe import stripe_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(marketplace_bp)
    app.register_blueprint(portal_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(stripe_bp)

    # Exempt JWT-authenticated API blueprints from CSRF
    # (they use Authorization header / token cookie, not session-based forms)
    csrf.exempt(auth_bp)
    csrf.exempt(marketplace_bp)
    csrf.exempt(portal_bp)
    csrf.exempt(admin_bp)
    csrf.exempt(stripe_bp)

    # Discover and register app modules
    from apps import discover_apps, registry

    discover_apps()

    for app_module in registry.list_all():
        bp = app_module.get_blueprint()
        app.register_blueprint(bp)
        csrf.exempt(bp)

    # Seed app definitions
    with app.app_context():
        _seed_app_definitions(registry)

    # Close psycopg tenant connections after every request
    from core.tenants.db_manager import init_db_teardown
    init_db_teardown(app)

    # Landing page — combined login / register
    @app.route("/")
    def landing():
        return render_template("auth/entry.html")

    # Auth template routes
    @app.route("/login")
    def login_page():
        return render_template("auth/login.html")

    @app.route("/register")
    def register_page():
        return render_template("auth/register.html")

    # Universal sign-out — clears session, JWT cookie, and localStorage then → /
    @app.route("/signout")
    def signout():
        session.clear()
        resp = make_response(
            "<!DOCTYPE html><html><head><script>"
            "localStorage.removeItem('token');"
            "window.location.replace('/');"
            "</script></head><body></body></html>"
        )
        resp.delete_cookie("token")
        return resp

    # App detail page
    @app.route("/apps/<slug>")
    def app_detail(slug):
        from core.models import AppDefinition

        app_def = AppDefinition.query.filter_by(slug=slug, is_active=True).first_or_404()
        return render_template("marketplace/app_detail.html", app=app_def)

    return app


def _seed_app_definitions(registry):
    """Ensure AppDefinition rows exist for all registered apps."""
    from core.models import AppDefinition

    db.create_all()

    for app_module in registry.list_all():
        existing = AppDefinition.query.filter_by(slug=app_module.slug).first()
        if not existing:
            app_def = AppDefinition(
                slug=app_module.slug,
                name=app_module.name,
                description=app_module.description,
                icon=app_module.icon,
            )
            db.session.add(app_def)

    db.session.commit()

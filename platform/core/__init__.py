import os

from flask import Flask, render_template

from config import config_by_name
from core.extensions import db, migrate, mail, cache


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

    # Register blueprints
    from core.auth import auth_bp
    from core.marketplace import marketplace_bp
    from core.portal import portal_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(marketplace_bp)
    app.register_blueprint(portal_bp)

    # Discover and register app modules
    from apps import discover_apps, registry

    discover_apps()

    for app_module in registry.list_all():
        bp = app_module.get_blueprint()
        app.register_blueprint(bp)

    # Seed app definitions
    with app.app_context():
        _seed_app_definitions(registry)

    # Landing page
    @app.route("/")
    def landing():
        from core.models import AppDefinition

        apps = AppDefinition.query.filter_by(is_active=True).all()
        return render_template("landing.html", apps=apps)

    # Auth template routes
    @app.route("/login")
    def login_page():
        return render_template("auth/login.html")

    @app.route("/register")
    def register_page():
        return render_template("auth/register.html")

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

from apps.base import BaseApp
from apps.school.models import TenantBase


class SchoolApp(BaseApp):
    @property
    def name(self):
        return "School"

    @property
    def slug(self):
        return "school"

    @property
    def description(self):
        return "Manage classes, students, teachers, curriculum, attendance, and grades."

    @property
    def icon(self):
        return "fas fa-school"

    def setup_schema(self, engine):
        """Create tables using SQLAlchemy models (for PostgreSQL tenants)
        or use raw SQL init (for SQLite tenants)."""
        TenantBase.metadata.create_all(engine)

    def setup_schema_sqlite(self, tenant_slug):
        """Initialize schema using raw SQL for SQLite tenant databases."""
        from apps.school.db_utils import init_school_db
        init_school_db(tenant_slug)

    def get_blueprint(self):
        from apps.school.routes import school_bp
        return school_bp

from apps.base import BaseApp
from apps.barber.models import TenantBase


class BarberApp(BaseApp):
    @property
    def name(self):
        return "Barber"

    @property
    def slug(self):
        return "barber"

    @property
    def description(self):
        return "Manage appointments, services, staff schedules, and clients."

    @property
    def icon(self):
        return "fas fa-cut"

    def setup_schema(self, engine):
        TenantBase.metadata.create_all(engine)

    def setup_schema_sqlite(self, tenant_slug):
        """Initialize schema using raw SQL for SQLite."""
        from apps.barber.db_utils import init_barber_db
        init_barber_db(tenant_slug)

    def get_blueprint(self):
        from apps.barber.routes import barber_bp
        return barber_bp

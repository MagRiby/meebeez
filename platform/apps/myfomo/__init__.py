from apps.base import BaseApp
from apps.myfomo.models import TenantBase


class MyFomoApp(BaseApp):
    @property
    def name(self):
        return "myFomo"

    @property
    def slug(self):
        return "myfomo"

    @property
    def description(self):
        return "Social commerce and advertising for store owners and followers."

    @property
    def icon(self):
        return "fas fa-bullhorn"

    def setup_schema(self, engine):
        TenantBase.metadata.create_all(engine)

    def setup_schema_sqlite(self, tenant_slug):
        """Initialize schema using raw SQL for SQLite."""
        from apps.myfomo.db_utils import init_myfomo_db
        init_myfomo_db(tenant_slug)

    def get_blueprint(self):
        from apps.myfomo.routes import myfomo_bp
        return myfomo_bp

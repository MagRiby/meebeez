from apps.base import BaseApp
from apps.shop.models import TenantBase


class ShopApp(BaseApp):
    @property
    def name(self):
        return "Shop"

    @property
    def slug(self):
        return "shop"

    @property
    def description(self):
        return "Manage products, inventory, suppliers, purchase orders, and sales."

    @property
    def icon(self):
        return "fas fa-store"

    def setup_schema(self, engine):
        TenantBase.metadata.create_all(engine)

    def setup_schema_sqlite(self, tenant_slug):
        """Initialize schema using raw SQL for SQLite."""
        from apps.shop.db_utils import init_shop_db
        init_shop_db(tenant_slug)

    def get_blueprint(self):
        from apps.shop.routes import shop_bp
        return shop_bp

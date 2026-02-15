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
        TenantBase.metadata.create_all(engine)

    def get_blueprint(self):
        from apps.school.routes import school_bp
        return school_bp

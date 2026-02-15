from abc import ABC, abstractmethod


class BaseApp(ABC):
    """Abstract base class for all pluggable app modules."""

    @property
    @abstractmethod
    def name(self):
        """Human-readable app name."""

    @property
    @abstractmethod
    def slug(self):
        """Unique identifier slug."""

    @property
    def description(self):
        return ""

    @property
    def icon(self):
        return "fas fa-cube"

    @abstractmethod
    def setup_schema(self, engine):
        """Create tenant-level tables in the given database engine."""

    @abstractmethod
    def get_blueprint(self):
        """Return the Flask blueprint for this app's routes."""

from apps.base import BaseApp


class AppRegistry:
    """Registry of all available app modules."""

    def __init__(self):
        self._apps = {}

    def register(self, app):
        if not isinstance(app, BaseApp):
            raise TypeError(f"{app} must be an instance of BaseApp")
        self._apps[app.slug] = app

    def get(self, slug):
        return self._apps.get(slug)

    def list_all(self):
        return list(self._apps.values())


registry = AppRegistry()


def discover_apps():
    """Import all app modules so they self-register."""
    from apps.school import SchoolApp
    from apps.barber import BarberApp
    from apps.shop import ShopApp
    from apps.myfomo import MyFomoApp

    registry.register(SchoolApp())
    registry.register(BarberApp())
    registry.register(ShopApp())
    registry.register(MyFomoApp())

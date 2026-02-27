from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_mail import Mail
from flask_caching import Cache
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
mail = Mail()
cache = Cache(config={"CACHE_TYPE": "SimpleCache"})
csrf = CSRFProtect()

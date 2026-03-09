import os
import sys


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if not SECRET_KEY or SECRET_KEY in ("change-me-in-production", "change-me-to-a-random-secret"):
        if os.environ.get("FLASK_ENV") == "prod":
            print("FATAL: SECRET_KEY must be set to a secure random value in production.", file=sys.stderr)
            sys.exit(1)
        SECRET_KEY = "dev-only-insecure-key-not-for-production"
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql://localhost/saas_platform"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": 5,
        "max_overflow": 10,
        "connect_args": {"connect_timeout": 10},
    }
    JWT_EXPIRATION_HOURS = int(os.environ.get("JWT_EXPIRATION_HOURS", "24"))

    # Mail settings
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")

    # File upload limit
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20 MB

    # Tenant DB base URI (without database name)
    TENANT_DB_BASE_URI = os.environ.get(
        "TENANT_DB_BASE_URI", "postgresql://localhost"
    )

    # Stripe
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_PLATFORM_FEE_PERCENT = float(
        os.environ.get("STRIPE_PLATFORM_FEE_PERCENT", "5")
    )


class DevConfig(Config):
    DEBUG = True


class ProdConfig(Config):
    DEBUG = False


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


config_by_name = {
    "dev": DevConfig,
    "prod": ProdConfig,
    "test": TestConfig,
}

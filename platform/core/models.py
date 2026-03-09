from datetime import datetime, timezone

from core.extensions import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    role = db.Column(
        db.String(50), nullable=False, default="client"
    )  # platform_admin | business_owner | client
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    tenants_owned = db.relationship("Tenant", backref="owner", lazy="dynamic")
    memberships = db.relationship(
        "TenantMembership", backref="user", lazy="dynamic"
    )


class AppDefinition(db.Model):
    __tablename__ = "app_definitions"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, default="")
    icon = db.Column(db.String(100), default="fas fa-cube")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    tenants = db.relationship("Tenant", backref="app_definition", lazy="dynamic")


class Tenant(db.Model):
    __tablename__ = "tenants"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    app_type_slug = db.Column(
        db.String(100),
        db.ForeignKey("app_definitions.slug"),
        nullable=False,
    )
    owner_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    db_name = db.Column(db.String(255), unique=True, nullable=False)
    status = db.Column(
        db.String(50), nullable=False, default="provisioning"
    )  # provisioning | active | suspended
    stripe_account_id = db.Column(db.String(255), nullable=True)
    stripe_onboarded = db.Column(db.Boolean, default=False)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    memberships = db.relationship(
        "TenantMembership", backref="tenant", lazy="dynamic"
    )
    subscription = db.relationship(
        "Subscription", backref="tenant", uselist=False
    )


class TenantMembership(db.Model):
    __tablename__ = "tenant_memberships"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    tenant_id = db.Column(
        db.Integer, db.ForeignKey("tenants.id"), nullable=False
    )
    role_in_tenant = db.Column(
        db.String(50), nullable=False, default="client"
    )  # admin | staff | client
    joined_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        db.UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),
    )


class Subscription(db.Model):
    __tablename__ = "subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey("tenants.id"),
        nullable=False,
        unique=True,
    )
    plan = db.Column(
        db.String(50), nullable=False, default="free"
    )  # free | basic | premium
    status = db.Column(
        db.String(50), nullable=False, default="active"
    )  # active | cancelled
    started_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    expires_at = db.Column(db.DateTime, nullable=True)

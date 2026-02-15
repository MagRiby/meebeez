"""Tenant-level models for the Barber app.

These models are created in each tenant's own database,
not in the platform database.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Time,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class TenantBase(DeclarativeBase):
    pass


class Service(TenantBase):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    duration_minutes = Column(Integer, nullable=False, default=30)
    price = Column(Float, nullable=False, default=0.0)
    is_active = Column(Boolean, default=True)

    appointments = relationship("Appointment", backref="service")


class Staff(TenantBase):
    __tablename__ = "staff"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    specialization = Column(String(255), default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    working_hours = relationship("WorkingHours", backref="staff")
    appointments = relationship("Appointment", backref="staff")


class Client(TenantBase):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    appointments = relationship("Appointment", backref="client")


class Appointment(TenantBase):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=False)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    appointment_date = Column(Date, nullable=False)
    appointment_time = Column(Time, nullable=False)
    duration_minutes = Column(Integer, nullable=False, default=30)
    status = Column(
        String(50), nullable=False, default="scheduled"
    )  # scheduled | completed | cancelled | no_show
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class WorkingHours(TenantBase):
    __tablename__ = "working_hours"

    id = Column(Integer, primary_key=True)
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0=Monday, 6=Sunday
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_active = Column(Boolean, default=True)

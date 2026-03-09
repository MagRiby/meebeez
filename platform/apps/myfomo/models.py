from sqlalchemy import (
    Column, Integer, String, Text, Float, DateTime, ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class TenantBase(DeclarativeBase):
    """Declarative base for all myfomo app models."""
    pass


class User(TenantBase):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(255), unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    name = Column(String(255))
    role = Column(String(50), nullable=False)  # admin | follower
    phone = Column(String(50), default="")
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime)
    bookings = relationship("Booking", backref="user")


class Post(TenantBase):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, default="")
    image_path = Column(Text, default="")
    post_type = Column(String(50), nullable=False, default="product")  # product | announcement | event
    price = Column(Float, default=0.0)
    original_quantity = Column(Integer, default=0)
    remaining_quantity = Column(Integer, default=0)
    sale_ends_at = Column(DateTime)
    status = Column(String(50), nullable=False, default="draft")  # draft | published | archived
    ai_generated = Column(Integer, default=0)
    created_at = Column(DateTime)
    bookings = relationship("Booking", backref="post")


class Event(TenantBase):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    image_path = Column(Text, default="")
    event_date = Column(String(20))
    event_time = Column(String(10))
    location = Column(String(255), default="")
    status = Column(String(50), nullable=False, default="upcoming")  # upcoming | passed | cancelled
    ai_generated = Column(Integer, default=0)
    created_at = Column(DateTime)


class Booking(TenantBase):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    status = Column(String(50), nullable=False, default="pending")  # pending | confirmed | cancelled | collected
    notes = Column(Text, default="")
    created_at = Column(DateTime)

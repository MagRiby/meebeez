from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, Date, DateTime, Float, ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class TenantBase(DeclarativeBase):
    """Declarative base for all shop app models."""
    pass


class User(TenantBase):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(255), unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    name = Column(String(255))
    role = Column(String(50), nullable=False)  # admin | staff
    is_active = Column(Boolean, default=True)


class Category(TenantBase):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    is_active = Column(Boolean, default=True)
    products = relationship("Product", backref="category")


class Product(TenantBase):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    sku = Column(String(100))
    description = Column(Text, default="")
    category_id = Column(Integer, ForeignKey("categories.id"))
    price = Column(Float, nullable=False, default=0.0)
    cost = Column(Float, nullable=False, default=0.0)
    quantity = Column(Integer, nullable=False, default=0)
    low_stock_threshold = Column(Integer, nullable=False, default=10)
    is_active = Column(Boolean, default=True)


class Supplier(TenantBase):
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    contact_name = Column(String(255), default="")
    email = Column(String(255), default="")
    phone = Column(String(50), default="")
    address = Column(Text, default="")
    notes = Column(Text, default="")
    purchase_orders = relationship("PurchaseOrder", backref="supplier")


class PurchaseOrder(TenantBase):
    __tablename__ = "purchase_orders"
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    order_date = Column(Date, nullable=False)
    status = Column(String(50), nullable=False, default="pending")  # pending | received | cancelled
    total_amount = Column(Float, nullable=False, default=0.0)
    notes = Column(Text, default="")
    items = relationship("PurchaseOrderItem", backref="purchase_order")


class PurchaseOrderItem(TenantBase):
    __tablename__ = "purchase_order_items"
    id = Column(Integer, primary_key=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    unit_cost = Column(Float, nullable=False, default=0.0)


class Sale(TenantBase):
    __tablename__ = "sales"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    total_amount = Column(Float, nullable=False, default=0.0)
    payment_method = Column(String(50), nullable=False, default="cash")  # cash | card | other
    notes = Column(Text, default="")
    created_by = Column(Integer, ForeignKey("users.id"))
    items = relationship("SaleItem", backref="sale")


class SaleItem(TenantBase):
    __tablename__ = "sale_items"
    id = Column(Integer, primary_key=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    unit_price = Column(Float, nullable=False, default=0.0)

#!/usr/bin/env python3
"""Seed script: creates demo business-owner accounts with MyFOMO stores.

Usage (from the platform/ directory):
    python scripts/seed_businesses.py

Creates 6 business-owner accounts, each with a MyFOMO store pre-configured
with branding, store settings, and a few sample posts (some featured).
Prints a summary table with login credentials at the end.
"""

import json
import os
import sys

# Ensure the platform package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from werkzeug.security import generate_password_hash

from core import create_app
from core.extensions import db
from core.models import User
from core.tenants.service import provision_tenant
from core.tenants.db_manager import get_tenant_connection

# -- Demo businesses -------------------------------------------------------
BUSINESSES = [
    {
        "owner_name": "Sarah Mitchell",
        "email": "sarah@demo.com",
        "password": "demo1234",
        "biz_name": "Sarah's Bakery",
        "category": "food",
        "tagline": "Freshly baked, always delicious",
        "brand_colors": ["#e85d04", "#faa307"],
        "posts": [
            {"title": "Croissant Basket", "body": "6 butter croissants, baked fresh every morning", "price": 12.99, "featured": 1},
            {"title": "Sourdough Loaf", "body": "Artisan sourdough with a crispy crust", "price": 8.50, "featured": 1},
            {"title": "Chocolate Eclair", "body": "Classic French eclair with dark chocolate ganache", "price": 5.00, "featured": 0},
            {"title": "Cinnamon Rolls (4-pack)", "body": "Warm, gooey cinnamon rolls with cream cheese icing", "price": 14.00, "featured": 1},
        ],
    },
    {
        "owner_name": "Ahmed Benali",
        "email": "ahmed@demo.com",
        "password": "demo1234",
        "biz_name": "Chez Ahmed",
        "category": "restaurants",
        "tagline": "Authentic Mediterranean cuisine",
        "brand_colors": ["#1d3557", "#e63946"],
        "posts": [
            {"title": "Lamb Tagine", "body": "Slow-cooked lamb with apricots and almonds", "price": 22.00, "featured": 1},
            {"title": "Falafel Platter", "body": "Crispy falafel with hummus, tabbouleh, and pita", "price": 14.50, "featured": 1},
            {"title": "Baklava Box", "body": "12 pieces of handmade pistachio baklava", "price": 18.00, "featured": 0},
            {"title": "Mint Lemonade (1L)", "body": "Refreshing house-made mint lemonade", "price": 6.00, "featured": 1},
            {"title": "Shakshuka Breakfast", "body": "Poached eggs in spiced tomato sauce with fresh bread", "price": 13.00, "featured": 0},
        ],
    },
    {
        "owner_name": "Lisa Chen",
        "email": "lisa@demo.com",
        "password": "demo1234",
        "biz_name": "ThreadLine",
        "category": "clothing",
        "tagline": "Sustainable fashion, bold style",
        "brand_colors": ["#6a0572", "#ab83a1"],
        "posts": [
            {"title": "Linen Summer Dress", "body": "Relaxed-fit linen dress in sage green", "price": 65.00, "featured": 1},
            {"title": "Recycled Denim Jacket", "body": "Upcycled denim with custom patches", "price": 89.00, "featured": 1},
            {"title": "Organic Cotton Tee", "body": "Classic crew neck tee in 5 colors", "price": 28.00, "featured": 0},
            {"title": "Bamboo Fiber Scarf", "body": "Ultra-soft scarf, perfect for layering", "price": 32.00, "featured": 1},
        ],
    },
    {
        "owner_name": "Marcus Johnson",
        "email": "marcus@demo.com",
        "password": "demo1234",
        "biz_name": "FitZone Gear",
        "category": "shopping",
        "tagline": "Gear up for greatness",
        "brand_colors": ["#ff6b35", "#004e89"],
        "posts": [
            {"title": "Resistance Band Set", "body": "5 bands with handles, door anchor, and carry bag", "price": 34.99, "featured": 1},
            {"title": "Foam Roller Pro", "body": "High-density foam roller for deep tissue recovery", "price": 29.00, "featured": 0},
            {"title": "Gym Duffel Bag", "body": "Water-resistant bag with shoe compartment", "price": 45.00, "featured": 1},
            {"title": "Protein Shaker Bottle", "body": "Leak-proof 750ml shaker with mixing ball", "price": 15.00, "featured": 1},
            {"title": "Yoga Mat (6mm)", "body": "Non-slip eco-friendly yoga mat", "price": 38.00, "featured": 0},
        ],
    },
    {
        "owner_name": "Fatima Zahra",
        "email": "fatima@demo.com",
        "password": "demo1234",
        "biz_name": "Glow Skincare",
        "category": "care",
        "tagline": "Natural beauty, radiant skin",
        "brand_colors": ["#2d6a4f", "#b7e4c7"],
        "posts": [
            {"title": "Vitamin C Serum", "body": "Brightening serum with 20% vitamin C and hyaluronic acid", "price": 42.00, "featured": 1},
            {"title": "Rose Clay Mask", "body": "Detoxifying mask for all skin types", "price": 28.00, "featured": 1},
            {"title": "Shea Butter Moisturizer", "body": "Rich daily moisturizer with organic shea butter", "price": 35.00, "featured": 0},
            {"title": "Lip Balm Trio", "body": "Vanilla, honey, and mint - all natural", "price": 12.00, "featured": 1},
        ],
    },
    {
        "owner_name": "David Park",
        "email": "david@demo.com",
        "password": "demo1234",
        "biz_name": "ByteBooks",
        "category": "learning",
        "tagline": "Code, learn, build - one page at a time",
        "brand_colors": ["#023e8a", "#0096c7"],
        "posts": [
            {"title": "Python for Beginners (eBook)", "body": "Step-by-step guide from zero to your first project", "price": 19.99, "featured": 1},
            {"title": "JavaScript Cheat Sheets", "body": "Printable reference cards for ES6+", "price": 9.99, "featured": 0},
            {"title": "Full-Stack Starter Kit", "body": "Boilerplate + video course: React + Flask", "price": 49.00, "featured": 1},
            {"title": "Data Structures Workbook", "body": "50 problems with solutions in Python and Java", "price": 24.00, "featured": 1},
            {"title": "Git Mastery Course", "body": "From commits to CI/CD pipelines", "price": 35.00, "featured": 0},
        ],
    },
]


def seed():
    results = []

    for biz in BUSINESSES:
        # 1. Create platform user (business_owner)
        existing = User.query.filter_by(email=biz["email"]).first()
        if existing:
            print(f"  [SKIP] User {biz['email']} already exists (id={existing.id}), skipping...")
            results.append({
                "email": biz["email"],
                "password": biz["password"],
                "biz_name": biz["biz_name"],
                "status": "SKIPPED (user exists)",
                "slug": "-",
            })
            continue

        user = User(
            email=biz["email"],
            password_hash=generate_password_hash(biz["password"]),
            name=biz["owner_name"],
            role="business_owner",
        )
        db.session.add(user)
        db.session.flush()  # get user.id

        # 2. Provision tenant (schema + records + admin seed)
        tenant, _temp_pw = provision_tenant(
            name=biz["biz_name"],
            app_slug="myfomo",
            owner_id=user.id,
        )
        print(f"  [OK] Created {biz['biz_name']} -> /t/{tenant.slug}/myfomo/")

        # 3. Update store_settings with branding & category
        conn = get_tenant_connection(tenant.slug)
        conn.execute(
            "INSERT INTO store_settings (id, brand_colors, business_tagline, category) "
            "VALUES (1, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET brand_colors=%s, business_tagline=%s, category=%s",
            (
                json.dumps(biz["brand_colors"]),
                biz["tagline"],
                biz["category"],
                json.dumps(biz["brand_colors"]),
                biz["tagline"],
                biz["category"],
            ),
        )

        # 4. Insert sample posts
        for post in biz["posts"]:
            conn.execute(
                "INSERT INTO posts (title, body, price, status, featured, post_type, "
                "original_quantity, remaining_quantity) "
                "VALUES (%s, %s, %s, 'published', %s, 'product', %s, %s)",
                (
                    post["title"],
                    post["body"],
                    post["price"],
                    post["featured"],
                    10,  # original_quantity
                    10,  # remaining_quantity
                ),
            )

        conn.commit()

        results.append({
            "email": biz["email"],
            "password": biz["password"],
            "biz_name": biz["biz_name"],
            "slug": tenant.slug,
            "status": "OK",
        })

    return results


def main():
    app = create_app()
    with app.app_context():
        print("\n--- Seeding demo businesses ---\n")
        results = seed()

        # Print summary table
        print("\n" + "=" * 80)
        print("  DEMO ACCOUNTS - LOGIN CREDENTIALS")
        print("=" * 80)
        print(f"  {'Email':<22} {'Password':<14} {'Business':<22} {'Status'}")
        print("-" * 80)
        for r in results:
            print(f"  {r['email']:<22} {r['password']:<14} {r['biz_name']:<22} {r['status']}")
        print("-" * 80)
        print(f"\n  Store URLs:  /t/<slug>/myfomo/store")
        for r in results:
            if r["status"] == "OK":
                print(f"    {r['biz_name']:<22} -> /t/{r['slug']}/myfomo/store")
        print("\n  All accounts use role: business_owner")
        print("  All passwords: demo1234\n")


if __name__ == "__main__":
    main()

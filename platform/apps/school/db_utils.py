"""Tenant-aware database utilities for the School app.

Provides a get_school_db() function that returns a raw DB connection
to the tenant's database, replacing the hardcoded sqlite3.connect()
calls from the original arabicschool app.
"""

import sqlite3
import os

from flask import g, current_app
from core.models import Tenant


def _get_tenant_db_path(tenant_slug):
    """Get the SQLite database file path for a tenant."""
    instance_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "instance",
        "tenants",
    )
    os.makedirs(instance_dir, exist_ok=True)
    return os.path.join(instance_dir, f"{tenant_slug}.db")


def get_school_db(tenant_slug):
    """Get a SQLite connection for the given tenant.

    Uses Flask's g object to cache the connection per-request.
    """
    cache_key = f"school_db_{tenant_slug}"
    if not hasattr(g, cache_key):
        db_path = _get_tenant_db_path(tenant_slug)
        conn = sqlite3.connect(db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        setattr(g, cache_key, conn)
    return getattr(g, cache_key)


def close_school_db(tenant_slug):
    """Close the cached connection for a tenant."""
    cache_key = f"school_db_{tenant_slug}"
    conn = g.pop(cache_key, None)
    if conn is not None:
        conn.close()


def init_school_db(tenant_slug):
    """Initialize the school database schema for a tenant using raw SQL.

    This is called during tenant provisioning as an alternative to
    SQLAlchemy's create_all() for maximum compatibility with the
    existing arabicschool schema.
    """
    conn = sqlite3.connect(_get_tenant_db_path(tenant_slug), timeout=10)
    c = conn.cursor()
    conn.execute("PRAGMA journal_mode=WAL;")

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT,
        role TEXT NOT NULL CHECK(role IN ('super_admin', 'local_admin', 'teacher', 'student')),
        created_by INTEGER,
        is_director INTEGER DEFAULT 0,
        FOREIGN KEY(created_by) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        local_admin_id INTEGER NOT NULL,
        name TEXT,
        email TEXT,
        phone TEXT,
        notes TEXT,
        alerts TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(local_admin_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS levels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        local_admin_id INTEGER NOT NULL,
        FOREIGN KEY(local_admin_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        teacher_id INTEGER,
        local_admin_id INTEGER NOT NULL,
        level_id INTEGER,
        backup_teacher_id INTEGER,
        dawra1_pub_start TEXT,
        dawra1_pub_end TEXT,
        dawra2_pub_start TEXT,
        dawra2_pub_end TEXT,
        dawra3_pub_start TEXT,
        dawra3_pub_end TEXT,
        year_pub_start TEXT,
        year_pub_end TEXT,
        FOREIGN KEY(teacher_id) REFERENCES teachers(id),
        FOREIGN KEY(local_admin_id) REFERENCES users(id),
        FOREIGN KEY(level_id) REFERENCES levels(id),
        FOREIGN KEY(backup_teacher_id) REFERENCES teachers(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        class_id INTEGER,
        email TEXT,
        phone TEXT,
        notes TEXT,
        alerts TEXT,
        date_of_birth TEXT,
        secondary_email TEXT,
        sex TEXT,
        FOREIGN KEY(class_id) REFERENCES classes(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS curriculum_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        local_admin_id INTEGER NOT NULL,
        level_id INTEGER NOT NULL,
        FOREIGN KEY(local_admin_id) REFERENCES users(id),
        FOREIGN KEY(level_id) REFERENCES levels(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS curriculum_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        FOREIGN KEY(group_id) REFERENCES curriculum_groups(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS class_courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER NOT NULL,
        curriculum_item_id INTEGER NOT NULL,
        FOREIGN KEY(class_id) REFERENCES classes(id),
        FOREIGN KEY(curriculum_item_id) REFERENCES curriculum_items(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS student_grades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        curriculum_item_id INTEGER NOT NULL,
        level INTEGER,
        comment TEXT,
        comment_updated_at TEXT,
        comment_user TEXT,
        FOREIGN KEY(student_id) REFERENCES students(id),
        FOREIGN KEY(curriculum_item_id) REFERENCES curriculum_items(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        start DATETIME NOT NULL,
        end DATETIME,
        color TEXT,
        recurrence TEXT,
        recurrence_group_id TEXT,
        recurrence_end DATE,
        FOREIGN KEY(class_id) REFERENCES classes(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS exams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        status TEXT DEFAULT 'active',
        curriculum_group_id INTEGER,
        is_final INTEGER DEFAULT 0,
        weight REAL DEFAULT 1.0,
        dawra INTEGER DEFAULT 1,
        is_year_final INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(class_id) REFERENCES classes(id),
        FOREIGN KEY(curriculum_group_id) REFERENCES curriculum_groups(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS grades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        exam_id INTEGER NOT NULL,
        grade TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(student_id) REFERENCES students(id),
        FOREIGN KEY(exam_id) REFERENCES exams(id),
        UNIQUE(student_id, exam_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        present INTEGER DEFAULT 1,
        FOREIGN KEY(student_id) REFERENCES students(id),
        FOREIGN KEY(class_id) REFERENCES classes(id),
        UNIQUE(student_id, class_id, day)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS homework (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER NOT NULL,
        due_date TEXT,
        description TEXT,
        files TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(class_id) REFERENCES classes(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        expiry TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS support_material (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        level_id INTEGER NOT NULL,
        filename TEXT,
        original_filename TEXT,
        description TEXT,
        uploader TEXT,
        date TEXT,
        FOREIGN KEY(level_id) REFERENCES levels(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS super_badges (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        icon_type TEXT,
        icon_value TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        active INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS student_super_badges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        super_badge_id TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(student_id) REFERENCES students(id),
        FOREIGN KEY(super_badge_id) REFERENCES super_badges(id),
        UNIQUE(student_id, super_badge_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS student_super_badges_notes (
        student_id INTEGER PRIMARY KEY,
        note TEXT,
        updated_at TEXT,
        user TEXT,
        FOREIGN KEY(student_id) REFERENCES students(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS backup_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        backup_date TEXT NOT NULL,
        backup_by TEXT
    )''')

    conn.commit()
    conn.close()

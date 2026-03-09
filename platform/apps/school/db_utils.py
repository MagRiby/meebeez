"""Tenant-aware database utilities for the School app (PostgreSQL / Neon)."""

from flask import g
from core.tenants.db_manager import get_tenant_connection


def get_school_db(tenant_slug):
    """Get a PostgreSQL connection for the given tenant.

    Returns a psycopg connection with dict_row and search_path
    set to the tenant's schema.  Cached per-request via db_manager.
    """
    return get_tenant_connection(tenant_slug)


def close_school_db(tenant_slug):
    """Close the cached connection for a tenant."""
    from core.tenants.db_manager import close_tenant_connection
    close_tenant_connection(tenant_slug)


def init_school_db(tenant_slug):
    """Initialize the school database schema for a tenant using raw SQL."""
    from core.tenants.db_manager import create_tenant_schema
    create_tenant_schema(tenant_slug)

    conn = get_tenant_connection(tenant_slug)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT,
        role TEXT NOT NULL CHECK(role IN ('super_admin', 'local_admin', 'teacher', 'student')),
        created_by INTEGER,
        is_director INTEGER DEFAULT 0,
        FOREIGN KEY(created_by) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS teachers (
        id SERIAL PRIMARY KEY,
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
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        local_admin_id INTEGER NOT NULL,
        FOREIGN KEY(local_admin_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS classes (
        id SERIAL PRIMARY KEY,
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
        id SERIAL PRIMARY KEY,
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
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        local_admin_id INTEGER NOT NULL,
        level_id INTEGER NOT NULL,
        FOREIGN KEY(local_admin_id) REFERENCES users(id),
        FOREIGN KEY(level_id) REFERENCES levels(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS curriculum_items (
        id SERIAL PRIMARY KEY,
        group_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        FOREIGN KEY(group_id) REFERENCES curriculum_groups(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS class_courses (
        id SERIAL PRIMARY KEY,
        class_id INTEGER NOT NULL,
        curriculum_item_id INTEGER NOT NULL,
        FOREIGN KEY(class_id) REFERENCES classes(id),
        FOREIGN KEY(curriculum_item_id) REFERENCES curriculum_items(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS student_grades (
        id SERIAL PRIMARY KEY,
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
        id SERIAL PRIMARY KEY,
        class_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        start TIMESTAMP NOT NULL,
        "end" TIMESTAMP,
        color TEXT,
        recurrence TEXT,
        recurrence_group_id TEXT,
        recurrence_end DATE,
        FOREIGN KEY(class_id) REFERENCES classes(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS exams (
        id SERIAL PRIMARY KEY,
        class_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        status TEXT DEFAULT 'active',
        curriculum_group_id INTEGER,
        is_final INTEGER DEFAULT 0,
        weight REAL DEFAULT 1.0,
        dawra INTEGER DEFAULT 1,
        is_year_final INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW(),
        FOREIGN KEY(class_id) REFERENCES classes(id),
        FOREIGN KEY(curriculum_group_id) REFERENCES curriculum_groups(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS grades (
        id SERIAL PRIMARY KEY,
        student_id INTEGER NOT NULL,
        exam_id INTEGER NOT NULL,
        grade TEXT,
        updated_at TIMESTAMP DEFAULT NOW(),
        FOREIGN KEY(student_id) REFERENCES students(id),
        FOREIGN KEY(exam_id) REFERENCES exams(id),
        UNIQUE(student_id, exam_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
        id SERIAL PRIMARY KEY,
        student_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        present INTEGER DEFAULT 1,
        FOREIGN KEY(student_id) REFERENCES students(id),
        FOREIGN KEY(class_id) REFERENCES classes(id),
        UNIQUE(student_id, class_id, day)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS homework (
        id SERIAL PRIMARY KEY,
        class_id INTEGER NOT NULL,
        due_date TEXT,
        description TEXT,
        files TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        FOREIGN KEY(class_id) REFERENCES classes(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS announcements (
        id SERIAL PRIMARY KEY,
        class_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        expiry TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS support_material (
        id SERIAL PRIMARY KEY,
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
        created_at TIMESTAMP DEFAULT NOW(),
        active INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS student_super_badges (
        id SERIAL PRIMARY KEY,
        student_id INTEGER NOT NULL,
        super_badge_id TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT NOW(),
        FOREIGN KEY(student_id) REFERENCES students(id),
        FOREIGN KEY(super_badge_id) REFERENCES super_badges(id),
        UNIQUE(student_id, super_badge_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS student_super_badges_notes (
        student_id INTEGER PRIMARY KEY,
        note TEXT,
        updated_at TEXT,
        "user" TEXT,
        FOREIGN KEY(student_id) REFERENCES students(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS backup_log (
        id SERIAL PRIMARY KEY,
        backup_date TEXT NOT NULL,
        backup_by TEXT
    )''')

    conn.commit()

"""Tenant-level models for the School app.

These models are created in each tenant's own database,
not in the platform database. The schema mirrors the
existing arabicschool application.
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
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


class TenantBase(DeclarativeBase):
    pass


class User(TenantBase):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(Text, nullable=True)
    role = Column(String(50), nullable=False)  # super_admin|local_admin|teacher|student
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_director = Column(Integer, default=0)


class Teacher(TenantBase):
    __tablename__ = "teachers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    local_admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(Text, nullable=True)
    email = Column(Text, nullable=True)
    phone = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    alerts = Column(Text, nullable=True)


class Level(TenantBase):
    __tablename__ = "levels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    local_admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)


class Class(TenantBase):
    __tablename__ = "classes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=True)
    local_admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    level_id = Column(Integer, ForeignKey("levels.id"), nullable=True)
    backup_teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=True)
    dawra1_pub_start = Column(Text, nullable=True)
    dawra1_pub_end = Column(Text, nullable=True)
    dawra2_pub_start = Column(Text, nullable=True)
    dawra2_pub_end = Column(Text, nullable=True)
    dawra3_pub_start = Column(Text, nullable=True)
    dawra3_pub_end = Column(Text, nullable=True)
    year_pub_start = Column(Text, nullable=True)
    year_pub_end = Column(Text, nullable=True)


class Student(TenantBase):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=True)
    email = Column(Text, nullable=True)
    phone = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    alerts = Column(Text, nullable=True)
    date_of_birth = Column(Text, nullable=True)
    secondary_email = Column(Text, nullable=True)
    sex = Column(Text, nullable=True)


class CurriculumGroup(TenantBase):
    __tablename__ = "curriculum_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    local_admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    level_id = Column(Integer, ForeignKey("levels.id"), nullable=False)


class CurriculumItem(TenantBase):
    __tablename__ = "curriculum_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("curriculum_groups.id"), nullable=False)
    name = Column(Text, nullable=False)


class ClassCourse(TenantBase):
    __tablename__ = "class_courses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    curriculum_item_id = Column(Integer, ForeignKey("curriculum_items.id"), nullable=False)


class StudentGrade(TenantBase):
    __tablename__ = "student_grades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    curriculum_item_id = Column(Integer, ForeignKey("curriculum_items.id"), nullable=False)
    level = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)
    comment_updated_at = Column(Text, nullable=True)
    comment_user = Column(Text, nullable=True)


class Event(TenantBase):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    start = Column(Text, nullable=False)
    end = Column(Text, nullable=True)
    color = Column(Text, nullable=True)
    recurrence = Column(Text, nullable=True)
    recurrence_group_id = Column(Text, nullable=True)
    recurrence_end = Column(Text, nullable=True)


class Exam(TenantBase):
    __tablename__ = "exams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    name = Column(Text, nullable=False)
    status = Column(Text, default="active")  # active|inactive
    curriculum_group_id = Column(Integer, ForeignKey("curriculum_groups.id"), nullable=True)
    is_final = Column(Integer, default=0)
    weight = Column(Float, default=1.0)
    dawra = Column(Integer, default=1)  # 1, 2, 3, or NULL
    is_year_final = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Grade(TenantBase):
    __tablename__ = "grades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=False)
    grade = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("student_id", "exam_id", name="uq_student_exam"),
    )


class Attendance(TenantBase):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    day = Column(Text, nullable=False)  # YYYY-MM-DD
    present = Column(Integer, default=1)  # 0=absent, 1=present

    __table_args__ = (
        UniqueConstraint("student_id", "class_id", "day", name="uq_attendance"),
    )


class Homework(TenantBase):
    __tablename__ = "homework"

    id = Column(Integer, primary_key=True, autoincrement=True)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    due_date = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    files = Column(Text, nullable=True)  # JSON list of filenames
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Announcement(TenantBase):
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    expiry = Column(Text, nullable=True)


class SupportMaterial(TenantBase):
    __tablename__ = "support_material"

    id = Column(Integer, primary_key=True, autoincrement=True)
    level_id = Column(Integer, ForeignKey("levels.id"), nullable=False)
    filename = Column(Text, nullable=True)
    original_filename = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    uploader = Column(Text, nullable=True)
    date = Column(Text, nullable=True)


class SuperBadge(TenantBase):
    __tablename__ = "super_badges"

    id = Column(String(36), primary_key=True)
    name = Column(String(128), nullable=False)
    icon_type = Column(String(20), nullable=True)
    icon_value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    active = Column(Integer, default=1)


class StudentSuperBadge(TenantBase):
    __tablename__ = "student_super_badges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    super_badge_id = Column(String(36), ForeignKey("super_badges.id"), nullable=False)
    active = Column(Integer, default=1)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("student_id", "super_badge_id", name="uq_student_badge"),
    )


class StudentSuperBadgeNotes(TenantBase):
    __tablename__ = "student_super_badges_notes"

    student_id = Column(Integer, ForeignKey("students.id"), primary_key=True)
    note = Column(Text, nullable=True)
    updated_at = Column(Text, nullable=True)
    user = Column(Text, nullable=True)


class BackupLog(TenantBase):
    __tablename__ = "backup_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    backup_date = Column(Text, nullable=False)
    backup_by = Column(Text, nullable=True)

"""Tenant-level models for the School app.

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


class Level(TenantBase):
    __tablename__ = "levels"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, default="")
    order = Column(Integer, default=0)

    classes = relationship("Class", backref="level")


class Class(TenantBase):
    __tablename__ = "classes"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    level_id = Column(Integer, ForeignKey("levels.id"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=True)
    schedule = Column(String(255), default="")
    max_students = Column(Integer, default=30)

    students = relationship("Student", backref="student_class")
    curriculum_groups = relationship("CurriculumGroup", backref="class_ref")


class Teacher(TenantBase):
    __tablename__ = "teachers"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    specialization = Column(String(255), default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    classes = relationship("Class", backref="teacher")


class Student(TenantBase):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    parent_name = Column(String(255), default="")
    parent_phone = Column(String(50), default="")
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    enrolled_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    attendance_records = relationship("Attendance", backref="student")
    grades = relationship("Grade", backref="student")


class CurriculumGroup(TenantBase):
    __tablename__ = "curriculum_groups"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    order = Column(Integer, default=0)

    items = relationship("CurriculumItem", backref="group")


class CurriculumItem(TenantBase):
    __tablename__ = "curriculum_items"

    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    group_id = Column(Integer, ForeignKey("curriculum_groups.id"), nullable=False)
    order = Column(Integer, default=0)
    is_completed = Column(Boolean, default=False)


class Attendance(TenantBase):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="present")  # present|absent|late
    notes = Column(Text, default="")


class Homework(TenantBase):
    __tablename__ = "homework"

    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    due_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Event(TenantBase):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    event_date = Column(Date, nullable=False)
    event_time = Column(Time, nullable=True)
    location = Column(String(255), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Exam(TenantBase):
    __tablename__ = "exams"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    exam_date = Column(Date, nullable=True)
    max_score = Column(Float, default=100.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    grades = relationship("Grade", backref="exam")


class Grade(TenantBase):
    __tablename__ = "grades"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=False)
    score = Column(Float, nullable=False)
    notes = Column(Text, default="")
    graded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

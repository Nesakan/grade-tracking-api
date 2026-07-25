#models.py
from sqlalchemy import Column, Integer, String, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base

class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)

    enrollments = relationship(
        "Enrollment", back_populates="student", cascade="all, delete-orphan"
    )

class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    credits = Column(Integer, nullable=False)

    enrollments = relationship("Enrollment", back_populates="course")

class Enrollment(Base):
    __tablename__ = "enrollments"
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)

    grade = Column(Float, nullable=True)

    student = relationship("Student", back_populates="enrollments")
    course = relationship("Course", back_populates="enrollments")

    __table_args__ = (
        UniqueConstraint("student_id", "course_id", name="uq_student_course"),
        )
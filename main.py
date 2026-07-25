from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from schemas import StudentCreate, StudentOut, CourseCreate, CourseOut, EnrollmentCreate, EnrollmentOut, EnrollmentUpdate
from database import get_db, Base, engine
from models import Student, Course, Enrollment
Base.metadata.create_all(bind=engine)

app = FastAPI()

@app.post("/students", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
def create_student(student_in: StudentCreate, db: Session = Depends(get_db)):
    student = Student(name=student_in.name, email=student_in.email)
    db.add(student)
    db.commit()
    db.refresh(student)
    return student

@app.post("/courses", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
def create_course(course_in: CourseCreate, db: Session = Depends(get_db)):
    course = Course(code=course_in.code, title=course_in.title, credits=course_in.credits)
    db.add(course)
    db.commit()
    db.refresh(course)
    return course

@app.post("/enrollments", response_model=EnrollmentOut, status_code=status.HTTP_201_CREATED)
def create_enrollment(enrollment_in: EnrollmentCreate, db: Session = Depends(get_db)):
    course = db.query(Course).filter(Course.id == enrollment_in.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    student = db.query(Student).filter(Student.id == enrollment_in.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    enrollment = Enrollment(student_id=enrollment_in.student_id, course_id=enrollment_in.course_id)
    db.add(enrollment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Student already enrolled in this course")
    db.refresh(enrollment)
    return enrollment

@app.patch("/enrollments/{enrollment_id}", response_model=EnrollmentOut)
def update_grade(enrollment_id: int, grade_in: EnrollmentUpdate, db: Session = Depends(get_db)):
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    enrollment.grade = grade_in.grade
    db.commit()
    db.refresh(enrollment)
    return enrollment

@app.get("/students/{student_id}/transcript")
def get_transcript(student_id: int, db: Session = Depends(get_db)):
    result = (
        db.query(func.sum(Enrollment.grade * Course.credits)/func.sum(Course.credits))
        .select_from(Enrollment)
        .join(Course, Enrollment.course_id == Course.id)
        .filter(Enrollment.student_id == student_id)
        .scalar()
    )
    if result is None:
        raise HTTPException(status_code=404, detail="No grades found for this student")
    return {"student_id": student_id, "gpa": result}

@app.get("/students", response_model=list[StudentOut])
def get_students(db: Session = Depends(get_db)):
    students = db.query(Student).all()
    return students

@app.get("/students/{student_id}", response_model=StudentOut)
def get_student(student_id: int, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail='Student not found')
    return student

@app.get("/students/{student_id}/enrollments")
def get_student_enrollments(student_id: int, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail='Student not found')

    result = []
    for enrollment in student.enrollments:
        result.append({
            "course_id":enrollment.course.id,
            "course_code":enrollment.course.code,
            "course_title":enrollment.course.title,
            "credits":enrollment.course.credits,
            "grade":enrollment.grade
        })
    return result

@app.get("/courses", response_model=list[CourseOut])
def get_courses(db: Session = Depends(get_db)):
    courses = db.query(Course).all()
    return courses

@app.delete("/students/{student_id}")
def delete_student(student_id: int, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail='Student not found')
    db.delete(student)
    db.commit()
    return {"message": "Student deleted successfully"}
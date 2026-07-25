from pydantic import BaseModel, EmailStr, field_validator

class StudentCreate(BaseModel):
    name: str
    email: EmailStr

class StudentOut(BaseModel):
    id: int
    name: str
    email: str

    class Config:
        from_attributes = True

class CourseCreate(BaseModel):
    code: str
    title: str
    credits: int


class CourseOut(BaseModel):
    id: int
    code: str
    title: str
    credits: int

    class Config:
        from_attributes = True

class EnrollmentCreate(BaseModel):
    student_id: int
    course_id: int

class EnrollmentOut(BaseModel):
    id: int
    student_id: int
    course_id: int
    grade: float | None

    class Config:
        from_attributes = True
        
class EnrollmentUpdate(BaseModel):
    grade: float

    @field_validator("grade")
    @classmethod
    def grade_in_range(cls, v):
        if not (0.0 <= v <= 10.0):
            raise ValueError("grade must be between 0.0 and 10.0")
        return v
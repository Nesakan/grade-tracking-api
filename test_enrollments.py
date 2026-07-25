def test_create_enrollment_invalid_course_returns_404(client):
    rep = client.post("/students", json={"name": "Hari", "email": "devhari@example.com"})
    data = rep.json()
    response = client.post("/enrollments", json={"student_id": data["id"], "course_id": 999})
    assert response.status_code == 404
    assert response.json() == {"detail": "Course not found"}

def test_duplicate_enrollment_409(client):
    s_data = client.post("/students", json={"name": "Hariharan", "email": "devhari@gmail.com"}).json()
    c_data = client.post("/courses", json={"code": "CS101", "title": "Intro to CS", "credits": 3}).json()
    r = client.post("/enrollments", json={"student_id":s_data["id"], "course_id":c_data["id"]})
    assert r.status_code == 201
    response = client.post("/enrollments", json={"student_id":s_data["id"], "course_id":c_data["id"]})
    assert response.status_code == 409
    assert response.json() == {"detail": "Student already enrolled in this course"}


def test_invalid_student_404(client):
    c_data = client.post("/courses", json={"code": "CS101", "title": "Intro to CS", "credits": 3}).json()
    response = client.post("/enrollments", json={"student_id": 999, "course_id": c_data["id"]})
    assert response.status_code == 404
    assert response.json() == {"detail": "Student not found"}


def test_empty_list_200(client):
    s_data = client.post("/students", json={"name": "Hariharan", "email": "devhari@gmail.com"}).json()

    response = client.get(f"/students/{s_data['id']}/enrollments")
    data = response.json()
    assert response.status_code == 200
    assert data == []
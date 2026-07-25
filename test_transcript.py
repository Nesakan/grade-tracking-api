import pytest

def test_gpa_correctness(client):
    s_data = client.post("/students", json={"name": "Hariharan", "email": "devhari@gmail.com"}).json()
    c1_data = client.post("/courses", json={"code": "CS101", "title": "Intro to CS", "credits": 3}).json()
    c2_data = client.post("/courses", json={"code": "CS102", "title": "Data Structures", "credits": 4}).json()
    e1_data = client.post("/enrollments", json={"student_id": s_data["id"], "course_id": c1_data["id"]}).json()
    e2_data = client.post("/enrollments", json={"student_id": s_data["id"], "course_id": c2_data["id"]}).json()

    p1 = client.patch(f"/enrollments/{e1_data['id']}", json={"grade": 8.0})
    p2 = client.patch(f"/enrollments/{e2_data['id']}", json={"grade": 9.0})
    assert p1.status_code == 200
    assert p2.status_code == 200

    response = client.get(f"/students/{s_data['id']}/transcript")
    data = response.json()
    assert data["gpa"] == pytest.approx(60/7)
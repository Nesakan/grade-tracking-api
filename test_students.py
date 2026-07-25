
def test_create_student(client):
    response = client.post("/students", json={"name": "John Doe", "email": "john.doe@example.com"})
    data = response.json()
    assert response.status_code == 201
    assert data["name"] == "John Doe"
    assert data["email"] == "john.doe@example.com"
    assert "id" in data
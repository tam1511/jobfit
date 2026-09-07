from fastapi.testclient import TestClient


def test_login_creates_user(client: TestClient) -> None:
    response = client.post("/api/session", json={"name": "Mai"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Mai"
    assert isinstance(body["user_id"], int)
    assert body["user_id"] >= 1


def test_login_rejects_blank_name(client: TestClient) -> None:
    response = client.post("/api/session", json={"name": "   "})
    assert response.status_code == 422


def test_login_rejects_missing_name(client: TestClient) -> None:
    response = client.post("/api/session", json={})
    assert response.status_code == 422


def test_two_logins_get_distinct_ids(client: TestClient) -> None:
    first = client.post("/api/session", json={"name": "Mai"}).json()
    second = client.post("/api/session", json={"name": "Duc"}).json()
    assert first["user_id"] != second["user_id"]

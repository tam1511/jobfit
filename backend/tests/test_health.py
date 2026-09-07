from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_without_frontend_returns_message(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Backend is running" in response.json()["message"]

from fastapi.testclient import TestClient

from tests.conftest import DEFAULT_CREDENTIALS, register


def test_register_creates_user_and_sets_cookie(client: TestClient) -> None:
    response = client.post("/api/auth/register", json=DEFAULT_CREDENTIALS)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "mai@example.com"
    assert body["name"] == "Mai"
    assert isinstance(body["user_id"], int)
    assert "jobfit_session" in response.cookies


def test_register_rejects_short_password(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={"email": "a@b.com", "password": "short", "name": "Mai"},
    )
    assert response.status_code == 422


def test_register_rejects_invalid_email(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={"email": "not-an-email", "password": "longenough", "name": "Mai"},
    )
    assert response.status_code == 422


def test_register_rejects_duplicate_email(client: TestClient) -> None:
    register(client)
    response = client.post("/api/auth/register", json=DEFAULT_CREDENTIALS)
    assert response.status_code == 409


def test_login_returns_cookie_on_correct_password(client: TestClient) -> None:
    register(client)
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": DEFAULT_CREDENTIALS["email"], "password": DEFAULT_CREDENTIALS["password"]},
    )
    assert response.status_code == 200
    assert "jobfit_session" in response.cookies


def test_login_rejects_wrong_password(client: TestClient) -> None:
    register(client)
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": DEFAULT_CREDENTIALS["email"], "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_login_rejects_unknown_email(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "whatever-longenough"},
    )
    assert response.status_code == 401


def test_login_wrong_and_missing_email_take_similar_time(client: TestClient) -> None:
    """Both paths must exercise bcrypt so a user's existence cannot be timed."""
    import time

    register(client)
    client.cookies.clear()

    def measure(email: str) -> float:
        start = time.perf_counter()
        client.post("/api/auth/login", json={"email": email, "password": "wrongpassword1"})
        return time.perf_counter() - start

    wrong_pw_time = measure(DEFAULT_CREDENTIALS["email"])
    no_user_time = measure("nobody@example.com")
    ratio = max(wrong_pw_time, no_user_time) / max(min(wrong_pw_time, no_user_time), 1e-6)
    assert ratio < 5.0, f"Login timing diverges too much: {wrong_pw_time:.4f}s vs {no_user_time:.4f}s"


def test_login_is_case_insensitive_on_email(client: TestClient) -> None:
    register(client)
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": DEFAULT_CREDENTIALS["email"].upper(), "password": DEFAULT_CREDENTIALS["password"]},
    )
    assert response.status_code == 200


def test_me_returns_current_user(authed_client: TestClient) -> None:
    response = authed_client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == DEFAULT_CREDENTIALS["email"]


def test_me_without_cookie_is_401(client: TestClient) -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_logout_clears_session(authed_client: TestClient) -> None:
    response = authed_client.post("/api/auth/logout")
    assert response.status_code == 200
    authed_client.cookies.clear()
    assert authed_client.get("/api/auth/me").status_code == 401

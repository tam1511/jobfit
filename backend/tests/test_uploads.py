from fastapi.testclient import TestClient

from tests.conftest import register


def _upload(client: TestClient, pdf: bytes, *, company: str = "Acme", role: str = "Marketing Manager", jd: str = "Digital Marketing Manager"):
    return client.post(
        "/api/uploads",
        data={"company": company, "role_title": role, "jd_text": jd},
        files={"cv": ("cv.pdf", pdf, "application/pdf")},
    )


def test_upload_requires_authentication(client: TestClient, marketing_pdf_bytes: bytes) -> None:
    response = _upload(client, marketing_pdf_bytes)
    assert response.status_code == 401


def test_upload_returns_extracted_text_and_score(
    authed_client: TestClient, marketing_pdf_bytes: bytes
) -> None:
    response = _upload(authed_client, marketing_pdf_bytes)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["filename"] == "cv.pdf"
    assert body["company"] == "Acme"
    assert body["role_title"] == "Marketing Manager"
    assert "Mai Nguyen" in body["extracted_text"]
    score = body["score"]
    assert 0 <= score["overall_score"] <= 100
    assert len(score["breakdown"]) == 5


def test_upload_rejects_non_pdf(authed_client: TestClient) -> None:
    response = authed_client.post(
        "/api/uploads",
        data={"company": "Acme", "role_title": "Manager", "jd_text": "role"},
        files={"cv": ("cv.txt", b"not a pdf", "text/plain")},
    )
    assert response.status_code == 415


def test_upload_rejects_blank_jd(authed_client: TestClient, marketing_pdf_bytes: bytes) -> None:
    response = _upload(authed_client, marketing_pdf_bytes, jd="   ")
    assert response.status_code == 422


def test_upload_rejects_blank_company(authed_client: TestClient, marketing_pdf_bytes: bytes) -> None:
    response = _upload(authed_client, marketing_pdf_bytes, company="   ")
    assert response.status_code == 422


def test_upload_rejects_blank_role(authed_client: TestClient, marketing_pdf_bytes: bytes) -> None:
    response = _upload(authed_client, marketing_pdf_bytes, role="   ")
    assert response.status_code == 422


def test_upload_rejects_unreadable_pdf(authed_client: TestClient) -> None:
    response = authed_client.post(
        "/api/uploads",
        data={"company": "Acme", "role_title": "Manager", "jd_text": "role"},
        files={"cv": ("cv.pdf", b"%PDF-broken", "application/pdf")},
    )
    assert response.status_code == 422


def test_list_uploads_returns_only_current_user(
    client: TestClient, marketing_pdf_bytes: bytes
) -> None:
    register(client)
    _upload(client, marketing_pdf_bytes, company="Acme", role="A")
    _upload(client, marketing_pdf_bytes, company="Beta", role="B")

    client.cookies.clear()
    register(client, email="other@example.com", name="Other")

    response = client.get("/api/uploads")
    assert response.status_code == 200
    assert response.json() == []


def test_list_uploads_filters_by_company_and_role(
    authed_client: TestClient, marketing_pdf_bytes: bytes
) -> None:
    _upload(authed_client, marketing_pdf_bytes, company="Acme", role="Manager")
    _upload(authed_client, marketing_pdf_bytes, company="Acme", role="Manager")
    _upload(authed_client, marketing_pdf_bytes, company="Beta", role="Analyst")

    response = authed_client.get("/api/uploads", params={"company": "Acme", "role_title": "Manager"})
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    for item in items:
        assert item["company"] == "Acme"
        assert item["role_title"] == "Manager"
        assert 0 <= item["overall_score"] <= 100


def test_get_upload_detail_requires_ownership(
    client: TestClient, marketing_pdf_bytes: bytes
) -> None:
    register(client)
    body = _upload(client, marketing_pdf_bytes).json()
    upload_id = body["upload_id"]

    client.cookies.clear()
    register(client, email="other@example.com", name="Other")

    response = client.get(f"/api/uploads/{upload_id}")
    assert response.status_code == 404


def test_get_upload_detail_returns_full_payload(
    authed_client: TestClient, marketing_pdf_bytes: bytes
) -> None:
    body = _upload(authed_client, marketing_pdf_bytes).json()
    upload_id = body["upload_id"]
    response = authed_client.get(f"/api/uploads/{upload_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["upload_id"] == upload_id
    assert payload["company"] == "Acme"
    assert "score" in payload
    assert payload["score"]["overall_score"] == body["score"]["overall_score"]


def test_delete_upload_removes_row(
    authed_client: TestClient, marketing_pdf_bytes: bytes
) -> None:
    upload_id = _upload(authed_client, marketing_pdf_bytes).json()["upload_id"]
    assert authed_client.delete(f"/api/uploads/{upload_id}").status_code == 200
    assert authed_client.get(f"/api/uploads/{upload_id}").status_code == 404


def test_delete_upload_requires_ownership(
    client: TestClient, marketing_pdf_bytes: bytes
) -> None:
    register(client)
    upload_id = _upload(client, marketing_pdf_bytes).json()["upload_id"]

    client.cookies.clear()
    register(client, email="other@example.com", name="Other")

    assert client.delete(f"/api/uploads/{upload_id}").status_code == 404

from fastapi.testclient import TestClient


def _login(client: TestClient, name: str = "Mai") -> int:
    return client.post("/api/session", json={"name": name}).json()["user_id"]


def test_upload_returns_extracted_text_and_score(
    client: TestClient, marketing_pdf_bytes: bytes
) -> None:
    user_id = _login(client)
    response = client.post(
        "/api/uploads",
        data={"user_id": str(user_id), "jd_text": "Digital Marketing Manager"},
        files={"cv": ("cv.pdf", marketing_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "cv.pdf"
    assert "Mai Nguyen" in body["extracted_text"]
    assert body["jd_text"] == "Digital Marketing Manager"
    score = body["score"]
    assert 0 <= score["overall_score"] <= 100
    assert len(score["breakdown"]) == 5
    assert {c["category"] for c in score["breakdown"]} == {
        "Hard Skills Match",
        "Experience Match",
        "ATS Keywords",
        "Quantified Achievements",
        "Formatting & Length",
    }


def test_upload_rejects_non_pdf(client: TestClient) -> None:
    user_id = _login(client)
    response = client.post(
        "/api/uploads",
        data={"user_id": str(user_id), "jd_text": "role"},
        files={"cv": ("cv.txt", b"not a pdf", "text/plain")},
    )
    assert response.status_code == 415


def test_upload_rejects_blank_jd(
    client: TestClient, marketing_pdf_bytes: bytes
) -> None:
    user_id = _login(client)
    response = client.post(
        "/api/uploads",
        data={"user_id": str(user_id), "jd_text": "   "},
        files={"cv": ("cv.pdf", marketing_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 422


def test_upload_rejects_unknown_user(
    client: TestClient, marketing_pdf_bytes: bytes
) -> None:
    response = client.post(
        "/api/uploads",
        data={"user_id": "9999", "jd_text": "role"},
        files={"cv": ("cv.pdf", marketing_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown user."


def test_upload_rejects_unreadable_pdf(client: TestClient) -> None:
    user_id = _login(client)
    response = client.post(
        "/api/uploads",
        data={"user_id": str(user_id), "jd_text": "role"},
        files={"cv": ("cv.pdf", b"%PDF-broken", "application/pdf")},
    )
    assert response.status_code == 422

import os

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_test.db")
os.environ.setdefault("IMAGEKIT_PRIVATE_KEY", "test-key")
os.environ.setdefault("JWT_SECRET", "test-secret")

from app.app import app


def test_health_check():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

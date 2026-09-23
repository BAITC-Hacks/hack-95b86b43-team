from fastapi.testclient import TestClient

from backend import __version__
from backend.main import create_app


def test_health():
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}

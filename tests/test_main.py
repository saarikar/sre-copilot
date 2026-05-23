import sys
sys.path.insert(0, '.')

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_metrics_unauthorized():
    response = client.get("/api/metrics")
    assert response.status_code == 401

def test_login():
    response = client.post("/auth/login", data={
        "username": "admin",
        "password": "password123"
    })
    assert response.status_code == 200
    assert "access_token" in response.json()
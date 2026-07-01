import sys
sys.path.insert(0, '.')

from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from botocore.exceptions import ClientError, NoCredentialsError
import json
from main import app

client = TestClient(app)


def get_token():
    response = client.post("/auth/login", data={"username": "admin", "password": "password123"})
    return response.json()["access_token"]


# --- Auth ---

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_login():
    response = client.post("/auth/login", data={"username": "admin", "password": "password123"})
    assert response.status_code == 200
    assert "access_token" in response.json()

def test_login_wrong_password():
    response = client.post("/auth/login", data={"username": "admin", "password": "wrong"})
    assert response.status_code == 401

def test_login_wrong_user():
    response = client.post("/auth/login", data={"username": "hacker", "password": "password123"})
    assert response.status_code == 401


# --- Metrics ---

def test_metrics_unauthorized():
    response = client.get("/api/metrics")
    assert response.status_code == 401

def test_metrics_authorized():
    token = get_token()
    response = client.get("/api/metrics", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert "cpu_percent" in data
    assert "memory_mb" in data
    assert "memory_total_mb" in data
    assert "memory_percent" in data
    assert "host" in data


# --- Log Analysis ---

def test_analyze_unauthorized():
    response = client.post("/api/analyze", json={"logs": "ERROR: crash", "pod_name": "test"})
    assert response.status_code == 401

def test_analyze():
    mock_result = {
        "root_cause": "Database connection refused after max retries",
        "immediate_fix": "kubectl rollout restart deployment/auth-service",
        "prevention": "Add connection pooling and retry backoff",
        "severity": "critical"
    }
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(mock_result)

    with patch("main.client.chat.completions.create", return_value=mock_response):
        token = get_token()
        response = client.post(
            "/api/analyze",
            json={"logs": "ERROR: connection refused to postgres:5432", "pod_name": "auth-service"},
            headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["root_cause"] == "Database connection refused after max retries"
    assert data["severity"] == "critical"
    assert "immediate_fix" in data
    assert "prevention" in data


# --- CloudWatch ---

def test_cloudwatch_groups_unauthorized():
    response = client.get("/api/cloudwatch/groups")
    assert response.status_code == 401

def test_cloudwatch_logs_unauthorized():
    response = client.post("/api/cloudwatch/logs", json={"log_group": "test", "minutes": 30})
    assert response.status_code == 401

def test_cloudwatch_analyze_unauthorized():
    response = client.post("/api/cloudwatch/analyze", json={"log_group": "test", "minutes": 30})
    assert response.status_code == 401

def test_cloudwatch_groups():
    mock_cw = MagicMock()
    mock_cw.describe_log_groups.return_value = {
        "logGroups": [
            {"logGroupName": "/aws/lambda/my-function"},
            {"logGroupName": "sre-copilot-demo"},
        ]
    }

    with patch("main.boto3.client", return_value=mock_cw):
        token = get_token()
        response = client.get("/api/cloudwatch/groups", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    data = response.json()
    assert "/aws/lambda/my-function" in data["log_groups"]
    assert "sre-copilot-demo" in data["log_groups"]

def test_cloudwatch_logs():
    mock_cw = MagicMock()
    mock_cw.filter_log_events.return_value = {
        "events": [
            {"message": "ERROR: connection refused"},
            {"message": "WARN: retrying connection"},
        ]
    }

    with patch("main.boto3.client", return_value=mock_cw):
        token = get_token()
        response = client.post(
            "/api/cloudwatch/logs",
            json={"log_group": "sre-copilot-demo", "minutes": 30},
            headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert "ERROR: connection refused" in data["events"]

def test_cloudwatch_logs_empty():
    mock_cw = MagicMock()
    mock_cw.filter_log_events.return_value = {"events": []}

    with patch("main.boto3.client", return_value=mock_cw):
        token = get_token()
        response = client.post(
            "/api/cloudwatch/logs",
            json={"log_group": "sre-copilot-demo", "minutes": 30},
            headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200
    assert response.json()["events"] == []

def test_cloudwatch_logs_not_found():
    class FakeResourceNotFound(Exception):
        pass

    mock_cw = MagicMock()
    mock_cw.exceptions.ResourceNotFoundException = FakeResourceNotFound
    mock_cw.filter_log_events.side_effect = FakeResourceNotFound()

    with patch("main.boto3.client", return_value=mock_cw):
        token = get_token()
        response = client.post(
            "/api/cloudwatch/logs",
            json={"log_group": "nonexistent", "minutes": 30},
            headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 404

def test_cloudwatch_logs_aws_error():
    mock_cw = MagicMock()
    mock_cw.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
    mock_cw.filter_log_events.side_effect = NoCredentialsError()

    with patch("main.boto3.client", return_value=mock_cw):
        token = get_token()
        response = client.post(
            "/api/cloudwatch/logs",
            json={"log_group": "sre-copilot-demo", "minutes": 30},
            headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 502

def test_cloudwatch_analyze():
    mock_cw = MagicMock()
    mock_cw.filter_log_events.return_value = {
        "events": [
            {"message": "ERROR: OOMKilled - exit code 137"},
            {"message": "ERROR: java.lang.OutOfMemoryError"},
        ]
    }

    mock_result = {
        "root_cause": "Pod ran out of memory and was OOMKilled",
        "immediate_fix": "kubectl set resources deployment/auth-service --limits=memory=1Gi",
        "prevention": "Set proper memory limits and configure alerts",
        "severity": "critical"
    }
    mock_groq = MagicMock()
    mock_groq.choices[0].message.content = json.dumps(mock_result)

    with patch("main.boto3.client", return_value=mock_cw), \
         patch("main.client.chat.completions.create", return_value=mock_groq):
        token = get_token()
        response = client.post(
            "/api/cloudwatch/analyze",
            json={"log_group": "sre-copilot-demo", "minutes": 30, "pod_name": "auth-service"},
            headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["log_group"] == "sre-copilot-demo"
    assert data["events_analyzed"] == 2
    assert data["severity"] == "critical"
    assert "root_cause" in data
    assert "immediate_fix" in data
    assert "prevention" in data

def test_cloudwatch_analyze_no_events():
    mock_cw = MagicMock()
    mock_cw.filter_log_events.return_value = {"events": []}

    with patch("main.boto3.client", return_value=mock_cw):
        token = get_token()
        response = client.post(
            "/api/cloudwatch/analyze",
            json={"log_group": "sre-copilot-demo", "minutes": 30},
            headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 404

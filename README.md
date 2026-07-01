# SRE Copilot

An AI-powered backend tool for Site Reliability Engineers. Pulls logs directly from AWS CloudWatch and uses a large language model to diagnose incidents — returning the root cause, an immediate fix, and a prevention recommendation in seconds.

## Features

- **AI Log Analysis** — sends logs to Groq (LLaMA 3.3 70B) and returns a structured diagnosis
- **AWS CloudWatch Integration** — fetch logs from any log group/stream without leaving the tool
- **JWT Authentication** — all endpoints are protected with bearer token auth
- **Live System Metrics** — real CPU, memory, and hostname via psutil
- **Prometheus Metrics** — auto-instrumented via `/metrics-public` for Grafana scraping
- **Dockerized** — runs anywhere with a single command
- **CI/CD** — GitHub Actions runs 18 unit tests and builds the Docker image on every push

## Architecture

```
AWS CloudWatch Log Groups
          │
          │  boto3 (filter_log_events)
          ▼
┌─────────────────────────┐
│     SRE Copilot API     │
│        (FastAPI)        │
│                         │
│  /api/cloudwatch/logs   │──► raw log events
│  /api/cloudwatch/analyze│──► Groq AI ──► diagnosis JSON
│  /api/analyze           │──► Groq AI ──► diagnosis JSON
│  /api/metrics           │──► live CPU / memory
│  /metrics-public        │──► Prometheus scrape endpoint
└─────────────────────────┘
          │
          │  Prometheus
          ▼
       Grafana
```

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI, Python 3.11 |
| AI | Groq API (LLaMA 3.3 70B) |
| Cloud | AWS CloudWatch (boto3) |
| Auth | JWT (python-jose), bcrypt |
| Metrics | Prometheus, psutil |
| Containerization | Docker |
| CI/CD | GitHub Actions |

## API Endpoints

### Auth
```
POST /auth/login
```
```json
{ "username": "admin", "password": "yourpassword" }
```
Returns a JWT bearer token used for all other requests.

---

### Log Analysis (manual)
```
POST /api/analyze
Authorization: Bearer <token>
```
```json
{
  "logs": "ERROR: connection refused to postgres:5432\nWARN: retrying...",
  "pod_name": "auth-service"
}
```
```json
{
  "root_cause": "Database connection pool exhausted due to unclosed connections",
  "immediate_fix": "kubectl rollout restart deployment/auth-service",
  "prevention": "Implement connection pooling with max_overflow limits",
  "severity": "critical"
}
```

---

### CloudWatch — List Log Groups
```
GET /api/cloudwatch/groups
Authorization: Bearer <token>
```
```json
{ "log_groups": ["/aws/lambda/my-function", "sre-copilot-demo"] }
```

---

### CloudWatch — Fetch Logs
```
POST /api/cloudwatch/logs
Authorization: Bearer <token>
```
```json
{
  "log_group": "sre-copilot-demo",
  "log_stream": "auth-service",
  "minutes": 30
}
```
```json
{
  "log_group": "sre-copilot-demo",
  "events": ["ERROR: OOMKilled - exit code 137", "..."],
  "count": 10
}
```

---

### CloudWatch — Fetch + Analyze
```
POST /api/cloudwatch/analyze
Authorization: Bearer <token>
```
```json
{
  "log_group": "sre-copilot-demo",
  "log_stream": "auth-service",
  "minutes": 30,
  "pod_name": "auth-service"
}
```
```json
{
  "log_group": "sre-copilot-demo",
  "events_analyzed": 10,
  "root_cause": "Pod exceeded memory limit and was OOMKilled by the OS",
  "immediate_fix": "kubectl set resources deployment/auth-service --limits=memory=1Gi",
  "prevention": "Set memory requests/limits and configure alerting on memory usage above 80%",
  "severity": "critical"
}
```

---

### System Metrics
```
GET /api/metrics
Authorization: Bearer <token>
```
```json
{
  "cpu_percent": 26.7,
  "memory_mb": 6757,
  "memory_total_mb": 7979,
  "memory_percent": 84.7,
  "host": "sre-copilot-host"
}
```

## Running Locally

**1. Clone the repo**
```bash
git clone https://github.com/your-username/sre-copilot.git
cd sre-copilot
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Set environment variables**

Create a `.env` file:
```env
GROQ_API_KEY=your-groq-api-key
SECRET_KEY=your-jwt-secret
ADMIN_PASSWORD=your-password
METRICS_TOKEN=your-metrics-token
AWS_ACCESS_KEY_ID=your-aws-key-id
AWS_SECRET_ACCESS_KEY=your-aws-secret
AWS_REGION=us-east-1
```

**4. Run the app**
```bash
uvicorn main:app --reload
```

Visit `http://localhost:8000/docs` for the interactive API docs.

**5. Run with Docker**
```bash
docker build -t sre-copilot .
docker run -p 8000:8000 --env-file .env sre-copilot
```

## Running Tests

```bash
pytest tests/test_unit.py -v
```

All 18 unit tests use mocked AWS and Groq clients — no credentials required to run the test suite.

## AWS Setup

The CloudWatch endpoints require an IAM user with `CloudWatchLogsReadOnlyAccess` attached:

1. AWS Console → IAM → Users → Create user
2. Attach policy: `CloudWatchLogsReadOnlyAccess`
3. Create access key → paste into `.env`

## Environment Variables

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | Groq API key for LLM access |
| `SECRET_KEY` | Secret used to sign JWT tokens |
| `ADMIN_PASSWORD` | Password for the admin user |
| `METRICS_TOKEN` | Bearer token for Prometheus scrape endpoint |
| `AWS_ACCESS_KEY_ID` | AWS IAM access key |
| `AWS_SECRET_ACCESS_KEY` | AWS IAM secret key |
| `AWS_REGION` | AWS region where your log groups live |

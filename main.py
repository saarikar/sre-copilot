from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.security.api_key import APIKeyHeader
from fastapi import Security
from pydantic import BaseModel
from dotenv import load_dotenv
from groq import Groq
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
import os
import json
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import psutil
import socket
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

load_dotenv()

# --- Config ---
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false"

# --- Setup ---
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
app = FastAPI(title="SRE Copilot")
from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app, include_in_schema=False)

# --- Rate limiting (per client IP) ---
limiter = Limiter(key_func=get_remote_address, enabled=RATE_LIMIT_ENABLED)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

@app.get("/metrics-public")
def metrics_public(authorization: str = Security(api_key_header)):
    token = os.getenv("METRICS_TOKEN")
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Unauthorized")
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
# --- Fake user database ---
USERS_DB = {
    "admin": {
        "username": "admin",
        "password": pwd_context.hash(os.getenv("ADMIN_PASSWORD")),
    }
}

# --- Models ---
class Token(BaseModel):
    access_token: str
    token_type: str

class LogRequest(BaseModel):
    logs: str
    pod_name: str = "unknown"

class CloudWatchLogsRequest(BaseModel):
    log_group: str
    log_stream: str = None
    minutes: int = 30

class CloudWatchAnalyzeRequest(BaseModel):
    log_group: str
    log_stream: str = None
    minutes: int = 30
    pod_name: str = "unknown"

# --- Auth helpers ---
def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# --- Routes ---
@app.post("/auth/login", response_model=Token)
@limiter.limit("5/minute")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    user = USERS_DB.get(form_data.username)
    if not user or not verify_password(form_data.password, user["password"]):
        raise HTTPException(status_code=401, detail="Wrong username or password")
    token = create_access_token({"sub": form_data.username})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/metrics", dependencies=[Depends(get_current_user)])
def metrics():
    mem = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "memory_mb": round(mem.used / (1024 * 1024)),
        "memory_total_mb": round(mem.total / (1024 * 1024)),
        "memory_percent": mem.percent,
        "host": socket.gethostname(),
    }

@app.post("/api/analyze", dependencies=[Depends(get_current_user)])
@limiter.limit("20/minute")
def analyze(request: Request, payload: LogRequest):
    return _analyze_logs(payload.logs, payload.pod_name)


def _analyze_logs(logs: str, pod_name: str):
    prompt = f"""You are an expert SRE. Analyze these Kubernetes pod logs.

Pod: {pod_name}
Logs:
{logs}

Respond in this exact JSON format with no markdown or extra text:
{{
  "root_cause": "one sentence explanation",
  "immediate_fix": "exact command or action to take",
  "prevention": "one recommendation to stop this recurring",
  "severity": "critical or high or medium or low"
}}"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    return json.loads(response.choices[0].message.content)


def _get_cloudwatch_client():
    return boto3.client(
        "logs",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )


def _fetch_cloudwatch_logs(log_group: str, log_stream: str, minutes: int) -> list[str]:
    cw = _get_cloudwatch_client()
    now = datetime.now(timezone.utc)
    start_ms = int((now - timedelta(minutes=minutes)).timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)

    kwargs = {
        "logGroupName": log_group,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": 200,
    }
    if log_stream:
        kwargs["logStreamNames"] = [log_stream]

    try:
        response = cw.filter_log_events(**kwargs)
    except cw.exceptions.ResourceNotFoundException:
        raise HTTPException(status_code=404, detail=f"Log group '{log_group}' not found")
    except (NoCredentialsError, ClientError) as e:
        raise HTTPException(status_code=502, detail=f"AWS error: {str(e)}")

    return [event["message"] for event in response.get("events", [])]


@app.get("/api/cloudwatch/groups", dependencies=[Depends(get_current_user)])
@limiter.limit("20/minute")
def list_log_groups(request: Request):
    cw = _get_cloudwatch_client()
    try:
        response = cw.describe_log_groups(limit=50)
    except (NoCredentialsError, ClientError) as e:
        raise HTTPException(status_code=502, detail=f"AWS error: {str(e)}")
    groups = [g["logGroupName"] for g in response.get("logGroups", [])]
    return {"log_groups": groups}


@app.post("/api/cloudwatch/logs", dependencies=[Depends(get_current_user)])
@limiter.limit("20/minute")
def get_cloudwatch_logs(request: Request, payload: CloudWatchLogsRequest):
    messages = _fetch_cloudwatch_logs(payload.log_group, payload.log_stream, payload.minutes)
    if not messages:
        return {"log_group": payload.log_group, "events": [], "message": "No log events found in the given time range"}
    return {"log_group": payload.log_group, "events": messages, "count": len(messages)}


@app.post("/api/cloudwatch/analyze", dependencies=[Depends(get_current_user)])
@limiter.limit("20/minute")
def analyze_cloudwatch_logs(request: Request, payload: CloudWatchAnalyzeRequest):
    messages = _fetch_cloudwatch_logs(payload.log_group, payload.log_stream, payload.minutes)
    if not messages:
        raise HTTPException(status_code=404, detail="No log events found in the given time range")
    logs_text = "\n".join(messages)
    return {
        "log_group": payload.log_group,
        "events_analyzed": len(messages),
        **_analyze_logs(logs_text, payload.pod_name),
    }
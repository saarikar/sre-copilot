from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from dotenv import load_dotenv
from groq import Groq
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
import os
import json

load_dotenv()

# --- Config ---
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# --- Setup ---
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
app = FastAPI(title="SRE Copilot")
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app)

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

# --- Auth helpers ---
def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
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
def login(form_data: OAuth2PasswordRequestForm = Depends()):
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
    return {
        "cpu_percent": 42,
        "memory_mb": 512,
        "pod": "auth-service",
        "restarts": 3
    }

@app.post("/api/analyze", dependencies=[Depends(get_current_user)])
def analyze(request: LogRequest):
    prompt = f"""You are an expert SRE. Analyze these Kubernetes pod logs.

Pod: {request.pod_name}
Logs:
{request.logs}

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
    result = json.loads(response.choices[0].message.content)
    return result
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from groq import Groq
import os
import json

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

app = FastAPI(title="SRE Copilot")

class LogRequest(BaseModel):
    logs: str
    pod_name: str = "unknown"

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/metrics")
def metrics():
    return {
        "cpu_percent": 42,
        "memory_mb": 512,
        "pod": "auth-service",
        "restarts": 3
    }

@app.post("/analyze")
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
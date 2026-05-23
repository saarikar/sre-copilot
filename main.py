from fastapi import FastAPI

app = FastAPI()

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
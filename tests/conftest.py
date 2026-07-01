import os

# Must be set before `main` is imported so the Limiter is constructed disabled.
# Otherwise the shared test client IP would trip rate limits across tests.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

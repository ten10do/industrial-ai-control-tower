"""FastAPI application entry point."""

from fastapi import FastAPI

from app.config import Settings

settings = Settings()

app = FastAPI(
    title="Industrial AI Control Tower",
    version="0.1.0",
    description="Backend API for the Industrial AI Control Tower.",
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}

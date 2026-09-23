"""Public ASGI entry point: python -m uvicorn backend.main:app."""

from backend.app.main import app, create_app

__all__ = ["app", "create_app"]

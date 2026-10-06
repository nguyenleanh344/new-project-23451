"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.services import BoreHoleService


def get_service(request: Request) -> BoreHoleService:
    """Return the singleton service bound to ``app.state`` by ``create_app``."""
    return request.app.state.service

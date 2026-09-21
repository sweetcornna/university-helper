"""Server-edition system endpoints (not mounted in the desktop build)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import get_current_user
from app.services.admin import is_admin_user

router = APIRouter()


@router.get("/update")
async def update_status(request: Request, current_user: dict = Depends(get_current_user)):
    """New-version notice for administrators; everyone else gets 403."""
    try:
        user_id = int(current_user.get("user_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    if not await asyncio.to_thread(is_admin_user, user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator only")

    checker = getattr(request.app.state, "update_checker", None)
    if checker is None:
        return {"enabled": False, "current": request.app.version, "has_update": False}
    return await checker.get_status()

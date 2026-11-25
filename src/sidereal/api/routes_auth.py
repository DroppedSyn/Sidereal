"""``/api/auth``: login, logout, me (plan §11.2).

Login and logout are POSTs, so the write guard (``X-Sidereal: 1`` + allowed Origin) applies to
them like any other write. Login failures of every kind get the same 401 body; the rate limit
answers 429. Validation errors on these paths never echo the submitted values (see ``app``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from sidereal.api.deps import get_now, get_settings, open_db
from sidereal.auth import ratelimit, sessions
from sidereal.auth.login import authenticate
from sidereal.auth.middleware import client_ip
from sidereal.config import Settings

router = APIRouter()

INVALID = "invalid username, password or code"
LIMITED = "too many failed attempts, try again later"


class LoginIn(BaseModel):
    username: str
    password: str
    code: str | None = None  # TOTP, when the account has one


class Me(BaseModel):
    auth: Literal["on", "off"]
    username: str | None


@router.post("/api/auth/login", response_model=Me,
             responses={401: {"description": "login failed"}, 404: {"description": "auth off"},
                        429: {"description": "rate limited"}})
def login(body: LoginIn, request: Request, response: Response,
          settings: Annotated[Settings, Depends(get_settings)],
          now: Annotated[datetime, Depends(get_now)]) -> Me:
    if settings.auth.mode != "on":
        raise HTTPException(status_code=404, detail="authentication is off")
    with open_db(settings) as conn:
        result = authenticate(
            conn, settings.auth, username=body.username, password=body.password,
            code=body.code, ip=client_ip(request, settings.web.trusted_proxies),
            user_agent=request.headers.get("user-agent"), now=now,
            old_token=request.cookies.get(sessions.COOKIE_NAME),
        )
    if result.status == "limited":
        raise HTTPException(status_code=429, detail=LIMITED,
                            headers={"Retry-After": str(ratelimit.retry_after_s())})
    if result.status != "ok" or result.token is None:
        raise HTTPException(status_code=401, detail=INVALID)
    sessions.set_cookie(response, result.token, secure=settings.web.https)
    return Me(auth="on", username=result.username)


@router.post("/api/auth/logout", status_code=204, response_class=Response)
def logout(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    """Deletes the session row (if any) and clears the cookie. Always 204."""
    token = request.cookies.get(sessions.COOKIE_NAME)
    if token is not None and settings.db_path.exists():
        with open_db(settings) as conn:
            sessions.revoke(conn, token)
    response = Response(status_code=204)
    sessions.clear_cookie(response, secure=settings.web.https)
    return response


@router.get("/api/auth/me", response_model=Me)
def me(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> Me:
    """Auth off → ``{auth: off, username: null}``; on → the session's user (the middleware has
    already answered 401 without one)."""
    if settings.auth.mode != "on":
        return Me(auth="off", username=None)
    user = request.state.user
    return Me(auth="on", username=user.username if user is not None else None)

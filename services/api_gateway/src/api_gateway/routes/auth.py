"""OIDC + session routes.

* ``GET  /auth/oidc/login``    → 302 to IdP (or returns URL via ``?return=json``).
* ``GET  /auth/oidc/callback`` → consumes ``code`` + ``state``, sets session cookie.
* ``POST /auth/logout``        → clears the session cookie.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from agenticos_shared.audit import AuditEvent, Decision
from agenticos_shared.errors import UnauthorizedError
from agenticos_shared.models import Tenant, User
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit_bus import get_emitter
from ..auth.oidc import (
    build_login_url,
    discover,
    exchange_code,
    random_token,
    verify_id_token,
)
from ..auth.session import SessionPayload, encode_session
from ..db import get_db
from ..schemas import LoginResponse
from ..settings import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])

OIDC_STATE_COOKIE = "agos_oidc_state"
OIDC_NONCE_COOKIE = "agos_oidc_nonce"
OIDC_RETURN_COOKIE = "agos_oidc_return"


@router.get("/oidc/login", response_model=None)
async def oidc_login(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    return_to: Annotated[str | None, Query(alias="return_to")] = None,
    json: Annotated[bool, Query()] = False,
):
    """Begin the OIDC authorization-code flow."""

    md = await discover(settings.oidc_issuer)
    state = random_token()
    nonce = random_token()

    url = build_login_url(
        md,
        client_id=settings.oidc_client_id,
        redirect_uri=settings.oidc_redirect_uri,
        state=state,
        nonce=nonce,
    )

    cookie_kwargs = {
        "httponly": True,
        "secure": settings.session_cookie_secure,
        "samesite": "lax",
        "max_age": 600,
        "path": "/",
    }

    def _redirect_or_json() -> Response:
        if json:
            r = Response(
                content=LoginResponse(authorize_url=url, state=state).model_dump_json(),
                media_type="application/json",
            )
        else:
            r = RedirectResponse(url=url, status_code=302)
        r.set_cookie(OIDC_STATE_COOKIE, state, **cookie_kwargs)
        r.set_cookie(OIDC_NONCE_COOKIE, nonce, **cookie_kwargs)
        if return_to:
            r.set_cookie(OIDC_RETURN_COOKIE, return_to, **cookie_kwargs)
        return r

    return _redirect_or_json()


@router.get("/oidc/callback", response_model=None)
async def oidc_callback(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Session, Depends(get_db)],
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
):
    """Complete the OIDC flow, set session cookie, redirect to web UI."""

    if error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"oidc error: {error}")
    if not code or not state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing code/state")

    expected_state = request.cookies.get(OIDC_STATE_COOKIE)
    nonce = request.cookies.get(OIDC_NONCE_COOKIE)
    return_to = request.cookies.get(OIDC_RETURN_COOKIE) or settings.web_ui_url
    if not expected_state or expected_state != state:
        raise UnauthorizedError("state mismatch")

    md = await discover(settings.oidc_issuer)
    tokens = await exchange_code(
        md,
        code=code,
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        redirect_uri=settings.oidc_redirect_uri,
    )
    id_token = tokens.get("id_token")
    if not id_token:
        raise UnauthorizedError("no id_token in token response")

    claims = await verify_id_token(
        id_token,
        md=md,
        audience=settings.oidc_client_id,
        nonce=nonce,
    )

    if not claims.email:
        raise UnauthorizedError("id_token has no email")

    # Auto-provision tenant on first sight.
    tenant = db.execute(
        select(Tenant).where(Tenant.slug == settings.auto_provision_tenant)
    ).scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(
            id=uuid4(),
            name=settings.auto_provision_tenant.title(),
            slug=settings.auto_provision_tenant,
        )
        db.add(tenant)
        db.flush()

    # Look up or auto-provision the user.
    user = db.execute(
        select(User).where(User.tenant_id == tenant.id, User.email == claims.email)
    ).scalar_one_or_none()
    if user is None:
        user = User(
            id=uuid4(),
            tenant_id=tenant.id,
            email=claims.email,
            display_name=claims.name,
            oidc_sub=claims.sub,
        )
        db.add(user)
        db.flush()
    else:
        user.last_login_at = datetime.now(tz=UTC)
        if claims.sub and not user.oidc_sub:
            user.oidc_sub = claims.sub
        if claims.name and not user.display_name:
            user.display_name = claims.name

    # Build + set the session cookie.
    now = int(time.time())
    payload = SessionPayload(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        display_name=user.display_name,
        issued_at=now,
        expires_at=now + settings.session_ttl_seconds,
    )
    token = encode_session(payload, secret=settings.secret_key)

    redirect = RedirectResponse(url=return_to, status_code=302)
    redirect.delete_cookie(OIDC_STATE_COOKIE, path="/")
    redirect.delete_cookie(OIDC_NONCE_COOKIE, path="/")
    redirect.delete_cookie(OIDC_RETURN_COOKIE, path="/")
    redirect.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_seconds,
        path="/",
    )

    # Audit (best-effort).
    try:
        await get_emitter().emit(
            AuditEvent(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                actor_email=user.email,
                action="auth.login",
                resource_type="user",
                resource_id=str(user.id),
                decision=Decision.ALLOW,
                ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
        )
    except Exception:
        pass

    return redirect


@router.post("/logout")
async def logout(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Clear the session cookie."""

    r = Response(status_code=status.HTTP_204_NO_CONTENT)
    r.delete_cookie(settings.session_cookie_name, path="/")
    try:
        await get_emitter().emit(
            AuditEvent(
                action="auth.logout",
                ip=request.client.host if request.client else None,
            )
        )
    except Exception:
        pass
    return r

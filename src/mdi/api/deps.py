"""FastAPI dependencies — JWT / API-key tenant auth + admin auth + tenant_session injection."""
from __future__ import annotations

import hmac
import uuid
from typing import AsyncIterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mdi.kernel.auth import (
    AuthError,
    decode_jwt,
    hash_api_key,
    tenant_session,
)
from mdi.kernel.settings import get_settings
from mdi.models.db import ApiKey, Tenant


async def require_admin(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
    """Gate POST /admin/* endpoints. Constant-time compare against settings.admin_api_key."""
    s = get_settings()
    if not s.admin_api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "admin endpoints disabled (set ADMIN_API_KEY)",
        )
    supplied = (x_admin_key or "").encode("utf-8")
    expected = s.admin_api_key.encode("utf-8")
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid admin key")


async def authenticate(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> uuid.UUID:
    """Resolve the caller's tenant_id from either a JWT or an API key.

    Header conventions:
      * Authorization: Bearer <jwt>
      * X-API-Key: mdi_<token>
    """
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(None, 1)[1]
        try:
            payload = decode_jwt(token)
            return uuid.UUID(payload["tid"])
        except (AuthError, KeyError, ValueError) as e:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, f"invalid bearer token: {e}"
            ) from e

    if x_api_key:
        # API key lookup must happen WITHOUT a tenant context (we don't know it yet).
        # We use a privileged admin session that bypasses RLS for `api_keys` lookup
        # only. Production may prefer a separate role.
        from mdi.kernel.auth import get_engine

        engine = get_engine()
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    select(ApiKey.tenant_id).where(
                        ApiKey.key_hash == hash_api_key(x_api_key),
                        ApiKey.revoked_at.is_(None),
                    )
                )
            ).first()
            if row is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")
            return row[0]  # type: ignore[no-any-return]

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing credentials")


async def db_session(
    tenant_id: uuid.UUID = Depends(authenticate),
) -> AsyncIterator[AsyncSession]:
    """A tenant-scoped session — RLS GUC is set before the handler runs."""
    async with tenant_session(tenant_id) as session:
        yield session


async def current_tenant(
    tenant_id: uuid.UUID = Depends(authenticate),
    db: AsyncSession = Depends(db_session),
) -> Tenant:
    row = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant not found")
    return row

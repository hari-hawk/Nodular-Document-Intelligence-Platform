"""Auth — JWT + per-tenant API keys + Postgres RLS context injection.

The MOST IMPORTANT function here is `tenant_session()`: it sets the
GUC `app.tenant_id` on every DB connection so RLS policies fire.
Every API handler that reads or writes tenant data MUST go through it.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

import jwt
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from mdi.kernel.observability import get_logger
from mdi.kernel.settings import get_settings

logger = get_logger(__name__)


class AuthError(RuntimeError):
    """Authentication / authorization failure."""


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def issue_jwt(*, tenant_id: uuid.UUID, subject: str, extra: dict[str, Any] | None = None) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "iss": "mdi",
        "sub": subject,
        "tid": str(tenant_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.jwt_ttl_minutes)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_jwt(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except jwt.PyJWTError as e:
        raise AuthError(f"invalid token: {e}") from e


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
def generate_api_key() -> tuple[str, str]:
    """Returns (raw_key, hashed_key). Raw key is shown to user once."""
    raw = "mdi_" + secrets.token_urlsafe(32)
    return raw, hash_api_key(raw)


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# DB engine + tenant-scoped session
# ---------------------------------------------------------------------------
_engine: AsyncEngine | None = None
_sessionmaker: sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.database_url_async,
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            future=True,
        )
        _sessionmaker = sessionmaker(  # type: ignore[call-overload]
            _engine, class_=AsyncSession, expire_on_commit=False,
        )
    return _engine


def reset_engine() -> None:
    """Drop the cached engine — for tests with throwaway DBs."""
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None


@asynccontextmanager
async def tenant_session(tenant_id: uuid.UUID | str) -> AsyncIterator[AsyncSession]:
    """Yield a DB session with `app.tenant_id` set so RLS policies fire.

    Usage::

        async with tenant_session(tenant.id) as db:
            db.add(...)
            await db.commit()

    Skipping this and using a raw session WILL violate the security model.

    Implementation note: the GUC is session-local (is_local=False), not
    transaction-local. Transaction-local GUCs evaporate at the first
    `db.commit()`, which the orchestrator does mid-pipeline; that left
    later reads unfiltered. Session-local survives commits within the
    connection, and we reset it on exit so pooled connections don't
    carry tenant context across requests.
    """
    get_engine()
    assert _sessionmaker is not None
    tid = str(tenant_id)
    async with _sessionmaker() as session:
        await session.execute(
            _set_config_stmt(),
            {"key": "app.tenant_id", "value": tid, "is_local": False},
        )
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            # Defense in depth — clear the GUC on the way out so pooled
            # connections never serve cross-tenant rows by accident.
            try:
                await session.execute(
                    _set_config_stmt(),
                    {"key": "app.tenant_id", "value": "", "is_local": False},
                )
            except Exception:
                pass  # connection may already be in error state


def _set_config_stmt() -> Any:
    """Lazily import to keep top-level import cheap."""
    from sqlalchemy import text
    return text("SELECT set_config(:key, :value, :is_local)")


# ---------------------------------------------------------------------------
# Helper for raw sync sessions (alembic, scripts) — bypasses RLS for migrations.
# ---------------------------------------------------------------------------
def admin_dsn() -> str:
    return get_settings().database_url

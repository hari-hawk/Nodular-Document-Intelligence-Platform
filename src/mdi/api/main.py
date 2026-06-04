"""FastAPI app factory + uvicorn entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mdi.api.routes import router
from mdi.kernel.observability import configure_logging
from mdi.kernel.settings import get_settings


def create_app() -> FastAPI:
    configure_logging()
    s = get_settings()
    app = FastAPI(
        title="MDI - Modular Data Intelligence",
        version="0.1.0",
        description="Multi-domain document intelligence brain with multi-tenant isolation.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()


def run() -> None:
    """Console entrypoint: `mdi-api`."""
    import uvicorn
    s = get_settings()
    uvicorn.run("mdi.api.main:app", host=s.api_host, port=s.api_port, reload=False)

"""FastAPI application entrypoint.

Run it:

    uvicorn app.main:app --reload

Free routes work out of the box. Paid routes require a payee address (set
``PAYEE_EVM_ADDRESS`` in ``.env``); without one, the app logs a warning and
serves everything for free — convenient for local development.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.discovery import register_discovery_manifest
from app.ledger import init_ledger
from app.payment import attach_payment_middleware
from app.routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="x402 Paid API Starter",
        version=__version__,
        description="A FastAPI starter for charging per API call with x402.",
    )

    # Wide-open CORS so browser-based x402 clients and explorers can reach the
    # API. Tighten ``allow_origins`` for production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["PAYMENT-REQUIRED", "PAYMENT-RESPONSE", "X-PAYMENT-RESPONSE"],
    )

    app.include_router(router)
    register_discovery_manifest(app, settings)

    # Create the ledger table up front (also created lazily on first write).
    if settings.payments_enabled:
        init_ledger()

    # Payment middleware is added LAST so it ends up outermost in the stack.
    attach_payment_middleware(app, settings)

    return app


app = create_app()

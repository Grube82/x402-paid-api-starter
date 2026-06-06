"""x402 payment middleware — the heart of the starter.

Wires the x402 protocol into a FastAPI app so that routes listed in
``app.pricing.ROUTE_PRICING`` require a USDC payment per call. The server is
**receive-only**: it needs your public payee address, never a private key.

Request flow (two middleware layers, outermost first):

    _PaymentGateMiddleware   -> lets you bypass x402 for your own authed users
    _LoggingPaymentMiddleware -> the x402 402/verify/settle flow + ledger write
    (your route handler)

Testnet uses the free public x402.org facilitator (Base Sepolia, no auth).
Mainnet uses Coinbase's CDP facilitator (Base + optional Solana), which needs
Ed25519-JWT auth built from your CDP API key.

This is a clean-room reimplementation of a production setup — the SDK import
paths, argument names, and the settlement flow are the parts that are easy to
get wrong, so they mirror what actually works against the x402 2.x line.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from x402.http import PaymentOption
from x402.http.types import RouteConfig
from x402.mechanisms.svm.constants import SOLANA_MAINNET_CAIP2
from x402.mechanisms.svm.exact import ExactSvmServerScheme

from app.config import Settings
from app.discovery import build_bazaar_extension
from app.ledger import record_payment_event
from app.paywall import build_paywall_html
from app.pricing import ROUTE_PRICING, metadata_for

logger = logging.getLogger(__name__)

_MAINNET_NETWORK = "eip155:8453"  # Base mainnet (CAIP-2)
_TESTNET_NETWORK = "eip155:84532"  # Base Sepolia testnet (CAIP-2)

# The public x402.org facilitator supports TESTNET only. Mainnet settlement
# goes through Coinbase's CDP facilitator, which requires Ed25519-JWT auth.
_TESTNET_FACILITATOR_URL = "https://x402.org/facilitator"
_CDP_FACILITATOR_URL = "https://api.cdp.coinbase.com/platform/v2/x402"
_CDP_FACILITATOR_HOST = "api.cdp.coinbase.com"

# Informational hint surfaced (nested under ``extensions``) in the 402 body so
# a human/developer poking at the API learns there could be another way in.
# Customise or remove — agents ignore it.
_ALTERNATIVE_AUTH_MSG = (
    "This endpoint is pay-per-call via x402. If you add your own API-key or "
    "subscription tier, send your key and these requests can bypass x402."
)


# ---------------------------------------------------------------------------
# Route config
# ---------------------------------------------------------------------------
def _make_route_config(
    route_key: str,
    price: str,
    *,
    network: str,
    evm_payee: str,
    solana_payee: str | None,
) -> RouteConfig:
    """Build a RouteConfig with one or two PaymentOptions.

    Args:
        route_key: Method-prefixed key from ROUTE_PRICING (``"GET /v1/...""``).
        price: Price string (e.g. ``"$0.01"``).
        network: EVM CAIP-2 network id (mainnet or testnet).
        evm_payee: EVM payee address.
        solana_payee: If set, append a Solana PaymentOption (mainnet only).

    Returns:
        RouteConfig with the Base (EVM) option ALWAYS first — many clients
        index ``accepts[0]`` — and an optional Solana option second.
    """
    accepts: list[PaymentOption] = [
        PaymentOption(scheme="exact", price=price, network=network, pay_to=evm_payee),
    ]
    if solana_payee:
        # No ``extra={...}`` here on purpose: the SDK's SVM scheme fills in
        # feePayer / tokenProgram / asset from the facilitator's /supported
        # response server-side. Anything set here would be overwritten.
        accepts.append(
            PaymentOption(
                scheme="exact",
                price=price,
                network=SOLANA_MAINNET_CAIP2,
                pay_to=solana_payee,
            )
        )

    meta = metadata_for(route_key)
    return RouteConfig(
        accepts=accepts,
        description=meta.description if meta else None,
        mime_type="application/json",
        extensions=build_bazaar_extension(meta),
        custom_paywall_html=build_paywall_html(
            endpoint=route_key.split(" ", 1)[-1],
            price=price,
            description=meta.description if meta else "",
            dual_chain=bool(solana_payee),
        ),
    )


# ---------------------------------------------------------------------------
# CDP facilitator auth (mainnet only) — Ed25519 JWT per facilitator call
# ---------------------------------------------------------------------------
def _generate_cdp_jwt(
    method: str, host: str, path: str, *, key_id: str, key_secret_b64: str
) -> str:
    """Generate a CDP Ed25519 JWT scoped to one facilitator method + URI.

    The CDP secret is base64-encoded raw 32 bytes of an Ed25519 private key
    seed. Each JWT is scoped to a specific ``METHOD host+path`` and expires in
    120 seconds (CDP rejects mismatched ``uri`` claims).
    """
    import base64
    import time
    import uuid

    import jwt
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    seed = base64.b64decode(key_secret_b64)[:32]
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    now = int(time.time())
    return jwt.encode(
        {
            "iss": "cdp",
            "sub": key_id,
            "nbf": now,
            "exp": now + 120,
            "uri": f"{method.upper()} {host}{path}",
        },
        sk,
        algorithm="EdDSA",
        headers={"kid": key_id, "nonce": uuid.uuid4().hex},
    )


def _build_cdp_auth_provider(key_id: str, key_secret_b64: str) -> Any:
    """Build an x402 AuthProvider that signs a fresh CDP JWT per call.

    The facilitator client makes three kinds of calls (verify / settle /
    supported); each needs its own JWT scoped to that path.
    """
    from x402.http.facilitator_client_base import CreateHeadersAuthProvider

    def _bearer(path: str, method: str = "POST") -> dict[str, str]:
        token = _generate_cdp_jwt(
            method, _CDP_FACILITATOR_HOST, path, key_id=key_id, key_secret_b64=key_secret_b64
        )
        return {"Authorization": f"Bearer {token}"}

    def create_headers() -> dict[str, dict[str, str]]:
        return {
            "verify": _bearer("/platform/v2/x402/verify"),
            "settle": _bearer("/platform/v2/x402/settle"),
            "supported": _bearer("/platform/v2/x402/supported", method="GET"),
        }

    return CreateHeadersAuthProvider(create_headers)


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
def attach_payment_middleware(app: Any, settings: Settings) -> None:
    """Attach the x402 payment middleware to a FastAPI app.

    No-op (with a warning) if ``settings.payments_enabled`` is False, so the
    API runs fine in local dev with no wallet configured.

    Raises:
        RuntimeError: if mainnet is selected but CDP credentials are missing.
    """
    from x402.http import FacilitatorConfig, HTTPFacilitatorClient
    from x402.mechanisms.evm.exact import ExactEvmServerScheme
    from x402.server import x402ResourceServer

    if not settings.payments_enabled:
        logger.warning("PAYEE_EVM_ADDRESS not set — payments disabled, all routes are free.")
        return

    network = _TESTNET_NETWORK if settings.testnet else _MAINNET_NETWORK
    solana_payee = settings.payee_solana_address if settings.dual_chain else None

    # Pick facilitator + auth.
    if settings.testnet:
        facilitator_url = _TESTNET_FACILITATOR_URL
        auth_provider = None
        logger.info("x402 facilitator: x402.org public (Base Sepolia testnet)")
    else:
        facilitator_url = _CDP_FACILITATOR_URL
        key_id = os.environ.get("CDP_API_KEY_ID", "").strip()
        key_secret = os.environ.get("CDP_API_KEY_SECRET", "").strip()
        if not key_id or not key_secret:
            raise RuntimeError(
                "Mainnet (X402_TESTNET=false) requires CDP_API_KEY_ID and "
                "CDP_API_KEY_SECRET. Get them free at https://portal.cdp.coinbase.com "
                "(1000 settlements/month). The public x402.org facilitator is testnet-only."
            )
        auth_provider = _build_cdp_auth_provider(key_id, key_secret)
        logger.info("x402 facilitator: Coinbase CDP (mainnet)")

    server = x402ResourceServer(
        HTTPFacilitatorClient(FacilitatorConfig(url=facilitator_url, auth_provider=auth_provider))
    )
    server.register(network, ExactEvmServerScheme())
    if solana_payee:
        server.register(SOLANA_MAINNET_CAIP2, ExactSvmServerScheme())
        logger.info("x402 Solana mainnet acceptance enabled")

    # Required for CDP Bazaar discovery — without it, routes are never indexed.
    from x402.extensions.bazaar import bazaar_resource_server_extension

    # Upstream typing quirk: the bazaar extension's type doesn't match
    # register_extension's signature, though it's the documented way to use it
    # and works at runtime. Remove this ignore if the SDK tightens the types.
    server.register_extension(bazaar_resource_server_extension)  # type: ignore[arg-type]

    # Build route configs — insertion order = matching precedence.
    routes = {
        route_key: _make_route_config(
            route_key,
            price,
            network=network,
            evm_payee=settings.payee_evm_address,
            solana_payee=solana_payee,
        )
        for route_key, price in ROUTE_PRICING.items()
    }

    # add_middleware uses insert(0, ...), so the LAST added is OUTERMOST.
    # The gate must be outermost so it can decide whether to route through x402.
    app.add_middleware(_LoggingPaymentMiddleware, routes=routes, server=server)
    app.add_middleware(_PaymentGateMiddleware)

    chains = "Base + Solana" if solana_payee else "Base"
    logger.info("x402 attached: %d priced routes on %s", len(routes), chains)


# ---------------------------------------------------------------------------
# Gate: decide which requests go through x402
# ---------------------------------------------------------------------------
class _PaymentGateMiddleware:
    """Routes keyless requests through x402; lets keyed requests bypass it.

    x402's flow starts with a request that carries NO payment header, so we
    can't use the payment header to decide routing. Instead we look for your
    own auth (here: an ``X-Api-Key`` header) as the bypass signal:

      * has X-Api-Key  -> skip x402 (your own authed user / subscriber path)
      * no  X-Api-Key  -> route through x402 (agent pays per call, or free route)

    If you don't have a key-based tier, this layer is harmless — every request
    simply flows through x402. It's here because "let my subscribers skip
    paying per call" is a question almost everyone hits eventually.
    """

    def __init__(self, app: Any) -> None:
        self.app = app  # the x402 logging middleware
        self._bypass_target: Any | None = None

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        has_api_key = b"x-api-key" in headers and headers[b"x-api-key"].strip()

        if has_api_key:
            # Skip the x402 layer entirely, jump to whatever it wraps.
            if self._bypass_target is None:
                self._bypass_target = getattr(self.app, "app", self.app)
            await self._bypass_target(scope, receive, send)
        else:
            await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# x402 flow + ledger write
# ---------------------------------------------------------------------------
class _LoggingPaymentMiddleware(BaseHTTPMiddleware):
    """The x402 402/verify/settle flow, plus one ledger row per settlement.

    Mirrors the x402 SDK's FastAPI middleware so protocol semantics don't
    drift, with a single ``record_payment_event(...)`` added after a
    successful on-chain settlement.
    """

    def __init__(self, app: Any, routes: Any, server: Any) -> None:
        from x402.http.x402_http_server import x402HTTPResourceServer

        super().__init__(app)
        self._http_server = x402HTTPResourceServer(server, routes)
        self._init_done = False

    async def dispatch(self, request: Any, call_next: Any) -> Any:
        from fastapi.responses import HTMLResponse, JSONResponse
        from starlette.responses import Response
        from x402.http.middleware.fastapi import FastAPIAdapter
        from x402.http.types import HTTPRequestContext

        adapter = FastAPIAdapter(request)
        context = HTTPRequestContext(
            adapter=adapter,
            path=request.url.path,
            method=request.method,
            payment_header=(
                adapter.get_header("payment-signature") or adapter.get_header("x-payment")
            ),
        )

        # Free route — pass straight through.
        if not self._http_server.requires_payment(context):
            return await call_next(request)

        # On first protected request, fetch facilitator capabilities.
        if not self._init_done:
            self._http_server.initialize()
            self._init_done = True

        result = await self._http_server.process_http_request(context, None)

        if result.type == "no-payment-required":
            return await call_next(request)

        if result.type == "payment-error":
            return self._payment_error_response(result, JSONResponse, HTMLResponse)

        if result.type == "payment-verified":
            return await self._settle_and_respond(
                request, call_next, result, JSONResponse, Response
            )

        # Unknown result type — match upstream fallthrough.
        return await call_next(request)

    def _payment_error_response(self, result: Any, JSONResponse: Any, HTMLResponse: Any) -> Any:
        """Build the 402 (or other payment-error) response."""
        response = result.response
        if response is None:
            return JSONResponse(
                content={
                    "error": "Payment required",
                    "extensions": {"alternativeAuth": _ALTERNATIVE_AUTH_MSG},
                },
                status_code=402,
                headers={"Cache-Control": "no-store"},
            )

        if response.is_html:
            return HTMLResponse(
                content=response.body, status_code=response.status, headers=response.headers
            )

        # x402 v2 writes the challenge to the PAYMENT-REQUIRED header and leaves
        # the body empty. Some clients still read the body — mirror it so both
        # styles work.
        body = response.body or {}
        if not body and response.status == 402:
            import base64
            import contextlib
            import json

            pr = response.headers.get("payment-required") or response.headers.get(
                "PAYMENT-REQUIRED"
            )
            if pr:
                with contextlib.suppress(Exception):
                    body = json.loads(base64.b64decode(pr).decode())

        if isinstance(body, dict) and response.status == 402:
            ext = body.setdefault("extensions", {})
            if isinstance(ext, dict):
                ext.setdefault("alternativeAuth", _ALTERNATIVE_AUTH_MSG)

        headers = dict(response.headers)
        if response.status == 402:
            headers["Cache-Control"] = "no-store"  # never cache a payment challenge

        return JSONResponse(content=body, status_code=response.status, headers=headers)

    async def _settle_and_respond(
        self, request: Any, call_next: Any, result: Any, JSONResponse: Any, Response: Any
    ) -> Any:
        """Run the handler, settle on-chain, record the ledger row, respond."""
        request.state.payment_payload = result.payment_payload
        request.state.payment_requirements = result.payment_requirements

        response = await call_next(request)

        # Don't settle if the handler errored — the buyer shouldn't pay for a 5xx.
        if response.status_code >= 400:
            return response

        # Buffer the body so we can re-emit it with settlement headers attached.
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        try:
            settle = await self._http_server.process_settlement(
                result.payment_payload, result.payment_requirements
            )
            if not settle.success:
                return JSONResponse(
                    content={"error": "Settlement failed", "details": settle.error_reason},
                    status_code=402,
                )

            # The only behavioural addition to the plain x402 flow: record the
            # sale. record_payment_event swallows its own errors, so a broken
            # ledger never breaks a settled payment.
            reqs = result.payment_requirements
            await record_payment_event(
                network=getattr(settle, "network", "") or getattr(reqs, "network", ""),
                route=request.url.path,
                method=request.method,
                payer_address=getattr(settle, "payer", "") or "",
                pay_to_address=getattr(reqs, "pay_to", "") or "",
                asset_address=getattr(reqs, "asset", None),
                amount_raw=str(getattr(reqs, "amount", "")),
                tx_hash=getattr(settle, "transaction", "") or "",
                raw_payload={"scheme": getattr(reqs, "scheme", None)},
            )

            headers = dict(response.headers)
            headers.update(settle.headers)
            return Response(
                content=body,
                status_code=response.status_code,
                headers=headers,
                media_type=response.media_type,
            )
        except Exception as e:  # noqa: BLE001 — settlement failures must return 402, not 500
            return JSONResponse(
                content={"error": "Settlement failed", "details": str(e)}, status_code=402
            )

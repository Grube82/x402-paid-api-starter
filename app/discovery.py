"""Discovery — how buyers (and their agents) find your paid endpoints.

Two complementary surfaces:

1. **CDP Bazaar extension** (``build_bazaar_extension``): attaches per-route
   metadata to each ``RouteConfig`` so Coinbase's facilitator indexes your
   endpoint in the x402 Bazaar after the first successful settlement. This is
   the path that actually gets you listed in agent-facing directories.

2. **``/.well-known/x402`` manifest** (``register_discovery_manifest``): a
   plain JSON document any human or crawler can read to see your price list at
   a glance. Not required by the protocol, but cheap and friendly.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.pricing import ROUTE_METADATA, ROUTE_PRICING, RouteMeta


def build_bazaar_extension(meta: RouteMeta | None) -> dict[str, Any] | None:
    """Build the ``extensions`` dict for a RouteConfig from route metadata.

    Returns ``None`` when there's no metadata — pass that straight to
    ``RouteConfig(extensions=...)``.
    """
    if meta is None:
        return None

    from x402.extensions.bazaar import OutputConfig, declare_discovery_extension

    output: OutputConfig | None = None
    if meta.output_example is not None or meta.output_schema is not None:
        output = OutputConfig(example=meta.output_example, schema=meta.output_schema)

    return declare_discovery_extension(
        input=meta.input_example or {},
        input_schema=meta.input_schema or {"type": "object", "properties": {}},
        output=output,
    )


def build_manifest(settings: Settings) -> dict[str, Any]:
    """Build the ``/.well-known/x402`` manifest from the price list + metadata."""
    base = (settings.public_base_url or "").rstrip("/")
    accepts = ["base", "solana"] if settings.dual_chain else ["base"]
    network = "base-sepolia" if settings.testnet else "base-mainnet"

    resources: list[dict[str, Any]] = []
    for route_key, price in ROUTE_PRICING.items():
        method, _, path = route_key.partition(" ")
        meta = ROUTE_METADATA.get(route_key)
        entry: dict[str, Any] = {
            "method": method,
            "path": path,
            "price": price,
            "accepts": accepts,
        }
        if base:
            entry["url"] = base + path
        if meta is not None:
            entry["description"] = meta.description
            if meta.input_example is not None:
                entry["input_example"] = meta.input_example
            if meta.output_example is not None:
                entry["output_example"] = meta.output_example
        resources.append(entry)

    return {
        "x402Version": 2,
        "network": network,
        "asset": "USDC",
        "resources": resources,
    }


def register_discovery_manifest(app: Any, settings: Settings) -> None:
    """Register the ``GET /.well-known/x402`` route on the FastAPI app.

    The manifest is a free, public route — it advertises your price list, so it
    must never be paid.
    """

    @app.get("/.well-known/x402", include_in_schema=False)
    def x402_manifest() -> dict[str, Any]:
        return build_manifest(settings)

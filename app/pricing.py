"""What you charge for, and how it's described for discovery.

This is the file you edit to monetise your own endpoints. Two things live here:

* ``ROUTE_PRICING`` — the price list. Any ``"METHOD /path"`` in this dict is a
  paid route; anything not in it is free.
* ``ROUTE_METADATA`` — optional, per-route descriptions + example/schema used
  to make your endpoints discoverable (CDP Bazaar + the ``/.well-known/x402``
  manifest). Skip an entry and the route still works, just with less metadata.

The example routes below return fake "reports" — replace them (and the handlers
in ``app/routes.py``) with your own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Price list.
#
# Dict INSERTION ORDER is the route-matching precedence — x402 returns the
# first match, so put more-specific paths BEFORE wildcards, e.g.
#     "GET /v1/reports/item"   before   "GET /v1/reports/*"
#
# Pattern syntax (from the x402 SDK):
#   *        matches any sequence of characters (wildcard)
#   [param]  matches a single path segment (no slashes)
#   {param}  is NOT supported — use * or [param]
#
# Tip: for high-cardinality identifiers (user ids, etc.), prefer a query param
# (?id=...) over a path template, so discovery indexes ONE route template
# instead of one literal URL per id.
# ---------------------------------------------------------------------------
ROUTE_PRICING: dict[str, str] = {
    "GET /v1/reports/latest": "$0.01",
    "GET /v1/reports/item": "$0.001",
}


@dataclass(frozen=True)
class RouteMeta:
    """Discovery metadata for one route.

    Attributes:
        description: One-line, natural-language summary (used in search).
        output_example: Representative success-response JSON.
        output_schema: JSON Schema for the response body.
        input_example: Example query params, e.g. ``{"id": "abc123"}``.
        input_schema: JSON Schema for accepted query params.
    """

    description: str
    output_example: Any | None = None
    output_schema: dict[str, Any] | None = None
    input_example: dict[str, Any] | None = None
    input_schema: dict[str, Any] | None = None


ROUTE_METADATA: dict[str, RouteMeta] = {
    "GET /v1/reports/latest": RouteMeta(
        description="Latest generated report (example endpoint).",
        output_example={"id": "rpt_001", "title": "Example report", "value": 42},
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "value": {"type": "number"},
            },
        },
    ),
    "GET /v1/reports/item": RouteMeta(
        description="A single report by id (example endpoint).",
        input_example={"id": "rpt_001"},
        input_schema={
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
        output_example={"id": "rpt_001", "title": "Example report", "value": 42},
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "value": {"type": "number"},
            },
        },
    ),
}


def metadata_for(method_and_path: str) -> RouteMeta | None:
    """Look up metadata by route key (e.g. ``"GET /v1/reports/latest"``)."""
    return ROUTE_METADATA.get(method_and_path)

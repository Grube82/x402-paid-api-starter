"""Example endpoints — replace these with your own.

The handlers below are deliberately trivial: they return fake "reports" so you
can see the payment flow end-to-end. What makes a route *paid* is its presence
in ``app.pricing.ROUTE_PRICING`` — NOT anything here. Add a handler, add a
price entry with the same ``"METHOD /path"`` key, and it's monetised.

Note there's no payment logic in these handlers at all. By the time a handler
runs, the middleware has already verified payment — your code just returns data.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

# Stand-in data. Swap for your real source.
_FAKE_REPORTS = {
    "rpt_001": {"id": "rpt_001", "title": "Example report", "value": 42},
    "rpt_002": {"id": "rpt_002", "title": "Another report", "value": 7},
}


@router.get("/v1/ping")
def ping() -> dict[str, str]:
    """Free health-check route (not in ROUTE_PRICING, so no payment required)."""
    return {"status": "ok"}


@router.get("/v1/reports/latest")
def latest_report() -> dict[str, object]:
    """Paid example: return the most recent report."""
    return _FAKE_REPORTS["rpt_002"]


@router.get("/v1/reports/item")
def report_item(id: str) -> dict[str, object]:
    """Paid example with a query param (``?id=rpt_001``).

    Query params are preferred over path templates for high-cardinality ids —
    discovery then indexes one route template instead of one URL per id.
    """
    return _FAKE_REPORTS.get(id, {"error": "not found", "id": id})

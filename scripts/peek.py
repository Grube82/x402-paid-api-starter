#!/usr/bin/env python3
"""Peek at a route's 402 payment challenge — WITHOUT paying.

A quick way to see exactly what a client is asked to pay: the price, the
network, the accepted chains, and your payee address. No wallet needed.

Usage:
    python scripts/peek.py http://localhost:8000/v1/reports/latest
"""

from __future__ import annotations

import base64
import json
import sys

import httpx


def peek(url: str) -> int:
    resp = httpx.get(url, timeout=15.0, follow_redirects=True)
    print(f"status: {resp.status_code}")

    if resp.status_code != 402:
        print("Not a 402 — this route is either free or returned something else.")
        print(f"body (first 300): {resp.text[:300]}")
        return 0

    # x402 v2 puts the challenge in the PAYMENT-REQUIRED header (base64 JSON);
    # older clients read it from the body. Try the header first.
    header = resp.headers.get("payment-required") or resp.headers.get("PAYMENT-REQUIRED")
    if header:
        challenge = json.loads(base64.b64decode(header).decode())
    else:
        challenge = resp.json()

    print("payment challenge:")
    print(json.dumps(challenge, indent=2))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/peek.py <url>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(peek(sys.argv[1]))

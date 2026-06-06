#!/usr/bin/env python3
"""Pay a route end-to-end and print the settlement receipt.

This is the *client* side — it signs a USDC payment and completes the x402
handshake against a running server. Use it to prove the whole flow works.

╔══════════════════════════════════════════════════════════════════════════╗
║  SECURITY                                                                 ║
║  • Use a THROWAWAY wallet funded with a tiny amount of TESTNET USDC.      ║
║  • NEVER paste a real/main wallet's private key into a script or shell.   ║
║  • NEVER commit a private key. Pass it via an env var, not an argument    ║
║    (arguments leak into shell history and process listings).              ║
╚══════════════════════════════════════════════════════════════════════════╝

Get testnet funds:
    • Base Sepolia ETH (gas): https://www.alchemy.com/faucets/base-sepolia
    • Base Sepolia USDC:      https://faucet.circle.com  (select Base Sepolia)

Usage:
    export PAYER_PRIVATE_KEY=0x...          # throwaway testnet key
    python scripts/pay_example.py http://localhost:8000/v1/reports/latest

Requires the client extras:
    pip install -e ".[client]"
"""

from __future__ import annotations

import os
import sys
from typing import Any

# Base network ids (CAIP-2) for explorer links.
_BASE_SEPOLIA = "eip155:84532"
_BASE_MAINNET = "eip155:8453"


def pay(url: str, private_key: str) -> int:
    # Imported lazily so the script gives a clean message if extras are missing.
    try:
        import requests  # noqa: F401
        from eth_account import Account
        from x402 import x402ClientSync
        from x402.http.clients.requests import x402_requests
        from x402.http.utils import decode_payment_response_header
        from x402.mechanisms.evm.exact import register_exact_evm_client
        from x402.mechanisms.evm.signers import EthAccountSigner
    except ImportError:
        print(
            "Missing client dependencies. Install them with:\n"
            '    pip install -e ".[client]"',
            file=sys.stderr,
        )
        return 2

    account = Account.from_key(private_key)
    print(f"payer address: {account.address}")

    # Build an x402-aware requests session: it transparently handles the
    # 402 -> sign -> retry handshake for you.
    client = x402ClientSync()
    register_exact_evm_client(client, EthAccountSigner(account))
    session = x402_requests(client)

    print(f"GET {url}")
    resp = session.get(url, timeout=60)
    print(f"status: {resp.status_code}")

    receipt = resp.headers.get("PAYMENT-RESPONSE") or resp.headers.get("X-PAYMENT-RESPONSE")
    if receipt:
        settle: Any = decode_payment_response_header(receipt)
        print(f"settlement tx: {settle.transaction}")
        print(f"network:       {settle.network}")
        print(f"payer:         {settle.payer}")
        if settle.network == _BASE_SEPOLIA:
            print(f"explorer:      https://sepolia.basescan.org/tx/{settle.transaction}")
        elif settle.network == _BASE_MAINNET:
            print(f"explorer:      https://basescan.org/tx/{settle.transaction}")
    else:
        print("no PAYMENT-RESPONSE header — the request may not have settled.", file=sys.stderr)

    print(f"body (first 400): {resp.text[:400]}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/pay_example.py <url>", file=sys.stderr)
        raise SystemExit(2)

    key = os.environ.get("PAYER_PRIVATE_KEY", "").strip()
    if not key:
        print(
            "Set PAYER_PRIVATE_KEY to a THROWAWAY testnet private key first:\n"
            "    export PAYER_PRIVATE_KEY=0x...",
            file=sys.stderr,
        )
        raise SystemExit(2)

    raise SystemExit(pay(sys.argv[1], key))

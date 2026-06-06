"""Network-free tests for the starter.

These cover the parts that should never break when you adapt the template:
pricing/metadata consistency, free-route passthrough, the discovery manifest,
the paywall renderer, and the ledger's idempotency contract.

The full paid -> 402 -> settle flow needs a live facilitator + funded wallet,
so it's exercised by ``scripts/pay_example.py`` against a running server rather
than in unit tests.
"""

from __future__ import annotations

import asyncio

import app.config as config
from app.config import Settings
from app.discovery import build_manifest
from app.paywall import build_paywall_html
from app.pricing import ROUTE_METADATA, ROUTE_PRICING


def _make_settings(**overrides: object) -> Settings:
    base = dict(
        payee_evm_address="0x000000000000000000000000000000000000dEaD",
        payee_solana_address=None,
        testnet=True,
        cdp_api_key_id="",
        cdp_api_key_secret="",
        public_base_url=None,
        ledger_db_path="payments.db",
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_metadata_keys_are_priced() -> None:
    """Every metadata entry must correspond to a priced route."""
    assert set(ROUTE_METADATA).issubset(set(ROUTE_PRICING))


def test_route_keys_well_formed() -> None:
    """Price-list keys must be ``METHOD /path``."""
    for key in ROUTE_PRICING:
        method, _, path = key.partition(" ")
        assert method.isupper()
        assert path.startswith("/")


def test_free_route_and_passthrough(monkeypatch) -> None:
    """With payments disabled, free routes work AND paid routes pass through."""
    from fastapi.testclient import TestClient

    monkeypatch.delenv("PAYEE_EVM_ADDRESS", raising=False)
    config.get_settings.cache_clear()
    from app.main import create_app

    client = TestClient(create_app())
    assert client.get("/v1/ping").status_code == 200
    # No payee configured -> payments off -> the priced route is served free.
    assert client.get("/v1/reports/latest").status_code == 200
    assert client.get("/.well-known/x402").status_code == 200
    config.get_settings.cache_clear()


def test_manifest_base_only() -> None:
    m = build_manifest(_make_settings(testnet=True))
    assert m["x402Version"] == 2
    assert m["network"] == "base-sepolia"
    assert len(m["resources"]) == len(ROUTE_PRICING)
    assert all(r["accepts"] == ["base"] for r in m["resources"])


def test_manifest_dual_chain() -> None:
    m = build_manifest(
        _make_settings(
            testnet=False,
            payee_solana_address="SoLanaPayeeAddressBase58Example1111111111",
            public_base_url="https://api.example.com",
        )
    )
    assert m["network"] == "base-mainnet"
    assert all(r["accepts"] == ["base", "solana"] for r in m["resources"])
    assert all(r["url"].startswith("https://api.example.com") for r in m["resources"])


def test_paywall_renders_details() -> None:
    html = build_paywall_html(
        endpoint="/v1/reports/latest", price="$0.01", description="desc", dual_chain=True
    )
    assert "/v1/reports/latest" in html
    assert "$0.01" in html
    assert "USDC on Base or Solana" in html
    assert "<script" not in html.lower()  # no-JS guarantee


def test_ledger_idempotent(monkeypatch, tmp_path) -> None:
    """Recording the same tx_hash twice writes exactly one row."""
    db = tmp_path / "ledger.db"
    monkeypatch.setenv("LEDGER_DB_PATH", str(db))
    monkeypatch.setenv("PAYEE_EVM_ADDRESS", "0x000000000000000000000000000000000000dEaD")
    config.get_settings.cache_clear()

    import importlib

    import app.ledger as ledger

    importlib.reload(ledger)
    ledger.init_ledger()

    async def _record() -> None:
        for _ in range(2):
            await ledger.record_payment_event(
                network="eip155:84532",
                route="/v1/reports/latest",
                method="GET",
                payer_address="0xpayer",
                pay_to_address="0xpayee",
                asset_address="0xusdc",
                amount_raw="10000",
                tx_hash="0xdeadbeef",
            )

    asyncio.run(_record())
    rows = list(ledger.iter_payment_events())
    assert len(rows) == 1
    assert rows[0].amount_usd == 0.01  # 10000 / 1e6
    config.get_settings.cache_clear()

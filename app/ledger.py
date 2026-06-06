"""Settlement ledger — one SQLite row per successful on-chain payment.

This is a *receipt book*, not custody: the money settles to your wallet
on-chain; this records that the sale happened so you can answer "how many
sales, which routes, how much?" from your own database.

Design notes worth keeping if you adapt this:
    * ``record_payment_event`` is async and never raises — a broken ledger
      must NEVER break a payment that already settled on-chain.
    * The SQLite write runs in a thread (``asyncio.to_thread``) so it doesn't
      block the event loop.
    * ``tx_hash`` is UNIQUE and the insert is ``INSERT OR IGNORE`` — so the
      writer is idempotent: the same settlement recorded twice is a no-op.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

# USDC has 6 decimals on every chain. Derive from the asset contract if you
# ever price a non-USDC token.
_USDC_DECIMALS = 6

_SCHEMA = """
CREATE TABLE IF NOT EXISTS payment_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT    NOT NULL,
    network       TEXT    NOT NULL,
    is_mainnet    INTEGER NOT NULL,
    route         TEXT    NOT NULL,
    method        TEXT    NOT NULL,
    payer_address TEXT    NOT NULL,
    pay_to_address TEXT   NOT NULL,
    asset_address TEXT,
    amount_raw    TEXT    NOT NULL,
    amount_usd    REAL    NOT NULL,
    tx_hash       TEXT    NOT NULL UNIQUE,
    raw_payload   TEXT
);
"""

# Networks treated as mainnet for the ``is_mainnet`` column.
_MAINNET_NETWORKS = frozenset(
    {
        "eip155:8453",  # Base mainnet
        "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",  # Solana mainnet
    }
)


@dataclass(frozen=True)
class PaymentEvent:
    """A settled payment row, exactly as stored."""

    id: int
    created_at: str
    network: str
    is_mainnet: bool
    route: str
    method: str
    payer_address: str
    pay_to_address: str
    asset_address: str | None
    amount_raw: str
    amount_usd: float
    tx_hash: str
    raw_payload: str | None


def _db_path() -> str:
    return get_settings().ledger_db_path


def init_ledger() -> None:
    """Create the ledger table if it doesn't exist. Safe to call repeatedly."""
    with sqlite3.connect(_db_path()) as conn:
        conn.execute(_SCHEMA)


def _amount_to_usd(amount_raw: str | int, decimals: int = _USDC_DECIMALS) -> float:
    """Convert a smallest-unit USDC amount to a decimal USD value (0.0 on error)."""
    try:
        return int(amount_raw) / (10**decimals)
    except (TypeError, ValueError):
        return 0.0


async def record_payment_event(
    *,
    network: str,
    route: str,
    method: str,
    payer_address: str,
    pay_to_address: str,
    asset_address: str | None,
    amount_raw: str,
    tx_hash: str,
    raw_payload: dict[str, Any] | None = None,
) -> None:
    """Record one settled payment. Never raises.

    Called from the payment middleware after the facilitator confirms
    settlement. See module docstring for the idempotency contract.
    """
    await asyncio.to_thread(
        _write,
        network=network,
        route=route,
        method=method,
        payer_address=payer_address,
        pay_to_address=pay_to_address,
        asset_address=asset_address,
        amount_raw=amount_raw,
        tx_hash=tx_hash,
        raw_payload=raw_payload,
    )


def _write(
    *,
    network: str,
    route: str,
    method: str,
    payer_address: str,
    pay_to_address: str,
    asset_address: str | None,
    amount_raw: str,
    tx_hash: str,
    raw_payload: dict[str, Any] | None,
) -> None:
    """Sync DB write (runs inside ``asyncio.to_thread``). Never raises."""
    try:
        created_at = datetime.now(UTC).isoformat()
        is_mainnet = 1 if network in _MAINNET_NETWORKS else 0
        amount_usd = _amount_to_usd(amount_raw)
        raw_json = json.dumps(raw_payload, default=str) if raw_payload is not None else None

        with sqlite3.connect(_db_path()) as conn:
            conn.execute(_SCHEMA)  # ensure table exists even if init was skipped
            conn.execute(
                """
                INSERT OR IGNORE INTO payment_events (
                    created_at, network, is_mainnet, route, method,
                    payer_address, pay_to_address, asset_address,
                    amount_raw, amount_usd, tx_hash, raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    network,
                    is_mainnet,
                    route,
                    method,
                    payer_address,
                    pay_to_address,
                    asset_address,
                    str(amount_raw),
                    amount_usd,
                    tx_hash,
                    raw_json,
                ),
            )
        logger.info(
            "payment logged: tx=%s amount=$%.6f network=%s route=%s",
            (tx_hash[:12] + "...") if len(tx_hash) > 12 else tx_hash,
            amount_usd,
            network,
            route,
        )
    except Exception:
        logger.exception(
            "Failed to log payment (tx=%s, route=%s) — payment settled on-chain "
            "but the ledger row was NOT written",
            tx_hash,
            route,
        )


def iter_payment_events(*, since: str | None = None) -> Iterator[PaymentEvent]:
    """Stream ledger rows in chronological order.

    Args:
        since: ISO date/timestamp lower bound (inclusive), or None for all rows.

    Yields:
        ``PaymentEvent`` instances.
    """
    sql = (
        "SELECT id, created_at, network, is_mainnet, route, method, "
        "payer_address, pay_to_address, asset_address, amount_raw, "
        "amount_usd, tx_hash, raw_payload FROM payment_events"
    )
    params: list[Any] = []
    if since is not None:
        sql += " WHERE created_at >= ?"
        params.append(since)
    sql += " ORDER BY created_at ASC, id ASC"

    with sqlite3.connect(_db_path()) as conn:
        conn.execute(_SCHEMA)
        for row in conn.execute(sql, params):
            yield PaymentEvent(
                id=row[0],
                created_at=row[1],
                network=row[2],
                is_mainnet=bool(row[3]),
                route=row[4],
                method=row[5],
                payer_address=row[6],
                pay_to_address=row[7],
                asset_address=row[8],
                amount_raw=row[9],
                amount_usd=row[10],
                tx_hash=row[11],
                raw_payload=row[12],
            )

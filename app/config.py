"""Environment-driven configuration.

All settings come from environment variables (loaded from a local ``.env``
file if present). Keeping config in one place — rather than scattering
``os.environ`` reads across modules — is a small habit that pays off as a
project grows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

# Load .env into the process environment once, at import time. Real env vars
# always win over .env values (load_dotenv does not override by default).
load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean env var. Accepts true/1/yes/on (case-insensitive)."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings.

    Attributes:
        payee_evm_address: Public wallet address that receives EVM (Base)
            payments. Empty string disables payments entirely (all routes
            free) — useful for local development.
        payee_solana_address: Optional Solana base58 payee address. Enables
            dual-chain acceptance on mainnet. Ignored on testnet (the public
            testnet facilitator is Base Sepolia only).
        testnet: True = Base Sepolia via the public x402.org facilitator.
            False = Base mainnet via the Coinbase CDP facilitator.
        cdp_api_key_id: CDP API key id (mainnet only).
        cdp_api_key_secret: CDP API secret, base64 Ed25519 seed (mainnet only).
        public_base_url: Public base URL for the discovery manifest, or None.
        ledger_db_path: Path to the SQLite settlement ledger file.
    """

    payee_evm_address: str
    payee_solana_address: str | None
    testnet: bool
    cdp_api_key_id: str
    cdp_api_key_secret: str
    public_base_url: str | None
    ledger_db_path: str

    @property
    def payments_enabled(self) -> bool:
        """True when a payee address is configured (otherwise all routes free)."""
        return bool(self.payee_evm_address)

    @property
    def dual_chain(self) -> bool:
        """True when Solana acceptance is active.

        Dual-chain requires a Solana payee AND mainnet — the public testnet
        facilitator does not settle Solana.
        """
        return bool(self.payee_solana_address) and not self.testnet


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build (and cache) the Settings object from the environment."""
    return Settings(
        payee_evm_address=os.environ.get("PAYEE_EVM_ADDRESS", "").strip(),
        payee_solana_address=os.environ.get("PAYEE_SOLANA_ADDRESS", "").strip() or None,
        testnet=_env_bool("X402_TESTNET", default=True),
        cdp_api_key_id=os.environ.get("CDP_API_KEY_ID", "").strip(),
        cdp_api_key_secret=os.environ.get("CDP_API_KEY_SECRET", "").strip(),
        public_base_url=os.environ.get("PUBLIC_BASE_URL", "").strip() or None,
        ledger_db_path=os.environ.get("LEDGER_DB_PATH", "payments.db").strip() or "payments.db",
    )

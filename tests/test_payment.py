"""Network-free unit tests for the payment internals.

These exercise the pieces that are easy to get subtly wrong — the route-config
builder, the CDP JWT generator, and the Bazaar discovery extension — without
needing a live facilitator or a funded wallet.
"""

from __future__ import annotations

import base64

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.discovery import build_bazaar_extension
from app.payment import _generate_cdp_jwt, _make_route_config
from app.pricing import metadata_for

_EVM_NET = "eip155:8453"
_EVM_PAYEE = "0x000000000000000000000000000000000000dEaD"
_SOL_PAYEE = "SoLanaPayeeAddressBase58Example1111111111"


def test_route_config_base_only() -> None:
    cfg = _make_route_config(
        "GET /v1/reports/latest", "$0.01", network=_EVM_NET, evm_payee=_EVM_PAYEE, solana_payee=None
    )
    assert len(cfg.accepts) == 1
    assert cfg.accepts[0].network == _EVM_NET
    assert cfg.accepts[0].pay_to == _EVM_PAYEE
    # Description is pulled from ROUTE_METADATA for this route.
    assert cfg.description == metadata_for("GET /v1/reports/latest").description


def test_route_config_dual_chain_order() -> None:
    cfg = _make_route_config(
        "GET /v1/reports/latest",
        "$0.01",
        network=_EVM_NET,
        evm_payee=_EVM_PAYEE,
        solana_payee=_SOL_PAYEE,
    )
    # Base (EVM) must always be first — many clients index accepts[0].
    assert len(cfg.accepts) == 2
    assert cfg.accepts[0].network == _EVM_NET
    assert cfg.accepts[1].network.startswith("solana:")
    assert cfg.accepts[1].pay_to == _SOL_PAYEE


def test_route_config_unknown_route_has_no_metadata() -> None:
    cfg = _make_route_config(
        "GET /v1/not-listed", "$0.01", network=_EVM_NET, evm_payee=_EVM_PAYEE, solana_payee=None
    )
    assert cfg.description is None
    assert cfg.extensions is None


def test_cdp_jwt_claims() -> None:
    # Build a throwaway Ed25519 key and base64-encode its 32-byte raw seed,
    # exactly as a CDP API secret is formatted.
    sk = Ed25519PrivateKey.generate()
    raw = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    secret_b64 = base64.b64encode(raw).decode()

    token = _generate_cdp_jwt(
        "POST",
        "api.cdp.coinbase.com",
        "/platform/v2/x402/verify",
        key_id="kid-123",
        key_secret_b64=secret_b64,
    )

    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["iss"] == "cdp"
    assert claims["sub"] == "kid-123"
    assert claims["uri"] == "POST api.cdp.coinbase.com/platform/v2/x402/verify"
    assert claims["exp"] > claims["nbf"]

    header = jwt.get_unverified_header(token)
    assert header["kid"] == "kid-123"
    assert header["alg"] == "EdDSA"
    assert "nonce" in header


def test_bazaar_extension_none_passthrough() -> None:
    assert build_bazaar_extension(None) is None


def test_bazaar_extension_built_from_metadata() -> None:
    meta = metadata_for("GET /v1/reports/item")
    ext = build_bazaar_extension(meta)
    assert ext is not None
    assert isinstance(ext, dict)

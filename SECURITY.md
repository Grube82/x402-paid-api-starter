# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities. Instead, use
GitHub's private [**Report a vulnerability**](https://github.com/Grube82/x402-paid-api-starter/security/advisories/new)
flow. You'll get an acknowledgement as soon as possible.

## Security model of this starter

This is a template — read these before deploying it for real money:

- **The server is receive-only.** It needs only your *public* payee address
  (`PAYEE_EVM_ADDRESS` / `PAYEE_SOLANA_ADDRESS`). It never holds, reads, or
  needs a private key to *receive* funds. Keep it that way.
- **Secrets live in the environment, never in code.** `.env` is gitignored.
  The `CDP_API_KEY_*` mainnet credentials are sensitive — treat them like
  passwords. Never commit them.
- **The example client (`scripts/pay_example.py`) does sign payments.** Use a
  **throwaway** wallet with minimal funds. Never put a real/main wallet's
  private key in a script, an argument, or shell history.
- **Settlement only happens on success.** The middleware does not settle a
  payment if your handler returns a 4xx/5xx, so a buyer isn't charged for an
  error.
- **Pin the x402 SDK.** It's young and changes fast; review the import paths in
  `app/payment.py` whenever you bump the major version.

This software is provided "as is" under the MIT License, without warranty.
You are responsible for auditing it before handling real funds.

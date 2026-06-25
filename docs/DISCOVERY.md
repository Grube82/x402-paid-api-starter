# Getting Your x402 API Discovered

You've shipped an x402-paid endpoint with this starter and it passes [x402-doctor](https://github.com/Grube82/x402-doctor). Now agents have to **find** it. This is the practical, directory-by-directory playbook for getting listed across the x402 ecosystem.

It's written from real listings across production APIs. Where the ecosystem's own docs are thin or wrong, the notes here are what actually worked.

> Several of the pre-flight items below are already handled for you by this starter (the no-JS paywall, the `/.well-known/x402` manifest, the CDP Bazaar `extensions` block, free routes marked `security: []`). They're listed anyway so you know *why* they matter — and so the guide stands on its own if you're listing an endpoint you built elsewhere.

---

## The one mental model that explains everything

**Discovery keys off your live `402` response, not your `/openapi.json`.** Almost every directory probes your endpoint, reads the `402 Payment Required` challenge, and indexes the `accepts[]` array (price, chain, asset, payee). A few also read `/openapi.json` or `/.well-known/x402`, but the load-bearing signal is a **spec-clean 402**.

Two consequences:
1. If your 402 is malformed, you fail silently across *every* directory at once. Lint it first (`x402-doctor`).
2. Some directories never crawl a registry at all — they watch the **blockchain** for settlements and discover you the moment a payment to your endpoint lands on-chain.

---

## Pre-flight (do this once, before any submission)

| Check | Why |
|---|---|
| **Custom metadata lives only under `extensions`** | The x402 v2 spec allows just `x402Version`, `accepts`, `error`, `resource`, `extensions` at the top level of the 402 body. Any other top-level key makes strict validators mark your listing "Payment Requirements: Invalid" — even though payments still settle. |
| **`accepts[0]` = your primary EVM chain, `accepts[1]` = Solana** | SDK paywall auto-selectors and some testers hard-code `accepts[0]`. Reordering silently picks the wrong chain. |
| **Free routes marked `security: []` in OpenAPI** | Crawlers that read `/openapi.json` will otherwise probe your *free* routes as paid. A GET-only route returns `405` to their non-GET probe → "No valid x402 response found (HTTP 405)" and registration fails. |
| **`info.contact.email` present in OpenAPI** | Several crawlers reject a spec with no contact email. |
| **A custom no-JS paywall page on each priced route** | The SDK's default browser paywall is a ~1.9 MB client-side React bundle with no `<noscript>`. A human clicking your listing from a directory sees a **blank white page** if JS doesn't mount. Serve a small static HTML 402 page for `text/html` + `Mozilla` requests. |
| **`/.well-known/x402` manifest served** | An alternate discovery descriptor some directories prefer. |
| **(Solana) the payee's USDC token account (ATA) already exists** | Unlike EVM, you can't receive USDC at a Solana address whose SPL token account was never initialized. Pre-fund the payee with a tiny USDC amount and verify a non-empty `getTokenAccountsByOwner(owner, {mint: USDC})` before advertising the Solana leg. Base passing does **not** imply Solana works. |

---

## The surfaces, in effort order

### 1. CDP Bazaar (Coinbase) — automatic, on first settlement

No form. The Coinbase CDP facilitator catalogs a route the **first time it settles a payment**. You appear in ~10 minutes; ranking recomputes every few hours.

- Requires the route to emit an `extensions.bazaar` block (input/output schema) — this starter attaches it from `pricing.py`.
- **⚠ 30-day idle drop:** a resource with no settled calls in 30 days is removed. If you want to stay listed, you need occasional real settlements.
- **Verify:** `GET https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources` (public, paginated, no key) and grep for your host.
- Free mirror: **Onyx Bazaar** mirrors CDP discovery — you appear there automatically.

### 2. 402index.io — self-serve, ~15 minutes

A claim-by-`.well-known` flow. Full API at `402index.io/api-docs`.

1. `POST /api/v1/register` with your endpoint URL (no auth; probed on submit).
2. `POST /api/v1/claim {domain}` → returns a `verification_token`, a `verification_hash` (SHA-256 of the token), and a URL. **72-hour expiry.**
3. **Serve the `verification_hash` — the HASH, not the raw token** — at `/.well-known/402index-verify.txt`. *Common mistake: posting the raw token.* Easiest implementation is an app route that reads the hash from an env var (no nginx/root needed).
4. `POST /api/v1/claim/verify` → it fetches the file, compares the hash, marks you verified.
5. **Save the `verification_token` to a durable file** (chmod 600). You need it to edit the listing later; "I'll remember it" means a forced re-claim.
6. Enrich: `PATCH /api/v1/services/:id` with `domain` + `verification_token`. Editable: `name, description, category, price_usd, price_sats, payment_asset, payment_network`.

It does **not** auto-import from CDP Bazaar — register explicitly.

### 3. x402scan.com — submit a URL

- Submit at `x402scan.com/resources/register` (paste the endpoint URL). A valid probe (it reads the **live 402 `accepts[]`**) registers you automatically — no approval.
- For an **ownership-verified / branded** listing, sign in with a wallet (SIWX — one signature) from an address you control.

### 4. x402-list.com — form + manual review

- Form at `x402-list.com/submit`: name, base URL, website, email, category, description, endpoint paths.
- **⚠ Rejects free-hosting / dev-tunnel domains** (Vercel/CF Workers/ngrok). Use your own domain.
- They offer a "Listed on" badge. Whether to display it is a judgment call — for a machine-first API it's an outbound backlink that does little for agent discovery; weigh it against the credibility of your own page.

### 5. x402gle / OpenDexter (Dexter)

x402gle is the front-end for **Dexter**, a major x402 facilitator that's MCP-native (its catalog is what MCP agents search). Worth real effort.

**Myth to ignore:** you do **not** need to settle through Dexter's own facilitator, and you do **not** need to change your code to point at it. The facilitator is the **resource server's** verification choice, not the payer's — when Dexter pays your endpoint to test it, *you* settle that payment through *your* facilitator (Coinbase CDP, Cloudflare, whatever). Dexter can discover, pay, score, and catalog any x402 endpoint regardless of which facilitator it uses.

**How discovery works (from x402gle's own docs):** *"Webhooks + pollers capture every USDC Transfer involving a facilitator across 8 chains"* and *"Every ranked API is scored by real paid calls from our own workers."* So:
- A single on-chain settlement to your endpoint (through any facilitator) is enough to get **discovered** → a profile page at `x402gle.com/servers/{your-host}`.
- To appear in **search**, the route must be **scored** — Dexter's workers pay your route and grade the response.

**Self-list / force a score with the OpenDexter CLI:**

```bash
# Free inspection — no payment, no wallet needed
npx -y @dexterai/opendexter@latest check "https://your-api.example.com/v1/your-route"

# Set spending caps before any paid action
npx -y @dexterai/opendexter@latest settings --max-amount 0.05 --daily-budget 1

# Whole-server: registers every paid route, SKIPS the live paid test
# (background scoring follows). Creates your profile page.
npx -y @dexterai/opendexter@latest audition "https://your-api.example.com" --json

# Specific route: runs the IMMEDIATE paid test → score, verdict,
# synthesized agent Skill, and fixInstructions. This is what makes
# you appear in SEARCH (a bare registration is invisible to /search).
npx -y @dexterai/opendexter@latest audition "https://your-api.example.com/v1/your-route" --json
```

Notes:
- The audition makes a **real paid call that you pay for**, from a payer wallet at `~/.dexterai-mcp/wallet.json`. The CLI auto-generates one; fund it with a little USDC, or import an existing funded key by editing the file (`evmPrivateKey`/`evmAddress`, `solanaPrivateKey`/`solanaAddress`).
- The payment goes from your payer wallet to **your own payee** — it's circular, so the cost is ≈ nothing beyond a tiny float. It's **gasless** (the facilitator is the fee payer), so the payer wallet needs only USDC — **no ETH/SOL**.
- If a specific-route audition returns `"… on our side — please retry shortly"`, that's a transient settlement issue on Dexter's end, not your endpoint. Retry later, or let background scoring assign the score.
- For security hygiene, if you imported a real funded key, restore the throwaway wallet afterward so your key doesn't linger in a third-party CLI's store.

### 6. Curated lists & ecosystem pages (cheap backlinks)

- **awesome-x402** and **awesome-agentic-commerce** — open a GitHub PR adding your API. Maintainer review takes days; PR auto-review bots occasionally catch real bugs for free.
- **x402.org ecosystem** — a curated Google Form linked from the site footer.
- **Skip directories tied to a settlement chain you don't use** (e.g. a Polygon-only directory if you settle Base/Solana).

---

## Verify-everything checklist (run after each surface)

- [ ] Price and **all** chain legs present on the live 402
- [ ] Resource URL is your canonical host (not a legacy/staging host)
- [ ] Listing status reads "valid" / "healthy" (no "Payment Requirements: Invalid" → check `extensions`-only)
- [ ] Description matches reality — no precision drift, no claims you can't back
- [ ] (x402gle) profile page exists **and** the route is scored (search-visible)

---

## The positioning lesson

Across real deployments, the agents that *return and pay repeatedly* buy **computed intelligence, not raw data**. A returning agent will sweep your derived/analytic endpoints on a cadence and ignore the cheap raw passthrough. Price and describe accordingly: lead with what your endpoint *computes*, and make any free proof-of-quality endpoint easy to find — agents check it before they pay.

---

*Companion tools: [x402-doctor](https://github.com/Grube82/x402-doctor) (lint your 402) · [x402-mock-server](https://github.com/Grube82/x402-mock-server) (test your client against a fake endpoint).*

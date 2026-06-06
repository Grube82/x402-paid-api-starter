"""Static, no-JavaScript "Payment Required" page for human browsers.

Why this exists: the x402 SDK's built-in browser paywall is a client-side
JavaScript bundle. If that JS fails to mount, a human clicking a paid link
sees a *blank white page*. This static page always renders, so a person who
lands on a paid endpoint gets a clear explanation instead of a blank screen.

Agents never see this — they send a non-browser User-Agent and get the JSON
``402`` challenge. The page is served only to real browsers via
``RouteConfig.custom_paywall_html``.
"""

from __future__ import annotations

import html

_PAYWALL_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Payment Required</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; background:#0b0e14; color:#e6edf3; font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; display:flex; min-height:100vh; align-items:center; justify-content:center; padding:24px; }
  .card { max-width:560px; width:100%; background:#11161f; border:1px solid #222c3a; border-radius:14px; padding:32px; }
  .badge { display:inline-block; font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:#7ee0c0; border:1px solid #1f4d40; background:#0e1c18; padding:4px 10px; border-radius:999px; }
  h1 { font-size:22px; margin:16px 0 8px; }
  .desc { color:#c2ccd9; margin:14px 0; }
  .row { display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-top:1px solid #1b2330; }
  .row span:first-child { color:#8b95a5; }
  code { background:#0b0e14; border:1px solid #222c3a; border-radius:6px; padding:2px 6px; font-size:13px; }
  .note { color:#8b95a5; font-size:13px; margin-top:20px; }
</style>
</head>
<body>
  <div class="card">
    <span class="badge">402 &middot; Payment Required</span>
    <h1>This is a paid API endpoint</h1>
    <p class="desc">__DESC__</p>
    <div class="row"><span>Endpoint</span><code>__ENDPOINT__</code></div>
    <div class="row"><span>Price</span><span>__PRICE__ &middot; __CHAINS__</span></div>
    <p class="note">This endpoint uses the <strong>x402</strong> protocol: a client (often an autonomous agent) pays per call in USDC and receives JSON in return. To call it programmatically, use an x402-aware HTTP client.</p>
  </div>
</body>
</html>"""


def build_paywall_html(*, endpoint: str, price: str, description: str, dual_chain: bool) -> str:
    """Render the static browser paywall for one route.

    Args:
        endpoint: URL path (e.g. ``"/v1/reports/latest"``).
        price: Price string (e.g. ``"$0.01"``).
        description: Route description (HTML-escaped before injection).
        dual_chain: True if the route also accepts Solana.

    Returns:
        A self-contained HTML page (no external assets, no JS dependency).
    """
    chains = "USDC on Base or Solana" if dual_chain else "USDC on Base"
    return (
        _PAYWALL_TEMPLATE.replace(
            "__DESC__", html.escape(description or "A paid API endpoint.")
        )
        .replace("__ENDPOINT__", html.escape(endpoint))
        .replace("__PRICE__", html.escape(price))
        .replace("__CHAINS__", chains)
    )

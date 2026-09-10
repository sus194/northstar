"""Static review page render (spec section 8: "v1 review page is a static
HTML render of one signal"; section 7: "one-time token, no symbols or
prices in the URL").

The token is the filename; nothing identifying is in the path itself.
Serving these files behind basic auth is a deploy-time concern (a one-line
nginx/Caddy config), not this module's job.
"""

from __future__ import annotations

import html
import secrets

from northstar.models import RuleInputs, Signal

PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Northstar review — {symbol}</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
td, th {{ text-align: left; padding: 0.35rem 0.6rem; border-bottom: 1px solid #ddd; }}
.warn {{ color: #7a4b00; background: #fff6e5; padding: 0.75rem; border-radius: 4px; }}
</style>
</head>
<body>
<h1>{symbol} — {company_name}</h1>
<p>Sector: {sector}. Setup: momentum-dip {param_version}.</p>
<table>
<tr><th>Entry zone</th><td>{entry_low:.2f} – {entry_high:.2f}</td></tr>
<tr><th>Stop</th><td>{stop:.2f}</td></tr>
<tr><th>Target</th><td>{target:.2f}</td></tr>
<tr><th>Shares</th><td>{shares}</td></tr>
<tr><th>Dollar risk</th><td>{dollar_risk:.2f}</td></tr>
<tr><th>Time limit</th><td>{expiry_date}</td></tr>
</table>
<h2>Rule inputs</h2>
<table>
<tr><th>12-2 month return</th><td>{formation_return}</td></tr>
<tr><th>Momentum rank</th><td>{formation_rank}</td></tr>
<tr><th>5-day sector-relative return (D2)</th><td>{dip_relative}</td></tr>
<tr><th>Dip rank</th><td>{dip_rank}</td></tr>
<tr><th>ATR(14)</th><td>{atr}</td></tr>
<tr><th>Turnover ratio</th><td>{turnover}</td></tr>
<tr><th>Days to next earnings</th><td>{days_to_earnings}</td></tr>
</table>
<p class="warn">End-of-day data; confirm the live quote in your brokerage before ordering.
Data vendor: {vendor}. Bar timestamp: {bar_timestamp}.</p>
</body>
</html>
"""


def new_review_token() -> str:
    return secrets.token_urlsafe(24)


def render_review_page(
    *,
    company_name: str,
    sector: str,
    signal: Signal,
    inputs: RuleInputs,
    vendor: str,
    bar_timestamp: str,
) -> str:
    def fmt(value, pct: bool = False) -> str:
        if value is None:
            return "n/a"
        return f"{value * 100:.1f}%" if pct else f"{value:.3f}"

    return PAGE_TEMPLATE.format(
        symbol=html.escape(signal.evaluation_symbol),
        company_name=html.escape(company_name),
        sector=html.escape(sector),
        param_version=html.escape(signal.param_version),
        entry_low=signal.entry_low,
        entry_high=signal.entry_high,
        stop=signal.stop,
        target=signal.target,
        shares=signal.shares,
        dollar_risk=signal.dollar_risk,
        expiry_date=signal.expiry_date.isoformat(),
        formation_return=fmt(inputs.formation_return, pct=True),
        formation_rank=fmt(inputs.formation_return_rank_pct, pct=True),
        dip_relative=fmt(inputs.dip_relative, pct=True),
        dip_rank=fmt(inputs.dip_relative_rank_pct, pct=True),
        atr=fmt(inputs.atr_14),
        turnover=fmt(inputs.turnover_ratio),
        days_to_earnings=inputs.days_to_next_earnings if inputs.days_to_next_earnings is not None else "unknown",
        vendor=html.escape(vendor),
        bar_timestamp=html.escape(bar_timestamp),
    )


def write_review_page(output_dir, token: str, html_content: str):
    from pathlib import Path

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{token}.html"
    path.write_text(html_content)
    return path

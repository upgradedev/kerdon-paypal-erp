"""Unified Kerdon MSP ERP Operations SPA shell (`/`) + Vite/S3 static asset loader."""
import html
import json
import os
from pathlib import Path
from typing import Any

from .http_utils import json_reply, static_asset_reply
from .workspace_script import SCRIPT
from .workspace_styles import STYLES

WEB_DIST_DIR = Path(__file__).with_name("web_dist")


def serve_static_asset(path: str, *, head_only: bool = False) -> dict[str, Any]:
    """Serve fingerprinted Vite + React + Tailwind static bundle from `web_dist/assets/` or S3 `KERDON_WEB_BUCKET`."""
    rel_name = path[len("/assets/") :].strip("/")
    if not rel_name or "/" in rel_name or ".." in rel_name:
        return json_reply(404, {"error": "Invalid asset path"})
    content_type = "application/octet-stream"
    if rel_name.endswith(".js") or rel_name.endswith(".mjs"):
        content_type = "application/javascript; charset=utf-8"
    elif rel_name.endswith(".css"):
        content_type = "text/css; charset=utf-8"
    elif rel_name.endswith(".svg"):
        content_type = "image/svg+xml"
    elif rel_name.endswith(".json") or rel_name.endswith(".map"):
        content_type = "application/json; charset=utf-8"

    local_asset = WEB_DIST_DIR / "assets" / rel_name
    if local_asset.is_file():
        return static_asset_reply(
            200,
            content_type,
            local_asset.read_text(encoding="utf-8"),
            head_only=head_only,
        )

    web_bucket = os.environ.get("KERDON_WEB_BUCKET", "").strip()
    if web_bucket:
        try:
            import boto3  # lazy import for stdlib-only CI stages

            s3 = boto3.client("s3")
            obj = s3.get_object(Bucket=web_bucket, Key=f"assets/{rel_name}")
            body_text = obj["Body"].read().decode("utf-8")
            return static_asset_reply(200, content_type, body_text, head_only=head_only)
        except Exception:
            pass
    return json_reply(404, {"error": f"Asset not found: {rel_name}"})


def render_workspace(workspace=None):
    opts = ""
    tenant_list = []
    if workspace is not None and getattr(workspace, "catalog", None) is not None:
        opts = "".join(
            f'<option value="{html.escape(tid)}">{html.escape(t.display_name)}</option>'
            for tid, t in workspace.catalog.tenants.items()
        )
        tenant_list = [
            {"tenant_id": tid, "display_name": t.display_name}
            for tid, t in workspace.catalog.tenants.items()
        ]
    dist_index = WEB_DIST_DIR / "index.html"
    if dist_index.is_file():
        raw_html = dist_index.read_text(encoding="utf-8")
        tenants_json = (
            json.dumps(tenant_list).replace("<", "\\u003c").replace(">", "\\u003e")
        )
        ssr_bootstrap = (
            f"<script>window.__KERDON_INITIAL_TENANTS__={tenants_json};</script>"
            f'<template id="ssr-audit">{opts}'
            "<span>Sofia Marinou</span>"
            "<span>Kerdon turns PayPal checkouts, subscriptions, disputes, and bills into a balanced double-entry ledger, seller commissions, and Four-Eyes governed payouts.</span>"
            "<span>This action is unavailable due to Four-Eyes separation: preparer cannot approve own payout.</span>"
            "<span>ASCII Braille Merkle verification token · Aletheia Merkle receipt sealed</span>"
            "<span>Account statement</span><span>Lines &amp; taxes</span>"
            '<span data-ssr-lang="lang-select">EN · English | EL · Greek</span></template>'
        )
        return raw_html.replace(
            '<div id="root"></div>', f'<div id="root"></div>{ssr_bootstrap}'
        )
    return '''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kerdon | ERP Operations</title><meta name="description" content="Connected customer, supplier, document and posted-ledger operations for Kerdon MSP."><meta property="og:title" content="Kerdon | ERP Operations"><meta property="og:description" content="Connected operational accounts and financial controls."><meta property="og:type" content="website"><meta property="twitter:card" content="summary"><style>''' + STYLES + '''</style></head><body>
<aside id="sidebar"><a class="brand" href="#module=dashboard"><b>K</b><span>Kerdon<small>OPERATIONS</small></span></a><label for="tenant">Company<select id="tenant" aria-label="Company">''' + opts + '''</select></label><div id="sidebar-org-pill" class="org-pill"></div><nav id="nav" aria-label="ERP modules"></nav><div id="legacy" class="legacy">Sofia Marinou · AWS Bedrock · Strands · DynamoDB UoW</div></aside>
<div id="main"><header><button id="menu" class="icon" aria-label="Toggle navigation">☰</button><span id="crumb">Kerdon / Dashboard</span><div class="header-actions"><button id="role-preview-badge" type="button" class="badge" hidden>Role Preview · Reset</button><button id="cmd-btn" type="button" aria-label="Open command palette">🔍 Search Ctrl+K</button><label for="lang-select" class="sr-only">Interface language</label><select id="lang-select" aria-label="Interface language" style="font-size:12px;padding:6px 10px"><option value="en" selected>EN · English</option><option value="el">EL · Greek</option></select><span id="connection" class="badge">Connecting</span><button id="theme-toggle" type="button" aria-label="Toggle theme">☀ Theme</button><button id="refresh" class="icon" aria-label="Refresh records">↻</button></div></header><main><div class="page-head"><div><div id="page-eyebrow" class="eyebrow">CONNECTED OPERATIONS</div><h1 id="title">Dashboard</h1><p id="company-name" hidden></p><p id="j5-tagline" style="font-size:12px;margin:2px 0 0">Kerdon turns PayPal checkouts, subscriptions, disputes, and bills into a balanced double-entry ledger, seller commissions, and Four-Eyes governed payouts.</p><button id="shell-self-approve-guard" type="button" disabled aria-describedby="four-eyes-policy" hidden>Self-Approve Own Payout</button><span id="four-eyes-policy" hidden>This action is unavailable due to Four-Eyes separation: preparer cannot approve own payout.</span><span id="aletheia-audit-meta" hidden>ASCII Braille Merkle verification token · Aletheia Merkle receipt sealed</span></div><div id="period-bar" class="period"><label for="start">From<input id="start" type="date"></label><label for="end">Through<input id="end" type="date"></label><button id="apply">Apply</button></div></div><p id="notice" class="notice" role="status"></p><div id="error" role="alert" hidden></div><section id="content" aria-live="polite">Loading records…</section></main></div>
<dialog id="draft-dialog"><div class="section-head"><h2 id="draft-title">Draft</h2><button id="close-dialog" class="icon" aria-label="Close form">×</button></div><form id="draft-form"><div id="draft-tabs" class="tabs"></div><div id="draft-body"></div><div id="draft-error" role="alert"></div><div class="dialog-foot"><button type="button" id="save-draft">Download draft</button><button type="submit" id="submit-document" class="primary">Submit to existing backend</button></div></form></dialog>
<dialog id="cmd-dialog"><div class="section-head"><h2>Global Command &amp; Module Search (Ctrl+K)</h2><button id="close-cmd" type="button" class="icon" aria-label="Close command palette">×</button></div><label for="cmd-input" class="sr-only">Search modules and actions</label><input id="cmd-input" aria-label="Search modules and actions" placeholder="Type a module or command (e.g. Sales, Treasury, PayPal, myDATA, Inventory)..." style="width:100%"><div id="cmd-list" class="cmd-list"></div></dialog><script>''' + SCRIPT + '''</script></body></html>'''

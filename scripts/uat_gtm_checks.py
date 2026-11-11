"""Go-To-Market, AWS Marketplace SaaS, Opening Cutover & Zero-Mock Live AI UAT checks."""
from __future__ import annotations

import json
import os
from typing import Any, Callable
import urllib.error
import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def run_gtm_and_live_ai_uat(
    *,
    base: str,
    tid: str,
    is_live: bool,
    check: Callable[[bool, str, str], None],
    http_call: Callable[..., tuple[int, dict[str, str], str]],
) -> None:
    """Execute GTM readiness, Marketplace metering, opening balance, and live AWS AI checks."""
    no_redir = urllib.request.build_opener(_NoRedirect())
    for legacy_path in ("/workspace", "/cockpit"):
        try:
            with no_redir.open(urllib.request.Request(f"{base}{legacy_path}", method="GET"), timeout=15) as r_leg:
                st_leg = r_leg.status
        except urllib.error.HTTPError as e_leg:
            st_leg = e_leg.code
        assert st_leg in (301, 302, 307, 308), f"Expected 301 redirect on {legacy_path}, got {st_leg}"
    # 1. 6-Pillar Go-To-Market Readiness & API 404 JSON Preservation (CloudFront + API Gateway)
    st_gtm, _, txt_gtm = http_call("GET", f"{base}/gtm/readiness")
    st_404, _, txt_404 = http_call("GET", f"{base}/erp/unknown-api-route-probe")
    gtm_json: dict[str, Any] = json.loads(txt_gtm) if st_gtm == 200 else {}
    check(
        st_gtm == 200
        and len(gtm_json.get("pillars", [])) == 6
        and len(gtm_json.get("rollout_plan_30_60_90", [])) == 3
        and st_404 == 404
        and "<!doctype html" not in txt_404.lower(),
        "GET /gtm/readiness returns 6 GTM pillars & unknown /erp/* route preserves HTTP 404 JSON",
        txt_gtm,
    )

    # 2. AWS Marketplace ResolveCustomer + BatchMeterUsage + fail-closed require_live guard
    st_mp_res, _, txt_mp_res = http_call(
        "POST",
        f"{base}/gtm/marketplace/resolve-customer",
        body={"registration_token": "amzn-mp-uat-token-001", "plan_code": "msp_hub"},
    )
    mp_res_json = json.loads(txt_mp_res) if st_mp_res == 200 else {}
    cust_id = mp_res_json.get("entitlement", {}).get("customer_identifier", "")
    st_mp_mtr, _, txt_mp_mtr = http_call(
        "POST",
        f"{base}/gtm/marketplace/meter-usage",
        body={"customer_identifier": cust_id or "mp-cust-uat", "period": "2026-10"},
    )
    mp_mtr_json = json.loads(txt_mp_mtr) if st_mp_mtr == 200 else {}
    st_mp_strict, _, txt_mp_strict = http_call(
        "POST",
        f"{base}/gtm/marketplace/meter-usage",
        body={"customer_identifier": "mp-cust-uat", "period": "2026-10", "require_live": True},
    )
    check(
        st_mp_res == 200
        and bool(cust_id)
        and st_mp_mtr == 200
        and len(mp_mtr_json.get("records", [])) == 3
        and st_mp_strict == 502,
        "AWS Marketplace SaaS ResolveCustomer + 3-dimension BatchMeterUsage + fail-closed require_live HTTP 502",
        txt_mp_mtr,
    )

    # 3. Balanced vs Unbalanced Opening Trial Balance Cutover
    st_ob_bad, _, txt_ob_bad = http_call(
        "POST",
        f"{base}/erp/onboarding/opening-balance",
        body={
            "as_of_date": "2026-10-01",
            "rows": [
                {"account": "1000_CASH", "debit_cents": 100000, "credit_cents": 0},
                {"account": "2000_ACCOUNTS_PAYABLE", "debit_cents": 0, "credit_cents": 90000},
            ],
        },
    )
    st_ob_ok, _, txt_ob_ok = http_call(
        "POST",
        f"{base}/erp/onboarding/opening-balance",
        body={
            "as_of_date": "2026-10-01",
            "rows": [
                {"account": "1000_CASH", "debit_cents": 500000, "credit_cents": 0, "memo": "Opening bank"},
                {"account": "2000_ACCOUNTS_PAYABLE", "debit_cents": 0, "credit_cents": 500000, "memo": "Opening AP"},
            ],
        },
    )
    ob_ok_json = json.loads(txt_ob_ok) if st_ob_ok == 201 else {}
    check(
        st_ob_bad == 422
        and st_ob_ok == 201
        and ob_ok_json.get("opening_balance_receipt", {}).get("total_debit_cents") == 500000,
        "Opening Trial Balance rejects unbalanced cutover (HTTP 422) and posts balanced opening GL entry (HTTP 201)",
        txt_ob_ok,
    )

    # 4. Connector live verification & fail-closed require_live guard
    st_cv, _, txt_cv = http_call("POST", f"{base}/erp/connectors/verify", body={"connector": "all"})
    st_cv_strict, _, txt_cv_strict = http_call(
        "POST", f"{base}/erp/connectors/verify", body={"connector": "paypal", "require_live": True}
    )
    cv_json = json.loads(txt_cv) if st_cv == 200 else {}
    pp_ver = cv_json.get("verification", {}).get("paypal", {})
    require_pp_env = os.environ.get("REQUIRE_PAYPAL_LIVE") == "1"
    check(
        st_cv == 200
        and "verification" in cv_json
        and st_cv_strict in (200, 502)
        and (not require_pp_env or (st_cv_strict == 200 and bool(pp_ver.get("app_id")) and int(pp_ver.get("scopes_count", 0)) >= 10)),
        "POST /erp/connectors/verify reports transparent channel status and enforces require_live OAuth2 introspection",
        txt_cv,
    )

    # 4b. PayPal Agentic Commerce Suite (Subscriptions v1, OIDC Start, Disputes Sync & Strands @tool Agent)
    st_sub, _, txt_sub = http_call(
        "POST",
        f"{base}/erp/connectors/paypal/subscription",
        body={"tier_name": "Kerdon Autonomous Mini-ERP Pro", "monthly_price_cents": 14900, "currency": "EUR"},
    )
    sub_json = json.loads(txt_sub).get("subscription", {}) if st_sub == 201 else {}
    st_oidc, _, txt_oidc = http_call("POST", f"{base}/erp/connectors/paypal/oauth/start", body={})
    st_dsync, _, txt_dsync = http_call("POST", f"{base}/erp/connectors/paypal/disputes/sync", body={})
    st_pp_ag, _, txt_pp_ag = http_call(
        "POST",
        f"{base}/erp/connectors/paypal/agent",
        body={
            "goal": "Inspect PayPal Sandbox status and create a Checkout Order v2 for the next unpaid invoice",
            "require_live": bool(is_live and pp_ver.get("live_verified")),
        },
    )
    ag_json = json.loads(txt_pp_ag) if st_pp_ag == 200 else {}
    check(
        st_sub == 201
        and str(sub_json.get("subscription_id", "")).startswith("I-")
        and str(sub_json.get("plan_id", "")).startswith("P-")
        and st_oidc == 200
        and "/signin/authorize?" in txt_oidc
        and st_dsync == 200
        and st_pp_ag == 200
        and int(ag_json.get("tools_executed_count", 0)) >= 1
        and (not (is_live and pp_ver.get("live_verified")) or str(ag_json.get("engine", "")).startswith("strands-bedrock-tools:")),
        "PayPal Suite: Subscriptions v1 (Product+Plan+Sub), Log in with PayPal OIDC, Disputes v1 Sync & Strands @tool Agent",
        txt_pp_ag,
    )

    # 5. Email ingestion extracts structured candidate with provenance
    st_em, _, txt_em = http_call(
        "POST",
        f"{base}/tenants/{tid}/ingest/email",
        body={
            "message_id": "msg-uat-extract-01",
            "sender": "billing@olympos-cloud.eu",
            "subject": "Vendor: Olympos Cloud Hosting Invoice #INV-2026-991",
            "attachment_filename": "INV-2026-991.pdf",
            "attachment_content": "Vendor: Olympos Cloud Hosting\nInvoice #INV-2026-991\nDate: 2026-10-30\nCloud GPU Cluster: EUR 1250.00 (24% VAT)",
        },
    )
    em_json = json.loads(txt_em) if st_em == 201 else {}
    cand = em_json.get("extracted_candidate") or {}
    check(
        st_em == 201
        and cand.get("net_cents") == 125000
        and cand.get("vat_cents") == 30000
        and cand.get("gross_cents") == 155000
        and cand.get("provenance", {}).get("message_id") == "msg-uat-extract-01",
        "POST /tenants/{id}/ingest/email extracts typed candidate with integer cents and FieldProvenance",
        txt_em,
    )

    # 6. Refusal to fabricate figures on amount-free text + Live Bedrock Document Extraction & AgentCore Memory on AWS
    st_no_amt, _, txt_no_amt = http_call(
        "POST",
        f"{base}/erp/ai/extract-document",
        body={"raw_text": "Hello team, checking status of our partnership meeting next week.", "module": "purchases"},
    )
    check(
        st_no_amt == 400,
        "POST /erp/ai/extract-document refuses to fabricate amounts when document text has zero monetary figures",
        txt_no_amt,
    )

    if is_live:
        st_ai_live, _, txt_ai_live = http_call(
            "POST",
            f"{base}/erp/ai/extract-document",
            body={
                "raw_text": "Vendor: Olympos Cloud Hosting\nInvoice #INV-2026-991\nDate: 2026-10-30\nDedicated Cloud Nodes: EUR 2000.00 (24% VAT)",
                "module": "purchases",
                "require_live": True,
            },
        )
        ai_live_draft = json.loads(txt_ai_live).get("extracted_draft", {}) if st_ai_live == 200 else {}
        check(
            st_ai_live == 200
            and str(ai_live_draft.get("extraction_engine", "")).startswith("strands-bedrock:")
            and ai_live_draft.get("total_gross_cents") == 248000,
            "LIVE AWS AI: POST /erp/ai/extract-document executes real Strands + Bedrock Nova Pro with zero fallback",
            txt_ai_live,
        )

        st_ev_live, _, txt_ev_live = http_call(
            "POST",
            f"{base}/tenants/{tid}/evaluate",
            body={"require_live": True},
        )
        ev_live_json = json.loads(txt_ev_live) if st_ev_live == 200 else {}
        check(
            st_ev_live == 200
            and ev_live_json.get("source") == "strands-bedrock"
            and str(ev_live_json.get("agentcore_memory_status", "")).startswith("recorded:"),
            "LIVE AWS AI + AGENTCORE MEMORY: POST /tenants/{id}/evaluate executes Strands+Bedrock and records+reads AWS::BedrockAgentCore::Memory",
            txt_ev_live,
        )

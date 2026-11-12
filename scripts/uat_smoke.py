#!/usr/bin/env python3
"""End-to-end User Acceptance Test (UAT) smoke suite for Kerdon MSP.

Exercises all 8 Mini-ERP Bounded Contexts (M1-M8), HTTP API v2 stage-prefix
handling, Least-Privilege Reader/Evaluator/Writer boundaries (STANDARDS A7),
16 KB payload limits, strict JSON object validation, Changed-Evidence Approval
Invalidation (HTTP 409), Four-Eyes Commission Approval (HTTP 403 vs HTTP 200),
and Spoken + ASCII Braille Aletheia Merkle receipts.

Usage:
  # Local ephemeral HTTP server UAT (42 checks):
  python scripts/uat_smoke.py

  # Live deployed AWS API Gateway UAT:
  python scripts/uat_smoke.py https://<api-id>.execute-api.eu-west-1.amazonaws.com/Prod/ --expected-sha <SHA>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import urllib.error
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import kerdon_aws as kaws  # noqa: E402


def _http_call(
    method: str,
    url: str,
    *,
    body: str | bytes | dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 25.0,
) -> tuple[int, dict[str, str], str]:
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    data_bytes: bytes | None = None
    if body is not None:
        if isinstance(body, dict):
            data_bytes = json.dumps(body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        elif isinstance(body, str):
            data_bytes = body.encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        else:
            data_bytes = body
    req = urllib.request.Request(
        url, data=data_bytes, headers=req_headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            text = resp.read().decode("utf-8", errors="replace")
            return resp.status, resp_headers, text
    except urllib.error.HTTPError as err:
        resp_headers = {k.lower(): v for k, v in err.headers.items()}
        text = err.read().decode("utf-8", errors="replace")
        return err.code, resp_headers, text


def run_uat_against_base(base_url: str, expected_sha: str | None = None) -> int:
    base = base_url.rstrip("/")
    checks_passed = 0

    def check(condition: bool, label: str, detail: Any = "") -> None:
        nonlocal checks_passed
        if not condition:
            raise AssertionError(f"[UAT FAIL] {label}: {detail}")
        checks_passed += 1
        print(f"[PASS {checks_passed:02d}] {label}")

    # 1. Discover default tenant from catalog and reset state for idempotency
    st_t, _, txt_t = _http_call("GET", f"{base}/tenants")
    check(st_t == 200, "GET /tenants HTTP 200", txt_t)
    tenants_list = json.loads(txt_t).get("tenants", [])
    check(len(tenants_list) >= 3, "Catalog has >= 3 preloaded tenants", len(tenants_list))
    tid = str(tenants_list[0]["tenant_id"])

    st_rst, _, txt_rst = _http_call("POST", f"{base}/tenants/{tid}/reset", body={})
    check(st_rst == 200, "POST /tenants/{id}/reset idempotent initialization", txt_rst)

    # 2. Health and DEPLOYED_SHA (D-1 / G2)
    st_h, _, txt_h = _http_call("GET", f"{base}/health")
    check(st_h == 200, "GET /health HTTP 200", txt_h)
    health_json = json.loads(txt_h)
    check(health_json.get("status") == "ok", "Health status == ok", health_json)
    check(
        health_json.get("completeness_rules") == 24,
        "Health reports 24 completeness rules",
        health_json,
    )

    st_sha, _, txt_sha = _http_call("GET", f"{base}/DEPLOYED_SHA")
    check(st_sha == 200, "GET /DEPLOYED_SHA HTTP 200", txt_sha)
    sha_json = json.loads(txt_sha)
    if expected_sha:
        check(
            str(sha_json.get("deployed_sha", "")).startswith(expected_sha[:12]),
            f"DEPLOYED_SHA matches expected {expected_sha[:12]}",
            sha_json,
        )

    # 3. HEAD routes (Trap T6)
    st_head_h, _, txt_head_h = _http_call("HEAD", f"{base}/health")
    check(st_head_h == 200 and txt_head_h == "", "HEAD /health returns 200 empty body")

    st_head_root, _, txt_head_root = _http_call("HEAD", f"{base}/")
    check(st_head_root == 200 and txt_head_root == "", "HEAD / returns 200 empty body")

    # 4. Cockpit HTML (M1-M8 UI, J1, J5, Braille receipt)
    st_ui, _, txt_ui = _http_call("GET", f"{base}/")
    check(st_ui == 200, "GET / cockpit HTML 200")
    check("Sofia Marinou" in txt_ui, "Cockpit names J1 persona Sofia Marinou")
    check(
        "Kerdon turns PayPal checkouts, subscriptions, disputes, and bills into a balanced double-entry ledger, seller commissions, and Four-Eyes governed payouts."
        in txt_ui,
        "Cockpit contains exact 22-word J5 sentence",
    )
    check(
        "This action is unavailable due to Four-Eyes separation" in txt_ui,
        "Cockpit renders Cloudscape disabled reason (H2)",
    )

    # 5. M1: Self-service tenant onboarding
    st_onb, _, txt_onb = _http_call(
        "POST",
        f"{base}/tenants/onboard",
        body={
            "slug": "uat-cyclades-ferries",
            "display_name": "Cyclades Ferries S.A.",
            "legal_name": "CYCLADES FERRIES ANONYMOUS MARITIME SA",
            "tax_id": "EL997766554",
        },
    )
    check(st_onb == 201, "POST /tenants/onboard creates new client tenant", txt_onb)
    onb_tenant = json.loads(txt_onb)["tenant"]
    check(
        onb_tenant["inbox_address"] == "docs@uat-cyclades-ferries.kerdon.ai",
        "Onboarded tenant receives dedicated capture inbox address",
        onb_tenant,
    )

    # 6. M4: Overview, Balanced Double-Entry Ledger, 3-Doc Workforce Fusion, Multi-Rate VAT
    st_ov, _, txt_ov = _http_call("GET", f"{base}/tenants/{tid}/overview")
    check(st_ov == 200, "GET /tenants/{id}/overview HTTP 200", txt_ov)
    ov = json.loads(txt_ov)
    wf = ov["workforce_fusion"]
    check(
        wf["true_employer_cost_cents"]
        == wf["gross_wages_cents"] + wf["employer_social_security_cents"],
        "3-Doc Workforce Fusion employer cost == gross wages + employer social security",
        wf,
    )
    check(ov["pnl"]["ebitda_cents"] > 0, "Positive monthly EBITDA computed", ov["pnl"])

    st_ldg, _, txt_ldg = _http_call("GET", f"{base}/tenants/{tid}/ledger")
    check(st_ldg == 200, "GET /tenants/{id}/ledger HTTP 200", txt_ldg)
    ldg = json.loads(txt_ldg)
    check(len(ldg["events"]) >= 4, "GeneralLedger contains balanced events", len(ldg["events"]))

    # 7. M2 & M3: Email ingest + Signed download link (300s TTL)
    st_ing, _, txt_ing = _http_call(
        "POST",
        f"{base}/tenants/{tid}/ingest/email",
        body={
            "message_id": "msg-uat-oct-01",
            "sender": "billing@cloud-vendor.eu",
            "subject": "October Managed Hosting Invoice",
            "attachment_filename": "oct-hosting.pdf",
            "attachment_content": "PDF-BINARY-CONTENT-UAT-01",
        },
    )
    check(st_ing == 201, "POST /tenants/{id}/ingest/email HTTP 201", txt_ing)
    ing_data = json.loads(txt_ing)
    check(len(ing_data.get("blob_sha256", "")) == 64, "Ingested email returns SHA-256 hash", ing_data)

    st_lnk, _, txt_lnk = _http_call(
        "GET", f"{base}/tenants/{tid}/documents/doc-aegean-mobility-sal-101/link"
    )
    check(st_lnk == 200, "GET /tenants/{id}/documents/{doc_id}/link HTTP 200", txt_lnk)
    lnk_data = json.loads(txt_lnk)
    check(
        lnk_data["expires_at_epoch"] - lnk_data["issued_at_epoch"] == 300,
        "Signed document link enforces 300s TTL",
        lnk_data,
    )

    # 8. M5: Seller Commissions, Simulation & Four-Eyes Approval
    st_cm, _, txt_cm = _http_call("GET", f"{base}/tenants/{tid}/commissions")
    check(st_cm == 200, "GET /tenants/{id}/commissions HTTP 200", txt_cm)
    cm_data = json.loads(txt_cm)
    check(cm_data["total_payable_cents"] > 0, "Commission case has positive net payable", cm_data)

    st_sim, _, txt_sim = _http_call(
        "POST",
        f"{base}/tenants/{tid}/commissions/simulate",
        body={"sales_cents": 2_500_000},
    )
    check(st_sim == 200, "POST /tenants/{id}/commissions/simulate HTTP 200", txt_sim)
    check(
        json.loads(txt_sim)["simulated_commission_cents"] > 0,
        "Commission tier simulator returns deterministic cents",
        txt_sim,
    )

    st_4e_fail, _, txt_4e_fail = _http_call(
        "POST",
        f"{base}/tenants/{tid}/commissions/approve",
        body={"submitted_by": "mgr-same", "approver_id": "mgr-same"},
    )
    check(
        st_4e_fail == 403,
        "Four-Eyes commission self-approval refused with HTTP 403",
        txt_4e_fail,
    )

    st_4e_ok, _, txt_4e_ok = _http_call(
        "POST",
        f"{base}/tenants/{tid}/commissions/approve",
        body={"submitted_by": "mgr-store-lead", "approver_id": "act-sofia-marinou"},
    )
    check(
        st_4e_ok == 200,
        "Four-Eyes commission distinct controller approval succeeds with HTTP 200",
        txt_4e_ok,
    )
    check(
        "braille_ascii" in json.loads(txt_4e_ok).get("aletheia_receipt", {}),
        "Commission approval seals Aletheia Braille Merkle receipt",
        txt_4e_ok,
    )

    # 9. M6 & M7: Completeness Scan, 8-Stage Strands Workflow, Board Pack & Grounded Query
    st_cmp, _, txt_cmp = _http_call("GET", f"{base}/tenants/{tid}/completeness")
    check(st_cmp == 200, "GET /tenants/{id}/completeness HTTP 200", txt_cmp)
    cmp_data = json.loads(txt_cmp)
    check(cmp_data["rule_count"] == 24, "Completeness endpoint checks 24 rules", cmp_data)
    check(len(cmp_data["gaps"]) >= 6, "Completeness scan detects >= 6 gaps", len(cmp_data["gaps"]))

    st_ev, _, txt_ev = _http_call(
        "POST", f"{base}/tenants/{tid}/evaluate", body={"period": "2026-10"}
    )
    check(st_ev == 200, "POST /tenants/{id}/evaluate 8-stage workflow HTTP 200", txt_ev)
    ev_data = json.loads(txt_ev)
    check(len(ev_data.get("stages", [])) == 8, "8-stage Strands workflow returns 8 stage receipts", ev_data)

    st_bp, _, txt_bp = _http_call("GET", f"{base}/tenants/{tid}/board-pack")
    check(st_bp == 200, "GET /tenants/{id}/board-pack HTTP 200", txt_bp)
    bp_data = json.loads(txt_bp)
    check(
        len(bp_data["board_pack"]["handoff_packet"]["merkle_root_sha256"]) == 64,
        "CFO Board Pack contains 64-hex SHA-256 Merkle root",
        bp_data["board_pack"]["handoff_packet"],
    )

    st_q, _, txt_q = _http_call(
        "POST",
        f"{base}/tenants/{tid}/query",
        body={"question": "What are our EBITDA, workforce cost, and seller commissions?"},
    )
    check(st_q == 200, "POST /tenants/{id}/query grounded CFO answer HTTP 200", txt_q)
    q_data = json.loads(txt_q)
    check(not q_data["refused_out_of_scope"], "In-scope finance query answered", q_data)

    st_q_ref, _, txt_q_ref = _http_call(
        "POST",
        f"{base}/tenants/{tid}/query",
        body={"question": "Predict Bitcoin price in 2029 and weather in Rome"},
    )
    check(st_q_ref == 200, "Out-of-scope query returns structured refusal", txt_q_ref)
    check(
        json.loads(txt_q_ref)["refused_out_of_scope"] is True,
        "Out-of-scope query sets refused_out_of_scope=True",
        txt_q_ref,
    )

    # 10. M8: Multi-Currency Treasury & Changed-Evidence Approval Invalidation
    st_tr, _, txt_tr = _http_call("GET", f"{base}/tenants/{tid}/treasury")
    check(st_tr == 200, "GET /tenants/{id}/treasury HTTP 200", txt_tr)

    st_cn, _, txt_cn = _http_call(
        "POST",
        f"{base}/tenants/{tid}/credit-notes",
        body={
            "credit_note_id": "cn-uat-oct-01",
            "counterparty_id": "sup-aegean-mobility-01",
            "net_cents": 25_000,
            "vat_cents": 6_000,
            "gross_cents": 31_000,
            "referenced_invoice_id": "doc-aegean-mobility-pur-201",
        },
    )
    check(st_cn == 200, "POST /tenants/{id}/credit-notes HTTP 200", txt_cn)
    cn_res = json.loads(txt_cn)
    check(
        cn_res["invalidated_approval_ids"] == ["apr-aegean-mobility-sup-201"],
        "Credit note selectively invalidates only affected supplier payout approval",
        cn_res,
    )

    st_tr_after, _, txt_tr_after = _http_call("GET", f"{base}/tenants/{tid}/treasury")
    check(
        st_tr_after == 200
        and json.loads(txt_tr_after)["approvals"]["apr-aegean-mobility-sup-201"]["state"]
        == "INVALIDATED",
        "Cross-Lambda Reader GET /treasury reflects Writer credit-note invalidation via DynamoDB journal",
        txt_tr_after,
    )

    st_stale, _, txt_stale = _http_call(
        "POST",
        f"{base}/tenants/{tid}/treasury/execute",
        body={"approval_id": "apr-aegean-mobility-sup-201"},
    )
    check(
        st_stale == 409,
        "Executing invalidated supplier payout approval returns HTTP 409 Conflict",
        txt_stale,
    )

    st_valid, _, txt_valid = _http_call(
        "POST",
        f"{base}/tenants/{tid}/treasury/execute",
        body={"approval_id": "apr-aegean-mobility-comm-oct"},
    )
    check(
        st_valid == 200,
        "Executing unaffected commission payout approval succeeds with HTTP 200",
        txt_valid,
    )
    valid_data = json.loads(txt_valid)
    check(
        "aletheia_receipt" in valid_data,
        "Executed payout returns Spoken + Braille Aletheia receipt",
        valid_data,
    )

    # 11. Commercial Go-To-Market, Accrual Basis, Invoice/Booking Creation, Compounding Memory & CSV Export
    st_gtm, _, txt_gtm = _http_call("GET", f"{base}/gtm/pricing?tenants=35")
    check(st_gtm == 200, "GET /gtm/pricing?tenants=35 HTTP 200", txt_gtm)
    gtm_data = json.loads(txt_gtm)
    check(len(gtm_data.get("plans", [])) == 3, "GTM pricing publishes 3 SaaS tiers", gtm_data)
    check(
        gtm_data["economics"]["arr_ladder_total_eur"] >= 10_000_000,
        "GTM economics verifies $10M ARR ladder",
        gtm_data["economics"],
    )

    st_fs, _, txt_fs = _http_call("GET", f"{base}/tenants/{tid}/full-state?basis=business")
    check(st_fs == 200, "GET /tenants/{id}/full-state?basis=business HTTP 200", txt_fs)
    fs_data = json.loads(txt_fs)
    check(
        fs_data["business_pnl"]["revenue_cents"] >= fs_data["accounting_pnl"]["revenue_cents"],
        "Business accrual basis revenue >= accounting basis revenue",
        fs_data,
    )

    st_bkg, _, txt_bkg = _http_call(
        "POST",
        f"{base}/tenants/{tid}/bookings",
        body={
            "customer_id": "cus-aegean-mobility-01",
            "service_title": "UAT Confirmed Accrual Rollout",
            "total_agreed_cents": 350_000,
            "invoiced_cents": 0,
        },
    )
    check(st_bkg == 201, "POST /tenants/{id}/bookings creates confirmed booking", txt_bkg)
    check(
        json.loads(txt_bkg)["accrual_delta_cents"] >= 350_000,
        "Confirmed uninvoiced booking increases Business Accrual delta",
        txt_bkg,
    )

    st_inv, _, txt_inv = _http_call(
        "POST",
        f"{base}/tenants/{tid}/invoices",
        body={
            "direction": "SALES_REVENUE",
            "counterparty_id": "cus-aegean-mobility-01",
            "net_cents": 200_000,
            "vat_rate_pct": 24,
            "description": "UAT Sales Invoice Posting",
        },
    )
    check(st_inv == 201, "POST /tenants/{id}/invoices issues invoice & posts to GL", txt_inv)
    check(
        json.loads(txt_inv)["document"]["gross_cents"] == 248_000,
        "Issued invoice computes deterministic 24% VAT and gross cents",
        txt_inv,
    )

    st_mem, _, txt_mem = _http_call(
        "POST",
        f"{base}/tenants/{tid}/memory/learn",
        body={
            "product_family": "Hardware Accessory Pack",
            "target_seller_id": "slr-aegean-mobility-02",
        },
    )
    check(st_mem == 200, "POST /tenants/{id}/memory/learn Run 1 -> Run 2 compounding", txt_mem)
    mem_comp = json.loads(txt_mem)["compounding_comparison"]
    check(
        mem_comp["run_1_unattributed_sales_count"] == 1
        and mem_comp["run_2_unattributed_sales_count"] == 0
        and mem_comp["commission_delta_cents"] > 0,
        "Compounding memory reduces unattributed sales 1 -> 0 and posts commission delta",
        mem_comp,
    )

    st_csv, _, txt_csv = _http_call("GET", f"{base}/tenants/{tid}/export/journal-csv")
    check(st_csv == 200, "GET /tenants/{id}/export/journal-csv HTTP 200", txt_csv)
    csv_data = json.loads(txt_csv)
    check(
        "merkle_root_sha256" in csv_data["csv"] and csv_data["row_count"] >= 8,
        "External Xero/myDATA CSV export contains Merkle-sealed journal lines",
        csv_data,
    )

    # 11b. Kerdon + Archon Superset Routes (PDF, Send Ledger, Plan Diff, Supersession, 6-Reader Gate, 240 Portfolio, Evidence Bundle, Invites & Billing)
    st_pdf, _, txt_pdf = _http_call("GET", f"{base}/tenants/{tid}/docgen/draft-aegean-01/pdf")
    check(st_pdf == 200, "GET /tenants/{id}/docgen/{draft_id}/pdf HTTP 200", txt_pdf)
    check(
        json.loads(txt_pdf).get("pdf_header", "").startswith("%PDF-1.4"),
        "Outbound draft PDF renders valid %PDF-1.4 binary header",
        txt_pdf,
    )

    st_pdiff, _, txt_pdiff = _http_call(
        "POST",
        f"{base}/tenants/{tid}/commissions/plan-diff",
        body={"mode": "RETROACTIVE", "rate_boost_bps": 50},
    )
    check(st_pdiff == 200, "POST /tenants/{id}/commissions/plan-diff HTTP 200", txt_pdiff)

    st_sup, _, txt_sup = _http_call(
        "POST",
        f"{base}/tenants/{tid}/commissions/supersede",
        body={"authority_rank": "OFFICIAL_SETTLEMENT", "reward_net_cents": 1_920_000},
    )
    check(st_sup == 200, "POST /tenants/{id}/commissions/supersede HTTP 200", txt_sup)

    st_gate, _, txt_gate = _http_call(
        "POST",
        f"{base}/tenants/{tid}/strands-gate/verify",
        body={"candidate_prose": "Please pay EUR 999,999.00 immediately."},
    )
    check(st_gate == 200, "POST /tenants/{id}/strands-gate/verify HTTP 200", txt_gate)
    check(
        json.loads(txt_gate)["release_gate_verdict"]["allowed"] is False,
        "6-Reader Strands Release Gate blocks hallucinated or held outbound prose",
        txt_gate,
    )

    st_port, _, txt_port = _http_call(
        "POST",
        f"{base}/tenants/{tid}/portfolio/mode",
        body={"mode": "FULL_240_PORTFOLIO"},
    )
    check(st_port == 200, "POST /tenants/{id}/portfolio/mode 240-record portfolio HTTP 200", txt_port)
    check(
        json.loads(txt_port)["portfolio"]["total_records"] == 240,
        "240-record portfolio loader returns 240 records across 16 clients and 10 suppliers",
        txt_port,
    )

    st_evb, _, txt_evb = _http_call("GET", f"{base}/tenants/{tid}/evidence-bundle")
    check(st_evb == 200, "GET /tenants/{id}/evidence-bundle HTTP 200", txt_evb)
    check(
        len(json.loads(txt_evb).get("bundle_sha256", "")) == 64,
        "Redacted evidence bundle includes 64-hex SHA-256 fingerprint",
        txt_evb,
    )

    st_sub, _, txt_sub = _http_call(
        "POST",
        f"{base}/tenants/{tid}/billing/subscription",
        body={"plan_code": "pro"},
    )
    check(st_sub == 200, "POST /tenants/{id}/billing/subscription HTTP 200", txt_sub)

    # 11b. M9: Deterministic SKU Inventory, Stock Ledger, Weighted-Average COGS & Reorder PO Engine
    st_inv_get, _, txt_inv_get = _http_call("GET", f"{base}/tenants/{tid}/inventory")
    check(st_inv_get == 200, "GET /tenants/{id}/inventory HTTP 200", txt_inv_get)
    inv_get_data = json.loads(txt_inv_get)["inventory"]
    check(len(inv_get_data["sku_items"]) == 4, "Inventory ledger tracks 4 hardware SKUs", inv_get_data)
    check(
        len(inv_get_data["draft_purchase_orders"]) >= 2,
        "Inventory alerts auto-draft supplier Reorder Purchase Orders",
        inv_get_data["draft_purchase_orders"],
    )

    st_inv_mv, _, txt_inv_mv = _http_call(
        "POST",
        f"{base}/tenants/{tid}/inventory/movement",
        body={
            "sku_code": "SKU-ONT-WIFI6-PRO",
            "movement_kind": "SALE_DISPATCH",
            "quantity": 2,
            "unit_sale_price_cents": 11_900,
        },
    )
    check(st_inv_mv == 200, "POST /tenants/{id}/inventory/movement SALE_DISPATCH HTTP 200", txt_inv_mv)
    check(
        json.loads(txt_inv_mv)["movement"]["cogs_cents"] > 0,
        "Inventory sale dispatch posts deterministic weighted-average COGS cents",
        txt_inv_mv,
    )

    st_inv_after, _, txt_inv_after = _http_call("GET", f"{base}/tenants/{tid}/inventory")
    check(
        st_inv_after == 200
        and json.loads(txt_inv_after)["inventory"]["sku_items"][0]["on_hand_qty"] == 12,
        "Cross-Lambda Reader GET /inventory reflects Writer SALE_DISPATCH via DynamoDB journal",
        txt_inv_after,
    )

    # 12. Adversarial Input Validation, Cross-Tenant Isolation & Payload Limits (C6, MF-4)
    st_413, _, _ = _http_call(
        "POST",
        f"{base}/tenants/onboard",
        body="x" * (kaws.MAX_BODY_BYTES + 256),
    )
    check(st_413 == 413, "Payload > 16 KB rejected with HTTP 413")

    st_arr, _, _ = _http_call("POST", f"{base}/tenants/onboard", body="[1, 2, 3]")
    check(st_arr == 400, "JSON array body rejected with HTTP 400")

    st_bad, _, _ = _http_call("POST", f"{base}/tenants/onboard", body="{malformed")
    check(st_bad == 400, "Malformed JSON body rejected with HTTP 400")

    st_xtenant, _, txt_xtenant = _http_call(
        "POST",
        f"{base}/tenants/{tid}/evaluate",
        body={"tenant_id": "tenant-thessaloniki-store", "period": "2026-10"},
    )
    check(
        st_xtenant == 403,
        "Cross-tenant body spoofing rejected with HTTP 403 (MF-4)",
        txt_xtenant,
    )

    st_ws, _, txt_ws = _http_call("GET", f"{base}/")
    check(st_ws == 200 and "Kerdon | ERP Operations" in txt_ws, "GET / renders canonical 18-module ERP Operations SPA")
    st_ops, _, txt_ops = _http_call("GET", f"{base}/tenants/{tid}/operations")
    ops_json = json.loads(txt_ops) if st_ops == 200 else {}
    check(
        st_ops == 200 and "aging" in ops_json and "profitability" in ops_json,
        "GET /tenants/{id}/operations returns operational projections, due-date aging, and cash forecast",
    )

    # 13. JWT-Bound Tenant-Agnostic /erp/* Routing, Multi-Organization RBAC & Pluggable Connectors
    st_erp_orgs, _, txt_erp_orgs = _http_call("GET", f"{base}/erp/organizations")
    erp_orgs_json = json.loads(txt_erp_orgs) if st_erp_orgs == 200 else {}
    check(
        st_erp_orgs == 200 and erp_orgs_json.get("active_tenant_id") == tid,
        "GET /erp/organizations resolves active organization from JWT/actor without tenant_id in URL",
        txt_erp_orgs,
    )

    st_erp_ops, _, txt_erp_ops = _http_call("GET", f"{base}/erp/operations")
    check(
        st_erp_ops == 200 and "aging" in json.loads(txt_erp_ops) and "profitability" in json.loads(txt_erp_ops),
        "GET /erp/operations returns active organization ERP projection without tenant_id in URL",
    )

    st_erp_conn, _, txt_erp_conn = _http_call("GET", f"{base}/erp/connectors")
    conn_json = json.loads(txt_erp_conn) if st_erp_conn == 200 else {}
    pay_ids = [c.get("id") for c in conn_json.get("available_payment_connectors", [])]
    tax_ids = [c.get("id") for c in conn_json.get("available_tax_connectors", [])]
    check(
        st_erp_conn == 200 and "PAYPAL" in pay_ids and "AADE_MYDATA" in tax_ids,
        "GET /erp/connectors exposes pluggable Payment (PAYPAL/STRIPE/BANK_IBAN) and Tax (AADE_MYDATA/PEPPOL_EU) catalog",
        txt_erp_conn,
    )
    first_doc_id = str(conn_json.get("mydata", {}).get("records", [{}])[0].get("document_id", "doc-aegean-mobility-inv-101"))

    pp_is_live = bool(conn_json.get("runtime_modes", {}).get("paypal_credentials_present"))
    st_pp_ord, _, txt_pp_ord = _http_call("POST", f"{base}/erp/connectors/paypal/order", body={"document_id": first_doc_id, "auto_capture": not pp_is_live})
    pp_ord_json = json.loads(txt_pp_ord) if st_pp_ord == 201 else {}
    if pp_is_live:
        oid_live = str(pp_ord_json.get("order", {}).get("order_id", ""))
        st_cap_u, _, txt_cap_u = _http_call("POST", f"{base}/erp/connectors/paypal/capture", body={"order_id": oid_live, "document_id": first_doc_id})
        pp_ord_ok = st_pp_ord == 201 and bool(oid_live) and pp_ord_json.get("captured") is False and st_cap_u == 502 and "ORDER_NOT_APPROVED" in txt_cap_u
    else:
        pp_ord_ok = st_pp_ord == 201 and pp_ord_json.get("captured") is True and pp_ord_json.get("order", {}).get("paypal_fee_cents", 0) > 0 and "agentic_commerce_narrative" in pp_ord_json
    check(pp_ord_ok, "POST /erp/connectors/paypal/order executes 2-step live Sandbox order + fail-closed ORDER_NOT_APPROVED (502) or simulated 3-line GL capture", txt_pp_ord)

    st_pp_disp, _, txt_pp_disp = _http_call(
        "POST",
        f"{base}/erp/connectors/paypal/dispute",
        body={
            "dispute_id": "PPDISP-UAT-001",
            "document_id": first_doc_id,
            "disputed_amount_cents": 20_000,
            "reason_code": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        },
    )
    pp_disp_json = json.loads(txt_pp_disp) if st_pp_disp == 201 else {}
    check(
        st_pp_disp == 201
        and pp_disp_json.get("dispute", {}).get("clawback_id", "").startswith("cb-pp-")
        and "agentic_commerce_narrative" in pp_disp_json,
        "POST /erp/connectors/paypal/dispute triggers Seller Commission ClawbackEvent and Agentic narrative",
        txt_pp_disp,
    )

    st_mydata_tx, _, txt_mydata_tx = _http_call(
        "POST",
        f"{base}/erp/connectors/mydata/transmit",
        body={"document_id": first_doc_id, "series": "A", "aa": "109"},
    )
    mydata_tx_json = json.loads(txt_mydata_tx) if st_mydata_tx == 201 else {}
    check(
        st_mydata_tx == 201
        and mydata_tx_json.get("mydata_transmission", {}).get("status") == "TRANSMITTED"
        and "<InvoicesDoc" in mydata_tx_json.get("mydata_transmission", {}).get("xml_preview", ""),
        "POST /erp/connectors/mydata/transmit builds AADE myDATA v1.0.8 InvoicesDoc XML and stamps MARK",
        txt_mydata_tx,
    )

    st_new_org, _, txt_new_org = _http_call(
        "POST",
        f"{base}/erp/organizations",
        body={
            "slug": "uat-second-org",
            "display_name": "UAT Second Franchise LLC",
            "tax_id": "EL099887766",
        },
    )
    new_org_id = json.loads(txt_new_org).get("organization", {}).get("tenant_id", "") if st_new_org == 201 else ""
    check(
        st_new_org == 201 and new_org_id.startswith("tnt-uat-second-org-"),
        "POST /erp/organizations creates isolated second organization for multi-company owner",
        txt_new_org,
    )

    st_inv_col, _, txt_inv_col = _http_call(
        "POST",
        f"{base}/erp/members/invite",
        headers={"x-active-tenant": new_org_id},
        body={
            "email": "external-cpa@firm-synth.eu",
            "target_sub": "jwt-sub-uat-cpa",
            "role": "PUBLIC_AUDITOR",
            "auto_accept": True,
        },
    )
    check(
        st_inv_col == 201
        and json.loads(txt_inv_col).get("invitation", {}).get("role") == "PUBLIC_AUDITOR",
        "POST /erp/members/invite grants per-organization collaborator role (PUBLIC_AUDITOR in Org 2)",
        txt_inv_col,
    )

    st_ai_ext, _, txt_ai_ext = _http_call(
        "POST",
        f"{base}/erp/ai/extract-document",
        body={
            "raw_text": "Invoice INV-UAT-AI-801\nDate: 2026-10-29 Due: 2026-11-29\nCloud Node Cluster: EUR 1000.00 (24% VAT)\nTech Onboarding: EUR 200.00 (13% VAT)",
            "module": "purchases",
        },
    )
    ai_ext_json = json.loads(txt_ai_ext) if st_ai_ext == 200 else {}
    check(
        st_ai_ext == 200
        and ai_ext_json.get("extracted_draft", {}).get("invoice_number") == "INV-UAT-AI-801"
        and ai_ext_json.get("extracted_draft", {}).get("total_gross_cents") == 146_600,
        "POST /erp/ai/extract-document extracts multi-rate VAT lines (24% & 13%) for /workspace AI Auto-Fill",
        txt_ai_ext,
    )

    st_ai_html, _, txt_ai_html = _http_call(
        "POST",
        f"{base}/erp/ai/extract-document",
        body={
            "raw_text": "<table><tr><td>Row</td><td>EUR 500.00</td></tr></table>",
            "module": "purchases",
            "source_kind": "HTML_BODY_TABLE",
        },
    )
    check(
        st_ai_html == 422,
        "POST /erp/ai/extract-document blocks HTML_BODY_TABLE invoice extraction with HTTP 422 (ADR-048)",
        txt_ai_html,
    )

    st_bc, _, txt_bc = _http_call("GET", f"{base}/erp/bounded-contexts")
    bc_json = json.loads(txt_bc) if st_bc == 200 else {}
    check(
        st_bc == 200
        and len(bc_json.get("bounded_contexts", [])) == 7
        and len(bc_json.get("public_datasets", [])) == 4,
        "GET /erp/bounded-contexts exposes 7 DDD Bounded Contexts (APQC PCF v7.4 / UBL 2.1 / ISO 20022) and 4 Public Datasets",
        txt_bc,
    )

    st_ds_imp, _, txt_ds_imp = _http_call(
        "POST",
        f"{base}/erp/datasets/import",
        body={"dataset_id": "kerdon-hellenic-eu-v1"},
    )
    ds_imp_json = json.loads(txt_ds_imp) if st_ds_imp == 201 else {}
    check(
        st_ds_imp == 201
        and ds_imp_json.get("imported", {}).get("dataset_id") == "kerdon-hellenic-eu-v1"
        and ds_imp_json.get("imported", {}).get("imported_documents_count", 0) >= 1,
        "POST /erp/datasets/import ingests public Hellenic EU corpus into double-entry GL with UoW receipt",
        txt_ds_imp,
    )
    cov_v = ds_imp_json.get("imported", {}).get("coverage_verification", {})
    check(
        bool(cov_v.get("all_18_modules_functional"))
        and cov_v.get("modules_passed") == 18
        and bool(cov_v.get("trial_balance_balanced")),
        "POST /erp/datasets/import verifies 18/18 functional modules across all 7 DDD Bounded Contexts with balanced Trial Balance",
        json.dumps(cov_v),
    )

    st_fp_de, _, txt_fp_de = _http_call("POST", f"{base}/erp/connectors/fiscal-profile", body={"country_code": "DE"})
    check(st_fp_de == 200 and json.loads(txt_fp_de).get("fiscal_profile", {}).get("aade_mydata_enabled") is False, "POST /erp/connectors/fiscal-profile parametrically disables AADE myDATA for non-Greek (DE) organization", txt_fp_de)
    st_fp_gr, _, txt_fp_gr = _http_call("POST", f"{base}/erp/connectors/fiscal-profile", body={"country_code": "GR", "doy": "Athens Corporate Tax Office (KEFODE Attikis)"})
    check(st_fp_gr == 200 and json.loads(txt_fp_gr).get("fiscal_profile", {}).get("aade_mydata_enabled") is True, "POST /erp/connectors/fiscal-profile parametrically activates AADE myDATA v1.0.8 + 17.1 Payroll for Greek (GR) organization", txt_fp_gr)
    from uat_gtm_checks import check_paypal_webhook_contract, run_gtm_and_live_ai_uat
    webhook_ok, webhook_check, txt_pp_wh = check_paypal_webhook_contract(base, pp_is_live or bool(expected_sha), _http_call)
    check(webhook_ok and len(conn_json.get("paypal", {}).get("agentic_tools", [])) == 6 and pp_disp_json.get("evidence_defense_packet", {}).get("evidence_type") == "PROOF_OF_FULFILLMENT", f"PayPal Agentic Commerce: 6 tools, evidence packet, and {webhook_check}", txt_pp_wh)
    check("lang-select" in txt_ws and "EN · English" in txt_ws and json.loads(txt_fp_gr).get("fiscal_profile", {}).get("country_name") == "Greece", "Bilingual EN default + EL switcher active across /workspace and fiscal profile", "lang-select")
    run_gtm_and_live_ai_uat(base=base, tid=tid, is_live=bool(expected_sha), check=check, http_call=_http_call)

    # Clean reset after UAT
    _http_call("POST", f"{base}/tenants/{tid}/reset", body={})
    print(f"UAT PASS: {checks_passed} checks")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Kerdon MSP end-to-end UAT smoke checks")
    parser.add_argument(
        "url",
        nargs="?",
        default="",
        help="Target base URL (omit to start an ephemeral local server)",
    )
    parser.add_argument(
        "--expected-sha",
        default="",
        help="Expected DEPLOYED_SHA prefix when testing a live deployment",
    )
    args = parser.parse_args()

    if args.url:
        return run_uat_against_base(args.url, expected_sha=args.expected_sha or None)

    port = 8892
    proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "scripts" / "serve_local.py"), str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 15.0
        while time.time() < deadline:
            try:
                st, _, _ = _http_call("GET", f"{base}/health", timeout=2.0)
                if st == 200:
                    break
            except Exception:
                time.sleep(0.25)
        return run_uat_against_base(base)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())

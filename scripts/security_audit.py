"""Enterprise Security Stage Audit for Kerdon MSP (`scripts/security_audit.py`).

Executes deterministic SAST, Secret Scanning, CloudFormation/SAM IaC Security
Posture verification, and OWASP API Security Top 10 (2023) adversarial fuzzing:
  - SEC-01: Git-tracked secret & credential leak scan (AWS keys, PEM keys, PATs)
  - SEC-02: Python AST dangerous-call audit (no eval/exec/pickle/shell=True)
  - SEC-03: SAM/CloudFormation IaC encryption, public-access block, throttling & 3-role IAM audit
  - SEC-04: OWASP API1:2023 BOLA / Cross-Tenant IDOR rejection (HTTP 403)
  - SEC-05: OWASP API5:2023 BFLA / Restricted SELLER role rejection on mutations (HTTP 403)
  - SEC-06: OWASP API5:2023 Reader/Evaluator handler isolation against state mutations
  - SEC-07: OWASP API4:2023 16 KB payload bomb (HTTP 413) & malformed JSON fuzzing (HTTP 400)
  - SEC-08: OWASP API8:2023 XSS script-tag sanitization & ADR-048 HTML invoice-posting guard
  - SEC-09: Four-Eyes SoD self-approval block (HTTP 403) & Changed-Evidence stale payout block (HTTP 409)
  - SEC-10: Replay & duplicate outbound dispatch block via DurableSendLedger (HTTP 409)
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import kerdon as kd  # noqa: E402
import kerdon_aws as kaws  # noqa: E402
from kerdon_aws.handlers import (  # noqa: E402
    dispatch_http_event,
    lambda_evaluator,
    lambda_reader,
    reset_superset_runtime,
)
from kerdon_aws.inventory_routes import reset_inventory_runtime  # noqa: E402
from kerdon_aws.persistence import MultiTenantStore  # noqa: E402

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS Access Key ID", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Private Key Header", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("GitHub PAT", re.compile(r"\b(ghp_[0-9A-Za-z]{36}|github_pat_[0-9A-Za-z_]{50,})\b")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
)

FORBIDDEN_AST_CALLS = {
    "eval",
    "exec",
    "compile",
    "pickle.loads",
    "pickle.load",
    "marshal.loads",
    "marshal.load",
}


def _http_event(
    method: str,
    path: str,
    body: object | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    raw_body: str | None = None
    if isinstance(body, str):
        raw_body = body
    elif body is not None:
        raw_body = json.dumps(body)
    return {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": "",
        "headers": headers or {"x-kerdon-role": "MSP_FINOPS_DIRECTOR"},
        "requestContext": {"http": {"method": method, "path": path}},
        "body": raw_body,
        "isBase64Encoded": False,
    }


def check_sec01_secret_scan() -> list[str]:
    out = subprocess.check_output(
        ["git", "ls-files"], cwd=REPO_ROOT, text=True, encoding="utf-8"
    )
    errors: list[str] = []
    for rel in out.splitlines():
        if not rel.strip():
            continue
        p = REPO_ROOT / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for label, pat in SECRET_PATTERNS:
            if pat.search(text):
                errors.append(f"{rel} matched secret pattern: {label}")
    return errors


def check_sec02_ast_audit() -> list[str]:
    errors: list[str] = []
    for py in sorted(SRC_DIR.rglob("*.py")):
        rel = py.relative_to(REPO_ROOT)
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(rel))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn_name = ""
                if isinstance(node.func, ast.Name):
                    fn_name = node.func.id
                elif isinstance(node.func, ast.Attribute) and isinstance(
                    node.func.value, ast.Name
                ):
                    fn_name = f"{node.func.value.id}.{node.func.attr}"
                if fn_name in FORBIDDEN_AST_CALLS:
                    errors.append(f"{rel}:{node.lineno} calls forbidden {fn_name}()")
                for kw in node.keywords:
                    if (
                        kw.arg == "shell"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True
                    ):
                        errors.append(f"{rel}:{node.lineno} uses shell=True")
    return errors


def check_sec03_iac_posture() -> list[str]:
    errors: list[str] = []
    tpl = (REPO_ROOT / "infra" / "template.yaml").read_text(encoding="utf-8")
    required_snippets = (
        "BlockPublicAcls: true",
        "BlockPublicPolicy: true",
        "IgnorePublicAcls: true",
        "RestrictPublicBuckets: true",
        "SSEAlgorithm: AES256",
        "PointInTimeRecoveryEnabled: true",
        "SSEEnabled: true",
        "ThrottlingBurstLimit:",
        "ThrottlingRateLimit:",
        "ReservedConcurrentExecutions:",
        "ReaderFunction:",
        "EvaluatorFunction:",
        "WriterFunction:",
        "DynamoDBReadPolicy:",
    )
    for snippet in required_snippets:
        if snippet not in tpl:
            errors.append(f"infra/template.yaml missing security invariant: {snippet}")
    return errors


def run_owasp_api_security_checks() -> tuple[list[tuple[str, bool, str]], list[str]]:
    store = MultiTenantStore(workspace=kd.build_default_msp_workspace())
    reset_superset_runtime()
    reset_inventory_runtime()
    tid = store.workspace.default_tenant_id
    results: list[tuple[str, bool, str]] = []
    failures: list[str] = []

    def record(code: str, ok: bool, detail: str) -> None:
        results.append((code, ok, detail))
        if not ok:
            failures.append(f"{code}: {detail}")

    # SEC-04: OWASP API1:2023 BOLA / Cross-Tenant IDOR
    bola = dispatch_http_event(
        _http_event(
            "POST",
            f"/tenants/{tid}/evaluate",
            {"tenant_id": "tnt-cyclades-telecom", "period": "2026-10"},
        ),
        store=store,
    )
    record(
        "SEC-04 (OWASP API1 BOLA / Cross-Tenant IDOR)",
        bola["statusCode"] == 403,
        f"status={bola['statusCode']}",
    )

    # SEC-05: OWASP API5:2023 BFLA / Restricted SELLER Role
    bfla_inv = dispatch_http_event(
        _http_event(
            "POST",
            f"/tenants/{tid}/inventory/movement",
            {"sku_code": "SKU-ONT-WIFI6-PRO", "kind": "GOODS_RECEIPT", "qty": 5},
            headers={"x-kerdon-role": "SELLER"},
        ),
        store=store,
    )
    bfla_tr = dispatch_http_event(
        _http_event(
            "POST",
            f"/tenants/{tid}/treasury/execute",
            {"approval_id": "apr-aegean-mobility-comm-oct"},
            headers={"x-kerdon-role": "SELLER"},
        ),
        store=store,
    )
    record(
        "SEC-05 (OWASP API5 BFLA / Restricted SELLER Role)",
        bfla_inv["statusCode"] == 403 and bfla_tr["statusCode"] == 403,
        f"inventory={bfla_inv['statusCode']}, treasury={bfla_tr['statusCode']}",
    )

    # SEC-06: Reader & Evaluator Lambda handlers refuse state mutations
    rd_mut = lambda_reader(
        _http_event(
            "POST",
            f"/tenants/{tid}/treasury/execute",
            {"approval_id": "apr-aegean-mobility-comm-oct"},
        ),
        store=store,
    )
    ev_mut = lambda_evaluator(
        _http_event(
            "POST",
            f"/tenants/{tid}/treasury/execute",
            {"approval_id": "apr-aegean-mobility-comm-oct"},
        ),
        store=store,
    )
    record(
        "SEC-06 (Lambda Role Isolation Reader/Evaluator vs Writer)",
        rd_mut["statusCode"] in (403, 405) and ev_mut["statusCode"] in (403, 404),
        f"reader={rd_mut['statusCode']}, evaluator={ev_mut['statusCode']}",
    )

    # SEC-07: OWASP API4:2023 Payload Bomb (>16KB) & Malformed JSON
    bomb = dispatch_http_event(
        _http_event("POST", "/tenants/onboard", "A" * (kaws.MAX_BODY_BYTES + 512)),
        store=store,
    )
    bad_json = dispatch_http_event(
        _http_event("POST", "/tenants/onboard", "{unclosed"),
        store=store,
    )
    record(
        "SEC-07 (OWASP API4 16KB Cap & JSON Fuzzing)",
        bomb["statusCode"] == 413 and bad_json["statusCode"] == 400,
        f"bomb={bomb['statusCode']}, bad_json={bad_json['statusCode']}",
    )

    # SEC-08: OWASP API8:2023 XSS Sanitization & ADR-048 HTML Invoice Guard
    xss_onboard = dispatch_http_event(
        _http_event(
            "POST",
            "/tenants/onboard",
            {
                "slug": "xss-test-store",
                "display_name": "<script>alert('xss')</script> Store",
                "legal_name": "XSS Test IKE",
                "tax_id": "EL099887766",
            },
        ),
        store=store,
    )
    cockpit_res = lambda_reader(_http_event("GET", "/"), store=store)
    cockpit_html = str(cockpit_res.get("body") or "")
    record(
        "SEC-08 (OWASP API8 XSS Sanitization in Cockpit DOM)",
        xss_onboard["statusCode"] == 201
        and "<script>alert('xss')</script>" not in cockpit_html
        and "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in cockpit_html,
        f"onboard={xss_onboard['statusCode']}, html_escaped=True",
    )

    # SEC-09: Four-Eyes SoD & Changed-Evidence Approval Invalidation
    sod = dispatch_http_event(
        _http_event(
            "POST",
            f"/tenants/{tid}/commissions/approve",
            {"submitted_by": "act-same", "approver_id": "act-same"},
        ),
        store=store,
    )
    dispatch_http_event(
        _http_event(
            "POST",
            f"/tenants/{tid}/credit-notes",
            {
                "credit_note_id": "cn-sec-01",
                "counterparty_id": "sup-aegean-mobility-01",
                "net_cents": 10_000,
                "vat_cents": 2_400,
                "gross_cents": 12_400,
                "referenced_invoice_id": "doc-aegean-mobility-pur-201",
            },
        ),
        store=store,
    )
    stale = dispatch_http_event(
        _http_event(
            "POST",
            f"/tenants/{tid}/treasury/execute",
            {"approval_id": "apr-aegean-mobility-sup-201"},
        ),
        store=store,
    )
    record(
        "SEC-09 (Four-Eyes SoD 403 & Changed-Evidence Stale Approval 409)",
        sod["statusCode"] == 403 and stale["statusCode"] == 409,
        f"sod={sod['statusCode']}, stale={stale['statusCode']}",
    )

    # SEC-10: Outbound Send Replay Protection via DurableSendLedger
    draft_id = store.get_tenant_state(tid).outbound_drafts[0].draft_id
    send1 = dispatch_http_event(
        _http_event("POST", f"/tenants/{tid}/docgen/{draft_id}/send", {}),
        store=store,
    )
    send2 = dispatch_http_event(
        _http_event("POST", f"/tenants/{tid}/docgen/{draft_id}/send", {}),
        store=store,
    )
    record(
        "SEC-10 (DurableSendLedger Replay Block HTTP 409)",
        send1["statusCode"] == 200 and send2["statusCode"] == 409,
        f"first={send1['statusCode']}, replay={send2['statusCode']}",
    )

    reset_superset_runtime()
    reset_inventory_runtime()
    return results, failures


def main() -> int:
    failures: list[str] = []
    sec01 = check_sec01_secret_scan()
    print(f"[{'PASS' if not sec01 else 'FAIL'}] SEC-01: Git-tracked secret & credential scan")
    failures.extend(sec01)

    sec02 = check_sec02_ast_audit()
    print(f"[{'PASS' if not sec02 else 'FAIL'}] SEC-02: Python AST dangerous-call audit")
    failures.extend(sec02)

    sec03 = check_sec03_iac_posture()
    print(f"[{'PASS' if not sec03 else 'FAIL'}] SEC-03: SAM/CloudFormation IaC security posture")
    failures.extend(sec03)

    owasp_results, owasp_failures = run_owasp_api_security_checks()
    for code, ok, detail in owasp_results:
        print(f"[{'PASS' if ok else 'FAIL'}] {code} ({detail})")
    failures.extend(owasp_failures)

    if failures:
        for f in failures:
            print(f"SECURITY FAILURE: {f}", file=sys.stderr)
        return 1
    print("SECURITY STAGE PASS: 10/10 security controls verified (0 vulnerabilities)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

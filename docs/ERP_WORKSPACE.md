# ERP Operations Workspace, Pluggable Connectors & Production Hardening Reference

**Kerdon turns PayPal checkouts, subscriptions, disputes, and bills into a balanced double-entry ledger, seller commissions, and Four-Eyes governed payouts.**

Built for **Sofia Marinou, FinOps and Multi-Tenant Back-Office Director at a 35-client AWS Managed Service Provider (MSP)**, the canonical CloudFront root `/` React 18 + TypeScript + Vite + Tailwind SPA exposes all 18 operational modules, JWT-bound `/erp/*` routing, pluggable payment and statutory tax connectors, and the Go-To-Market (GTM) & AWS Marketplace SaaS Launchpad on `main`.

---

## 1. Delivered & Shipped Capabilities (`main`)

1. **Single Canonical React 18 Operations SPA (`/`):**
   - CloudFront CDN (`SpaRewriteFunction` on `S3WebOrigin`) serves the 18-module React 18 Operations SPA at `/` (`src/kerdon_aws/workspace_ui.py`) and enforces edge `301` canonical redirects from legacy `/workspace` and `/cockpit` paths without intercepting API Gateway `403`/`404` JSON error responses.
   - `BASE_PATH` resolution handles both CloudFront root `/` and API Gateway `/Prod/` stages cleanly, and aliases `#module=commercial` directly to `#module=billing` (`Subscription & fleet`).
2. **Production Identity & Per-Organization RBAC (`src/kerdon_aws/identity.py`):**
   - Server-managed `SubjectMembershipRegistry` maps verified JWT `sub` claims (API Gateway HTTP API v2 `requestContext.authorizer.jwt.claims` or signed HS256 `Authorization: Bearer <jwt>`) to `Actor`, `Role`, `allowed_tenant_ids`, `org_roles`, and `seller_id`.
   - Fails closed in strict mode (`KERDON_AUTH_MODE=strict` or `x-kerdon-auth-mode: strict`): ignores spoofed `x-kerdon-role` / `x-kerdon-actor` client headers, returns `HTTP 401` on unauthenticated calls, and enforces seller-to-seller privacy isolation on `GET /tenants/{id}/commissions/seller-statement`.
   - Separates synthetic demo fixtures from production onboarding (`build_empty_tenant_state` in `src/kerdon/demo_fixtures.py`) and supports balanced Day-1 cutover via `POST /tenants/{id}/onboarding/opening-balance` (`src/kerdon/gtm_marketplace.py`).
3. **Zero-Scan Persistence & Atomic Unit of Work (`src/kerdon_aws/persistence.py`, `src/kerdon/uow.py`):**
   - Zero suppressed storage errors (`PersistenceError` -> `HTTP 503`, `VersionConflictError` -> `HTTP 409`), paginated DynamoDB journal replay (`LastEvaluatedKey`), side-effect-free journal hydration (`replay_journal_entries`), `TransactWriteItems` atomic commits with Transactional Outbox (`OUTBOX#obx-*`), and SHA-256 verified tenant backup/restore.
4. **Commercial ERP Documents, Allocations & Aging (`src/kerdon/erp_services.py`, `src/kerdon/operational.py`):**
   - Validated customer/supplier CRUD (`POST /tenants/{id}/parties`), Four-Eyes drafts (`POST /tenants/{id}/drafts`), multi-line mixed-VAT (`0%`, `6%`, `13%`, `24%`) sales and purchase invoices (`POST /tenants/{id}/invoices`), direct expenses (`POST /tenants/{id}/expenses`), document reversals (`POST /tenants/{id}/invoices/{doc_id}/reverse`), cash receipts/payments with allocations (`POST /tenants/{id}/receipts`, `POST /tenants/{id}/payments`), and AR/AP due-date aging + 30-day cash forecasts (`GET /tenants/{id}/operations`).
5. **Live Bedrock AI Document Auto-Fill, Pluggable Connectors & AWS Marketplace Metering:**
   - `POST /erp/ai/extract-document` and `POST /tenants/{id}/ai/extract-document` route to `EvaluatorFunction`, combining deterministic integer-cent line math (`src/kerdon/uow.py`) with live **Strands + Amazon Bedrock (`eu.amazon.nova-pro-v1:0`)** counterparty/header enrichment (`extract_document_with_bedrock` in `src/kerdon_aws/bedrock_adapter.py`).
   - Pluggable Payment (`NONE`, `BANK_IBAN`, `PAYPAL`, `STRIPE`) and Statutory Tax (`NONE`, `AADE_MYDATA` REST v1.0.8 `InvoicesDoc` XML, `PEPPOL_EU` BIS Billing 3.0) connectors include runtime redacted credential configuration (`POST /tenants/{id}/connectors/config`) and fail-closed live readiness probes (`POST /tenants/{id}/connectors/verify`).
   - AWS Marketplace SaaS onboarding (`POST /gtm/marketplace/resolve-customer`), usage metering (`POST /gtm/marketplace/meter-usage`), and 6-pillar production readiness (`GET /gtm/readiness`) power the `#module=billing` Launchpad.

---

## 2. Endpoint, Role & Mutation Inventory

| Route | Method | Lambda Role (`A7`) | Required Capability | Mutates State | Description |
|---|---|---|---|---|---|
| `/` | `GET`, `HEAD` | `S3+CDN` / `Reader` | Public HTML shell | No | Serves canonical React 18 Operations SPA (`/workspace` & `/cockpit` 301-redirect to `/`) |
| `/health`, `/DEPLOYED_SHA` | `GET`, `HEAD` | `Reader` | Public probe | No | Liveness, rule count (`24`), and deployed git SHA |
| `/gtm/pricing`, `/gtm/readiness` | `GET`, `HEAD` | `Reader` | Public / `VIEW_PNL` | No | SaaS tiers, $10M ARR economics, and 6-pillar GTM readiness matrix |
| `/gtm/marketplace/resolve-customer`, `/gtm/marketplace/meter-usage` | `POST` | `Writer` | `MANAGE_TENANTS` | Yes | AWS Marketplace `ResolveCustomer` & `BatchMeterUsage` integration |
| `/tenants/onboard`, `/tenants/{id}/onboarding/opening-balance` | `POST` | `Writer` | `MANAGE_TENANTS` / `POST_LEDGER` | Yes | Self-service tenant onboarding & balanced opening trial-balance cutover |
| `/tenants/{id}/operations`, `/erp/operations` | `GET`, `HEAD` | `Reader` | `VIEW_PNL` | No | Operational lists, statements, KPIs, aging, forecast, targets |
| `/tenants/{id}/parties`, `/tenants/{id}/drafts` | `POST` | `Writer` | `ISSUE_DOCS` | Yes | Validated party CRUD & Four-Eyes `DRAFT -> APPROVED` workflow |
| `/tenants/{id}/invoices`, `/tenants/{id}/expenses` | `POST` | `Writer` | `POST_LEDGER` | Yes | Multi-line mixed-VAT invoices & direct supplier expense bills |
| `/tenants/{id}/receipts`, `/tenants/{id}/payments` | `POST` | `Writer` | `POST_LEDGER` | Yes | Cash settlements with allocations, fees, and unapplied advances |
| `/tenants/{id}/connectors/config`, `/tenants/{id}/connectors/verify` | `POST` | `Writer` | `MANAGE_TENANTS` | Yes | Redacted connector credential update & live provider probe (`require_live`) |
| `/tenants/{id}/treasury/approve`, `/tenants/{id}/treasury/execute` | `POST` | `Writer` | `APPROVE_PAYOUTS` / `EXECUTE_PAYOUTS` | Yes | Evidence-bound payout approval & Four-Eyes execution |
| `/tenants/{id}/query`, `/tenants/{id}/evaluate`, `/erp/ai/extract-document` | `POST` | `Evaluator` | `VIEW_PNL` / `RUN_COMPLETENESS` / `ISSUE_DOCS` | No | Strands + Amazon Bedrock Nova Pro + AgentCore Memory evaluation & extraction |

---

## 3. UI-to-Service Coverage & Live Credential Boundaries

| Workspace Area / Capability | Status | Backing Service / Route | Verification Evidence |
|---|---|---|---|
| **Dashboard KPIs, Track 2 4-Step Loop & Journal Drill-Down** | **Shipped & Live** | `GET /tenants/{id}/operations`, `POST /tenants/{id}/track2/close-runs` | `tests/test_operational.py`, `scripts/workspace_browser_qa.py` |
| **Parties, Multi-Line Mixed-VAT Invoices, Expenses & Reversals** | **Shipped & Live** | `POST /tenants/{id}/parties`, `POST /tenants/{id}/invoices`, `POST /tenants/{id}/expenses` | `tests/test_erp_workspace_production.py`, `tests/test_workspace_http.py` |
| **AI Document Auto-Fill (`#ai-autofill-btn`) & `HTML_BODY_TABLE` Guard** | **Shipped & Live on Bedrock** | `POST /erp/ai/extract-document` (`EvaluatorFunction` -> `eu.amazon.nova-pro-v1:0`) | `tests/test_kerdon_aws.py`, `scripts/uat_smoke.py` |
| **AgentCore Memory Write & Read-Back (`kerdon_msp_memory`)** | **Shipped & Live on AWS** | `AWS::BedrockAgentCore::Memory` (`create_event` + `list_events` in `src/kerdon_aws/bedrock_adapter.py`) | `tests/test_kerdon_aws.py`, `scripts/uat_smoke.py` |
| **GTM Launchpad, Opening Trial-Balance Import & Marketplace Metering** | **Shipped & Live** | `GET /gtm/readiness`, `POST /tenants/{id}/onboarding/opening-balance`, `POST /gtm/marketplace/*` | `scripts/uat_gtm_checks.py`, `tests/test_kerdon_aws.py` |
| **Pluggable Payment (`PayPal`/`Bank IBAN`) & Tax (`AADE myDATA` v1.0.8 XML)** | **Shipped (Owner Keys Optional)** | `src/kerdon_aws/connectors_adapter.py` (`POST /tenants/{id}/connectors/verify`) | Deterministic sandbox mode active; `require_live=True` fails closed until live PayPal/YPAES keys are supplied |
| **Strict Cognito / OIDC JWT Cutover (`AuthMode=strict`)** | **Code Verified (Demo Stack Uses `demo`)** | `src/kerdon_aws/identity.py` (`SubjectMembershipRegistry`) | Public hackathon stack runs `AuthMode=demo` for zero-login judge access; customer stacks set `AuthMode=strict` |

---

## 4. Verification Commands & Production Cutover Checklist

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python scripts/verify_gates.py
PYTHONPATH=src python scripts/verify_gates.py --self-test
PYTHONPATH=src python scripts/security_audit.py
PYTHONPATH=src python scripts/uat_smoke.py
```

- [x] `59/59` unit, hexagonal port-swap, security, and GTM Marketplace tests pass across `8` test modules (`src/kerdon/` has `28` pure domain modules with `0` cloud/LLM SDK imports).
- [x] `108/108` local (`111/111` live AWS) HTTP API v2 UAT smoke and adversarial boundary checks (`scripts/uat_smoke.py`) pass.
- [x] `10/10` readiness gates (`scripts/verify_gates.py`), `5/5` negative `--self-test` failure proofs, and `10/10` OWASP/IAM `SEC-01..SEC-10` controls (`scripts/security_audit.py`) pass.
- [x] Every `.py`, `.ts`, and `.tsx` source file in `src/`, `scripts/`, `tests/`, and `frontend/src/` is `<= 800` lines (`Gate A1`).

---

## 5. 3-Minute Demo Video Storyboard (`kerdon.ai`)

1. **`0:00 - 0:25` Framing & Live CloudFront SPA (`/`):** Introduce Sofia Marinou's 35-client MSP back-office pain and show the live Operations Dashboard (`https://dshvkidt3tkge.cloudfront.net/`), highlighting deterministic integer-cent KPIs paired with live **Amazon Bedrock Nova Pro** narration.
2. **`0:25 - 1:10` Autonomous Email Intake, Live Bedrock Auto-Fill & 8-Stage Close:** Trigger `⚡ Autonomous Email Ingest` (`docs@aegean-mobility.kerdon.ai`), open the Sales/Purchases drawer `#ai-autofill-btn` (`strands-bedrock:eu.amazon.nova-pro-v1:0`), and run `1. Close Run` -> `2. Four-Eyes Approve` -> `3. Export Pack` backed by `AWS::BedrockAgentCore::Memory` (`kerdon_msp_memory`).
3. **`1:10 - 2:05` Multi-Organization RBAC, AADE myDATA XML, PayPal & GTM Launchpad:** Open `Subscription & fleet` (`/#module=billing`) to show per-organization collaborator RBAC (`org_roles`), balanced Opening Trial-Balance Cutover, AWS Marketplace `ResolveCustomer`/`BatchMeterUsage`, and country-parametric **AADE myDATA v1.0.8 `InvoicesDoc` XML** (`MARK` + `E3`).
4. **`2:05 - 3:00` Changed-Evidence Payout Invalidation & Aletheia Braille Receipt:** Inject late Supplier Credit Note `CN-99` (`EUR 310.00`), show stale supplier payout approval `apr-aegean-mobility-sup-201` flipping immediately to `INVALIDATED` (`HTTP 409 Conflict`), execute the unaffected commission payout (`HTTP 200 OK`), and verify the Spoken + Grade-1 ASCII Braille Merkle receipt (`AletheiaMerkleReceipt`).

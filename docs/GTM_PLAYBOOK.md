# Go-To-Market (GTM) & AWS Marketplace SaaS Playbook: Kerdon MSP

**Kerdon MSP turns client emails and bills into a balanced double-entry ledger, seller commissions, auto-drafted fixes, and invalidated stale payouts on AWS.**

---

## 1. Ideal Customer Profile (ICP) & Named Buyer

- **Primary Buyer (`J1`):** **Sofia Marinou, FinOps and Multi-Tenant Back-Office Director at a 15-to-100 client AWS Managed Service Provider (MSP)** or multi-entity accounting practice.
- **Secondary Buyer:** Multi-store retail, telecom, and mobility franchise operators (`5-to-50` storefronts) managing store-level P&L, principal commission settlements, and salesperson payouts.
- **Operational Pain:** Each downstream SMB or franchise client forwards unstructured `.eml`/`.msg` threads, PDF vendor bills, payroll files (`Payroll Register + APD + FMY`), principal commission sheets, and late supplier credit notes. Without Kerdon MSP, controllers re-key invoices manually per tenant, miss uninvoiced settlements, reconcile seller commissions in brittle spreadsheets, and risk paying stale supplier approvals after a credit note has already arrived.
- **Business Operation Performed (Zero-Click Autonomous Loop + Exception Review):**
  1. **Autonomous Trigger Outside the UI:** Client and vendor emails arriving at `docs@<slug>.kerdon.ai` (`POST /tenants/{id}/ingest/email`) unpack nested `.msg`/`.eml` envelopes, extract structured drafts via **AWS Strands Agents SDK + Amazon Bedrock (`eu.amazon.nova-pro-v1:0`)**, post balanced double-entry journal lines, evaluate 24 completeness rules, and invalidate affected pending payout approvals automatically.
  2. **Controller Exception Review:** Sofia Marinou reviews only ranked completeness gaps (`R01..R24`), approves human-gated corrective documents through the 6-Reader Strands Release Gate, and releases Four-Eyes treasury payouts within currency reserve floors.
  3. **External Last-Mile Write:** Verified outputs land directly in downstream systems of record via Merkle-sealed journal CSV exports (`GET /tenants/{id}/export/journal-csv` for Xero HQ and SoftOne/Galaxy ERP), **AADE myDATA v1.0.8 `InvoicesDoc` XML** (`POST /tenants/{id}/connectors/mydata/transmit`), **Peppol BIS Billing 3.0 XML**, `%PDF-1.4` corrective notices (`GET /tenants/{id}/docgen/{draft_id}/pdf`), and governed **PayPal Orders v2 / Payouts v1** settlements.

---

## 2. Quantified Buyer ROI & MSP Resell Margin

All commercial projections below carry explicit `[ESTIMATE]` labels and derive from `src/kerdon/memory.py` (`compute_msp_gtm_economics`):

| Metric | Value | Basis & Reproducing Reference |
|---|---|---|
| **Controller Time Saved** | `14 hrs / client / month` `[ESTIMATE]` | Eliminates manual bill re-keying, 3-doc payroll reconciliation, and spreadsheet commission audits (`490 hrs/mo` across `35` clients). |
| **Labor Cost Saved (35-Client MSP)** | `EUR 17,640 / month` `[ESTIMATE]` | `490 hrs/mo` x `EUR 36/hr` loaded European FinOps/accounting controller cost (`src/kerdon/memory.py`). |
| **Prevented Revenue & Payout Leakage** | `EUR 4,200 / month` `[ESTIMATE]` | Catches uninvoiced principal settlements (`R07`) and blocks stale post-credit-note disbursements (`HTTP 409`). |
| **MSP Fleet Subscription Price** | `EUR 2,990 / month` (`EUR 35,880 / yr`) | Published tier in `GET /gtm/pricing` covering up to `35` client tenants (`EUR 85.43 / tenant / month` wholesale). |
| **Net Buyer ROI** | `7.3x` `[ESTIMATE]` | `(EUR 17,640 + EUR 4,200) / EUR 2,990` monthly value-to-subscription ratio. |
| **MSP Managed-Service Resell Margin** | `66% - 81%` `[ESTIMATE]` | MSP bundles Kerdon MSP (`EUR 85.43/mo` cost per client) into a `EUR 250 - EUR 450/mo` `[ESTIMATE]` Autonomous FinOps & Back-Office retainer. |

---

## 3. Published SaaS Packaging & Bottom-Up $10M ARR Path

### 3.1 Self-Service & AWS Marketplace Tiers (`GET /gtm/pricing`)

| Tier | Monthly Price | Annual Contract Value (ACV) | Target Customer & Included Entitlements |
|---|---|---|---|
| **Entry** | `EUR 49 / mo` | `EUR 588 / yr` | Single SMB entity (`1` organization, `docs@<slug>.kerdon.ai`, double-entry GL, VAT & myDATA/Peppol export). |
| **Pro** | `EUR 149 / mo` | `EUR 1,788 / yr` | Multi-store SMB (`up to 5` stores, seller commissions, 3-doc workforce fusion, Four-Eyes treasury). |
| **MSP & Franchise Fleet** | `EUR 2,990 / mo` | `EUR 35,880 / yr` | AWS MSPs, accounting firms & franchise groups (`up to 35` client tenants, Strands + Bedrock + AgentCore close automation, AWS Marketplace metering). |

### 3.2 External Market Denominators & $10M ARR Arithmetic

- **External Denominator 1 (AWS Partner Channel):** The AWS Partner Network (`https://partners.amazonaws.com/`) encompasses more than `100,000` partner organizations across `150+` countries, including `>3,500` `[ESTIMATE]` AWS Managed Service Providers and cloud financial practices delivering managed billing and back-office operations.
- **External Denominator 2 (European Accounting & Multi-Store Retail):** Eurostat Structural Business Statistics (`https://ec.europa.eu/eurostat`, NACE Rev. 2 `M69.2` accounting/bookkeeping and multi-outlet retail) records `>320,000` `[ESTIMATE]` accounting practices and multi-branch commercial enterprises across the EU-27.
- **Bottom-Up ARR Ladder (`[ESTIMATE]`):**
  - **Milestone 1 (Seed Validation - Month 6):** `15` MSP Fleet accounts (`EUR 538,200` ARR `[ESTIMATE]`) + `60` Pro multi-store accounts (`EUR 107,280` ARR `[ESTIMATE]`) = **`EUR 645,480` ARR `[ESTIMATE]`**.
  - **Milestone 2 (Series A Readiness - Month 18):** `90` MSP Fleet accounts (`EUR 3,229,200` ARR `[ESTIMATE]`) + `250` Pro accounts (`EUR 447,000` ARR `[ESTIMATE]`) = **`EUR 3,676,200` ARR `[ESTIMATE]`**.
  - **Milestone 3 ($10M+ ARR Scale - Month 36):** **`280` MSP & Franchise Fleet customers** (`< 8%` `[ESTIMATE]` of global AWS MSPs or `< 0.09%` `[ESTIMATE]` of EU accounting/franchise firms) x `EUR 35,880 / yr` ACV = **`EUR 10,046,400` ARR (`~$10.8M USD` `[ESTIMATE]`)**.

---

## 4. AWS Marketplace SaaS Architecture & Co-Sell Integration

Kerdon MSP implements AWS Marketplace SaaS subscription resolution and usage metering in [`src/kerdon/gtm_marketplace.py`](../src/kerdon/gtm_marketplace.py) and [`src/kerdon_aws/gtm_routes.py`](../src/kerdon_aws/gtm_routes.py), wired into `infra/template.yaml` (`AWS_MARKETPLACE_PRODUCT_CODE` + `aws-marketplace:ResolveCustomer` and `aws-marketplace:BatchMeterUsage` IAM policies on `WriterFunction`):

1. **SaaS Landing & Token Exchange (`POST /gtm/marketplace/resolve-customer`):**
   - Exchanges `x-amzn-marketplace-token` via `boto3.client("meteringmarketplace").resolve_customer(RegistrationToken=...)` to bind `CustomerIdentifier`, `CustomerAWSAccountId`, and `ProductCode` to the MSP organization.
   - Supports `require_live: true` (`KERDON_REQUIRE_LIVE_MARKETPLACE=1`), failing closed (`HTTP 424` / `RuntimeError`) when live AWS Marketplace credentials or real registration tokens are absent rather than returning silent mocks.
2. **Hourly Usage Metering (`POST /gtm/marketplace/meter-usage`):**
   - Computes deterministic tenant activity quantities in `build_marketplace_metering_batch` and submits `meteringmarketplace.batch_meter_usage` records across three dimensions defined in `MARKETPLACE_DIMENSIONS`:
     - `managed_client_tenants`: Active downstream client organizations managed under the MSP hub.
     - `autonomous_period_closes`: Completed 8-stage Strands + Bedrock + Step Functions period-close runs.
     - `governed_payouts_verified`: Executed treasury payouts sealed with Aletheia Merkle receipts.
3. **APN Co-Sell & AWS Marketplace Private Offers:**
   - Enables enterprise MSPs to procure Kerdon MSP directly against their existing **AWS Enterprise Discount Program (EDP / PPA)** spend commitment via AWS Marketplace Private Offers, compressing procurement cycles from months to days.

---

## 5. Day-1 Customer Onboarding & Production Cutover Runbook

The interactive **GTM & AWS Marketplace SaaS Launchpad** (`GET /#module=billing` and `GET /gtm/readiness`) evaluates a **6-Pillar Production Readiness Matrix** (`evaluate_gtm_readiness` in `src/kerdon/gtm_marketplace.py`):

1. **Pillar 1 - Identity & Multi-Tenant RBAC (`src/kerdon_aws/identity.py`):**
   - Demo stack runs `AuthMode=demo` for zero-login judge inspection; production customer stacks deploy with `--parameter-overrides AuthMode=strict` and Amazon Cognito / OIDC JWT authorizers so spoofed client role headers are ignored and unauthenticated calls return `HTTP 401`.
2. **Pillar 2 - Opening Trial-Balance Cutover (`POST /tenants/{id}/onboarding/opening-balance`):**
   - Imports historical customer receivables (`1100_ACCOUNTS_RECEIVABLE`), supplier payables (`2000_ACCOUNTS_PAYABLE`), cash balances (`1000_CASH_AT_BANK`), and offsetting opening equity (`3000_OPENING_EQUITY`) via `import_opening_trial_balance` in `src/kerdon/gtm_marketplace.py`, enforcing `total_debits == total_credits` before any Day-1 invoice posts.
3. **Pillar 3 - AWS Agentic AI & Compounding Memory (`src/kerdon_aws/bedrock_adapter.py`, `infra/template.yaml`):**
   - Provisions `AWS::BedrockAgentCore::Memory` (`AgentCoreMemory`), `eu.amazon.nova-pro-v1:0` cross-region inference profiles on `EvaluatorFunction`, and `MonthEndCloseStateMachine` on AWS Step Functions.
4. **Pillar 4 - Live External Payment & Statutory Tax Rails (`POST /tenants/{id}/connectors/verify`):**
   - Runtime redacted credential vault (`POST /tenants/{id}/connectors/config`) and live connectivity probe (`verify_tenant_connectors` in `src/kerdon_aws/connectors_adapter.py`) verify PayPal OAuth2 (`/v1/oauth2/token`), AADE myDATA (`aade-user-id` + subscription key), and Peppol BIS 3.0 endpoints with `require_live: true` fail-closed semantics.
5. **Pillar 5 - Durable Zero-Scan Storage & Atomic Unit of Work (`src/kerdon_aws/persistence.py`):**
   - DynamoDB `kerdon-msp-app` and `kerdon-msp-approvals` with Point-in-Time Recovery (`PITR`), SSE encryption, `TransactWriteItems` atomic commits, S3 `14-day` evidence lifecycle rules, and SHA-256 verified tenant backup/restore.
6. **Pillar 6 - AWS Marketplace SaaS Metering (`src/kerdon/gtm_marketplace.py`):**
   - Live `ResolveCustomer` and `BatchMeterUsage` integration for usage-based MSP billing.

---

## 6. 30 / 60 / 90-Day Commercial Execution Roadmap

| Window | Milestone | Concrete Engineering & Commercial Deliverable |
|---|---|---|
| **Days 1 - 30** | **MSP Design-Partner Cutover** | Onboard first `3` MSP / multi-entity accounting partners `[ESTIMATE]` onto isolated `AuthMode=strict` stacks; import opening trial balances via `POST /tenants/{id}/onboarding/opening-balance`; activate inbound Amazon SES email routing (`docs@<slug>.kerdon.ai`). |
| **Days 31 - 60** | **AWS Foundational Technical Review (FTR) & Marketplace Listing** | Complete AWS Partner Network FTR security checklist (`scripts/security_audit.py` `SEC-01..SEC-10` already automated in CI); publish public **Kerdon MSP SaaS Listing** on AWS Marketplace wired to `AWS_MARKETPLACE_PRODUCT_CODE`. |
| **Days 61 - 90** | **Multi-Country EU MSP Co-Sell Expansion** | Expand statutory connector packs beyond `AADE_MYDATA` (Greece) and `PEPPOL_EU` (Germany/EU EN 16931) to UK MTD VAT and Spanish Veri*factu adapters while preserving the unchanged pure hexagonal core (`src/kerdon/`). |

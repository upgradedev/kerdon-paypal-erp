# Devpost Submission Copy: Kerdon PayPal Edition

## Project Title
**Kerdon: Autonomous Agentic Commerce & Governed Double-Entry Mini-ERP on PayPal**

## Tagline
Kerdon turns PayPal checkouts, subscriptions, disputes, and bills into a balanced double-entry ledger, seller commissions, and Four-Eyes governed payouts.

## Inspiration
Multi-store SMB merchants and financial back-offices lose hours and margin every month reconciling PayPal checkouts, unbooked payment processing fees, chargeback disputes, seller commission clawbacks, and manual disbursements. Financial Ops Director **Sofia Marinou** needed an Agentic Commerce workspace that executes real PayPal API workflows and renders CFO-grade financial statements without ever hallucinating a cent in the General Ledger or bypassing payout approvals.

## What It Does
Kerdon connects **8 live PayPal Developer Platform capabilities** (`https://api-m.sandbox.paypal.com`) and a **6-tool Strands + Bedrock AI copilot** to a **19-module double-entry Mini-ERP & AG Grid v33 Financial Studio**:
1. **Strands `@tool` PayPal Commerce Agent (`POST /erp/connectors/paypal/agent`):** Orchestrates 6 executable tools on Amazon Bedrock (`eu.amazon.nova-pro-v1:0`) with persistent audit memory (`AWS::BedrockAgentCore::Memory`).
2. **2-Step Orders v2 + 3-Line Fee GL Reconciliation:** Creates live PayPal `Orders v2` (`checkoutnow?token=...`), blocks unapproved captures fail-closed (`HTTP 502` + `paypal_debug_id`), and books confirmed `seller_receivable_breakdown` (`gross_amount`, `paypal_fee`, `net_amount`) into a balanced 3-line General Ledger entry (`DR 1000_CASH + DR 6200_OPEX = CR 1100_AR`).
3. **Catalog Products v1, Billing Plans v1 & Subscriptions v1:** Provisions live recurring EUR SaaS billing plans (`PROD-...` -> `P-...` -> `I-...`) with subscriber approval links.
4. **Four-Eyes Governed Batch Payouts v1:** Enforces Segregation of Duties (`approver_id != executor_id`), Beneficiary Binding, Mandatory Reserve Floor, and **SHA-256 Changed-Evidence invalidation** (`HTTP 409 Conflict` when late supplier credit notes arrive) before calling `POST /v1/payments/payouts`, sealing Spoken + Grade-1 ASCII Braille Aletheia Merkle receipts.
5. **Customer Disputes v1 + Autonomous Defense Packets + Shipment Tracking v1:** Syncs live PayPal disputes, submits `DHL` fulfillment trackers (`POST /v1/shipping/trackers-batch`), assembles SHA-256 invoice + statutory tax `MARK` defense packets, and posts deterministic seller commission `ClawbackEvent` deductions.
6. **Log in with PayPal (OIDC v1.1) & Webhooks v1:** Links verified merchant `payer_id` identities and registers + signature-verifies PayPal webhook events with replay deduplication.
7. **7-Tab Financial Statements Hub & 4-Way Cent-Exact Reconciliation (`/#module=statements`):** Reconciles Dashboard KPIs (with interactive `i` IFRS/GAAP formula tooltips), Income Statement (`P&L`), Balance Sheet, **IAS 7 Direct-Method Cash Flow Statement**, **Cash & PayPal Account Card (`1000_CASH`)**, Customer & Supplier **`DR`/`CR` Counterparty Account Statements**, Trial Balance, AR/AP Aging, and VAT Return (`F2`).

## Prize Categories & Sponsor Technologies Targeted
- **1st Place & Best Use of PayPal + AI:** Deep integration of 8 live PayPal Sandbox APIs (`Orders v2`, `Subscriptions v1`, `Batch Payouts v1`, `Disputes v1`, `Tracking v1`, `Webhooks v1`, `OAuth 2.0`, `OIDC v1.1`) driven by 6 Strands `@tool` functions on Bedrock Nova Pro with zero-SDK integer-cent ledger verification.
- **Best Use of Agentic Commerce:** Autonomous merchant back-office loop (`Detect -> Reason -> Draft Fix -> Four-Eyes Governed Settlement`) turning raw PayPal payment events and incoming bills into reconciled accounting entries, seller commission clawbacks, and governed payouts.
- **Best Use of AG Grid:** Maximum enterprise utilization of open-source **`ag-grid-community` (`v33.1.1`)** + **`ag-charts-community` (`v11.1.0`)** (`frontend/src/ag_grid_bridge.ts`, `frontend/src/runtime_statements.ts`, `frontend/src/runtime_paypal.ts`):
  - **AI Grid Studio Command Bar:** Natural-language and numeric threshold queries (`> 1000`, `open`, `DR`, `PayPal`, `top`) paired with 1-click Smart Financial View chips and instant CSV export.
  - **Live-Recalculating `pinnedBottomRowData` Double-Entry Totals:** Real-time summation of Debits, Credits, Net Amounts, PayPal Fees (`6200_OPEX`), and Running Balances across the PayPal 3-Line Fee Reconciliation Grid, IAS 7 Cash Flow Statement, Trial Balance, Counterparty `DR`/`CR` Cards, AR/AP Aging, Close Gaps, and Seller Commissions.
  - **Accessible WCAG-AA Quartz Theme:** Custom `themeQuartz` dark/light mode synchronization, right-aligned `tabular-nums` currency formatting, responsive mobile columns (`375px`), and `0` `axe-core` violations.
- **Most Creative:** SHA-256 Changed-Evidence Payout Invalidation (`HTTP 409`), 3-Document Payroll Fusion, and Spoken + ASCII Braille Merkle audit receipts (`AletheiaMerkleReceipt`).

## How We Built It
- **Hexagonal Domain Core (`src/kerdon/`):** Pure Python 3.12 (`29` modules) integer-cent accounting, IAS 7 cash flow & counterparty statement engine (`src/kerdon/statements.py`), 24 completeness rules (`90/90` benchmark accuracy), commissions, and treasury state machines with zero cloud or LLM SDK imports (`Gate A5`).
- **Live PayPal REST & OIDC Adapter (`src/kerdon_aws/paypal_live_client.py`, `src/kerdon_aws/paypal_routes.py`):** Zero-mock HTTPS client against `https://api-m.sandbox.paypal.com` with `PayPal-Request-Id` idempotency and structured `debug_id` error propagation.
- **Agentic Orchestration (`src/kerdon_aws/paypal_agent_tools.py`):** AWS Strands Agents SDK `@tool` functions backed by Amazon Bedrock Nova Pro and Bedrock AgentCore Memory.
- **Enterprise Financial SPA (`frontend/`):** React 18 + TypeScript + Vite 5 + Tailwind CSS 3 + AG Grid v33 + AG Charts v11 served from S3 + CloudFront OAC (`0` `axe-core` violations at `375px` and `1280px`).

## Challenges We Ran Into
- **Preventing LLM Arithmetic Drift & Premature Ledger Mutation:** Live PayPal Orders v2 start in `CREATED` state until buyer wallet approval. We separated order creation (`pending_paypal_orders`) from ledger settlement so GL accounts mutate only when PayPal confirms `COMPLETED` capture breakdown.
- **4-Way Statement & Sub-Ledger Reconciliation:** Guaranteeing that Dashboard tiles, Balance Sheet lines, IAS 7 Cash Flow movements, and individual Customer/Supplier `DR`/`CR` Account Cards match to the exact integer cent across multi-tenant opening balances, PayPal fee splits, and credit-note reversals.

## Accomplishments That We're Proud Of
- `64/64` unit, 4-way reconciliation, and mocked-HTTPS tests, `109/109` local UAT contract checks, `34/34` live PayPal Sandbox E2E verification checks, `10/10` OWASP API Top-10 security controls (`scripts/security_audit.py`), `90/90` ERP benchmark cases, and `0` `axe-core` violations in a 6-stage GitHub Actions CI/CD pipeline.

## Try It Out
- **Live PayPal Agentic Commerce Console:** https://d175u4e48xuu3p.cloudfront.net/#module=paypal
- **Live 7-Tab Financial Statements & AG Grid Studio:** https://d175u4e48xuu3p.cloudfront.net/#module=statements
- **Public MIT Repository:** https://github.com/upgradedev/kerdon-paypal-erp

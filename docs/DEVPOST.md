# Devpost Submission Copy: Kerdon PayPal Edition

## Project Title
**Kerdon: Autonomous Agentic Commerce & Governed Double-Entry Mini-ERP on PayPal**

## Tagline
Kerdon turns PayPal checkouts, subscriptions, disputes, and bills into a balanced double-entry ledger, seller commissions, and Four-Eyes governed payouts.

## Inspiration
Small and multi-store merchants lose hours and margin every month reconciling PayPal checkouts, unbooked payment processing fees, customer disputes, seller commission clawbacks, and manual payouts. Financial Ops Director **Sofia Marinou** needed an AI commerce copilot that executes real PayPal API workflows without ever hallucinating a cent in the General Ledger or bypassing payout approvals.

## What It Does
Kerdon connects **8 live PayPal Developer Platform capabilities** (`https://api-m.sandbox.paypal.com`) to an 18-module double-entry Mini-ERP:
1. **Strands `@tool` PayPal Commerce Agent (`POST /erp/connectors/paypal/agent`):** Orchestrates 6 executable tools on Amazon Bedrock (`eu.amazon.nova-pro-v1:0`) with persistent audit memory (`AWS::BedrockAgentCore::Memory`).
2. **2-Step Orders v2 + 3-Line Fee GL Reconciliation:** Creates live PayPal `Orders v2` (`checkoutnow?token=...`), blocks unapproved captures fail-closed (`HTTP 502` + `paypal_debug_id`), and books confirmed `seller_receivable_breakdown` (`gross_amount`, `paypal_fee`, `net_amount`) into a balanced 3-line General Ledger entry (`DR 1000_CASH + DR 6200_OPEX = CR 1100_AR`).
3. **Catalog Products v1, Billing Plans v1 & Subscriptions v1:** Provisions live recurring SaaS billing plans (`PROD-...` -> `P-...` -> `I-...`) in EUR.
4. **Four-Eyes Governed Batch Payouts v1:** Enforces Segregation of Duties (`approver_id != executor_id`), Beneficiary Binding, Mandatory Reserve Floor, and SHA-256 Changed-Evidence invalidation before calling `POST /v1/payments/payouts`, sealing Spoken + ASCII Braille Aletheia receipts.
5. **Customer Disputes v1 + Autonomous Defense Packets + Shipment Tracking v1:** Syncs live PayPal disputes, submits `DHL` fulfillment trackers (`POST /v1/shipping/trackers-batch`), assembles SHA-256 invoice + tax `MARK` defense packets, and posts deterministic seller commission `ClawbackEvent` deductions.
6. **Log in with PayPal (OIDC v1.1) & Webhooks v1:** Links verified merchant `payer_id` identities and registers + verifies PayPal webhook events with replay deduplication.

## How We Built It
- **Hexagonal Domain Core (`src/kerdon/`):** Pure Python 3.12 integer-cent accounting, 24 completeness rules (`90/90` benchmark accuracy), commissions, and treasury state machines with zero cloud or LLM SDK imports (`Gate A5`).
- **Live PayPal REST & OIDC Adapter (`src/kerdon_aws/paypal_live_client.py`, `src/kerdon_aws/paypal_routes.py`):** Zero-mock HTTPS client against `https://api-m.sandbox.paypal.com` with `PayPal-Request-Id` idempotency and structured `debug_id` error propagation.
- **Agentic Orchestration (`src/kerdon_aws/paypal_agent_tools.py`):** AWS Strands Agents SDK `@tool` functions backed by Amazon Bedrock Nova Pro and Bedrock AgentCore Memory.
- **Accessible SPA (`frontend/src/runtime_paypal.ts`):** React 18 + TypeScript + Vite 5 + Tailwind CSS 3 served from S3 + CloudFront OAC (`0` `axe-core` violations at `375px` and `1280px`).

## Challenges We Ran Into
- **Preventing LLM Arithmetic Drift & Premature Ledger Mutation:** Live PayPal Orders v2 start in `CREATED` state until buyer wallet approval. We separated order creation (`pending_paypal_orders`) from ledger settlement so GL accounts mutate only when PayPal confirms `COMPLETED` capture breakdown.
- **Multi-Lambda Event-Journal Replay Isolation:** Recording `_replay_provider_receipt` envelopes in DynamoDB ensures cold-start `Reader` Lambdas reconstruct exact PayPal state in memory with zero duplicate external API calls.

## Accomplishments That We're Proud Of
- `61/61` unit and mocked-HTTPS tests, `109/109` live UAT contract checks, `10/10` OWASP API Top-10 security controls (`scripts/security_audit.py`), `90/90` ERP benchmark cases, and `0` `axe-core` violations in a 6-stage GitHub Actions CI/CD pipeline.

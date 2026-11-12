![Kerdon PayPal Edition. A checkout connects to an invoice, a three-line journal and a finance workspace.](docs/media/kerdon-paypal-banner.png)

# Kerdon PayPal Edition

**Kerdon turns PayPal checkouts, subscriptions, disputes, and bills into a balanced double-entry ledger, seller commissions, and Four-Eyes governed payouts.**

[![CI](https://github.com/upgradedev/kerdon-paypal-erp/actions/workflows/ci.yml/badge.svg)](https://github.com/upgradedev/kerdon-paypal-erp/actions/workflows/ci.yml)
[![PayPal Sandbox](https://img.shields.io/badge/PayPal-Sandbox-003087?logo=paypal&logoColor=white)](https://developer.paypal.com/tools/sandbox/)
[![Amazon Bedrock](https://img.shields.io/badge/Amazon%20Bedrock-Nova%20Pro-FF9900)](#architecture)
[![AG Grid](https://img.shields.io/badge/AG%20Grid-Community-0769AD)](frontend/package.json)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**[Open PayPal Commerce](https://d175u4e48xuu3p.cloudfront.net/#module=paypal)** · [Financial statements](https://d175u4e48xuu3p.cloudfront.net/#module=statements) · [Try the demo](#try-the-demo) · [Verification](#verification-and-sandbox-boundaries) · [Architecture](#architecture)

Built for the [PayPal AI Hackathon](https://paypalaihackathon.devpost.com/). The public workspace uses synthetic business data and PayPal Sandbox. [Submitted project](https://devpost.com/software/kerdon-paypal-edition) · [Final demo with English captions](https://www.youtube.com/watch?v=WmzaWJCReQg)

[Problem](#the-problem) · [Checkout flow](#how-a-checkout-becomes-a-journal) · [Build and test](#build-and-test) · [Docs and license](#documentation-and-license)

## The problem

Sofia Marinou, a finance operations director for a multi-store merchant, needs to tie each customer payment to the right invoice and explain the difference between gross sales and net cash. When fees, approvals and settlement records live in different systems, that reconciliation becomes a manual close task.

Kerdon links PayPal order and capture IDs to the invoice, then uses the provider's capture breakdown to clear receivables and post cash and fees in integer cents. A Strands agent on Amazon Bedrock Nova Pro can call PayPal tools from the same workspace. PayPal controls buyer authorization and returns provider status. The accounting core validates and posts the journal.

## Try the demo

To inspect the filmed proof without signing in, open PayPal Commerce and filter settlements to `5V401147JW927470T`. Open its GL Event and linked invoice. If needed, include November 12, 2026 in the accounting date range. In Recurring SaaS Subscriptions, find `I-20GWDNPS6BVM` marked `ACTIVE` at €1.00 per month. [Checkout demo](https://www.youtube.com/watch?v=WmzaWJCReQg&t=18s) · [Subscription and signed webhook](https://www.youtube.com/watch?v=WmzaWJCReQg&t=119s)

To exercise a fresh order in Sandbox:

1. Open **[PayPal Commerce](https://d175u4e48xuu3p.cloudfront.net/#module=paypal)** and choose **Verify Live OAuth2 Scopes** to check the sandbox connection.
2. Replace the suggested agent goal with **Inspect the Sandbox connection and summarize the account. Only use the status tool.** Choose **Run PayPal Strands Agent** and inspect the engine, tool results and provider mode.
3. Choose **Create Live Order v2** to create a sandbox order from an open invoice. The order row shows its PayPal ID and approval link. **Sync Status** reads the provider state.

The hosted workspace opens without a Kerdon account. To exercise the capture path, approve the order through **Approve on PayPal Sandbox** with a PayPal Sandbox buyer account, return to Kerdon and choose **Capture -> GL** on that order. Inspect the net cash, PayPal fee and cleared receivable in the commerce workspace, then open [Financial statements](https://d175u4e48xuu3p.cloudfront.net/#module=statements). The workspace also includes sample reconciled entries for exploring the grids without buyer credentials.

With the deployed merchant's Sandbox credentials in your shell, run `python scripts/verify_paypal_checkout.py ORDER_ID` to compare the provider's capture with the deployed settlement and journal. The check reads both systems and fails if either side is incomplete or the amounts differ.

## How a checkout becomes a journal

```mermaid
sequenceDiagram
    actor Operator
    actor Buyer
    participant K as Kerdon Commerce
    participant PP as PayPal Sandbox
    participant GL as Accounting core
    Operator->>K: Create order for an open invoice
    K->>PP: Create Orders v2 resource
    PP-->>K: Order ID and approval link
    Buyer->>PP: Approve with sandbox buyer account
    Operator->>K: Request capture for that order
    K->>PP: Capture order
    alt PayPal confirms capture
        PP-->>K: Capture ID, gross, fee and net
        K->>GL: Validate and post capture
        GL-->>Operator: Balanced journal and capture reference
    else PayPal rejects capture
        PP-->>K: Issue code and debug ID
        K-->>Operator: Provider error without a capture posting
    end
```

A confirmed capture debits **cash** for the net amount and **processing expense** for the fee. It credits **accounts receivable** for the gross amount. AG Grid shows the split, filters, totals and CSV export. The statements workspace reads the same ledger for the trial balance, cash flow and account cards.

## Verification and sandbox boundaries

| Surface | Evidence and scope |
|---|---|
| **Hosted release** | [Deployed SHA](https://d175u4e48xuu3p.cloudfront.net/DEPLOYED_SHA), [runtime source at `4e444aa`](https://github.com/upgradedev/kerdon-paypal-erp/tree/4e444aad477e454344587fa72f0acc1051c13273) and [successful CI run](https://github.com/upgradedev/kerdon-paypal-erp/actions/runs/43196277057). Documentation can be updated independently of the runtime release. |
| **Checkout** | PayPal Sandbox order `5V401147JW927470T` completed with capture `3PC343616J2263823`. Kerdon posted €95.75 cash and €4.25 fees against €100.00 receivables. The linked invoice shows €0 outstanding. A separate premature capture returned `ORDER_NOT_APPROVED` and left the ledger unchanged. Sample rows are labeled as fixtures. |
| **Subscriptions and webhooks** | A Personal Sandbox buyer approved `I-20GWDNPS6BVM` at €1.00 per month. PayPal and Kerdon both returned `ACTIVE`, and the deployed listener recorded signature verification `SUCCESS` for event `WH-9S05637553950283G-0J356622ME680244H`. Collection in a later billing cycle remains unverified. |
| **Agent tools** | The hosted writer can run six Strands tools for inspection, checkout, subscriptions, webhooks and governed payouts. The response includes the engine, provider mode, tool results and AgentCore Memory audit status. A deterministic fallback has a separate engine label. |
| **AG Grid** | The workspace label **AG Grid Studio** refers to the Kerdon views built with AG Grid Community. The filmed settlement is filtered by order ID and exported to CSV. |
| **Payouts and disputes** | Payouts check role separation, evidence and available balance before a provider request. The observed Sandbox rejection was `INSUFFICIENT_FUNDS`. Dispute sync returned HTTP 200 with zero cases. The workspace prepares evidence for review. Provider evidence submission and case outcome remain unverified. |
| **Provider boundaries** | The PayPal integration targets Sandbox. Invoicing v2 payloads are previews. The public workspace uses demo identities and synthetic records. Use only sandbox accounts and sample data. |

## Architecture

```mermaid
flowchart LR
    Browser["React workspace and AG Grid"] --> Edge["CloudFront"]
    Edge --> Web["Private S3 frontend"]
    Edge --> API["API Gateway HTTP API"]
    API --> Read["Reader Lambda"]
    API --> Eval["Evaluator Lambda"]
    API --> Write["Writer Lambda"]
    Read --> DB["DynamoDB journal and approvals"]
    Eval --> Nova["Amazon Bedrock Nova Pro"]
    Write --> Tools["Strands Commerce tools"]
    Tools --> Nova
    Tools --> Memory["Bedrock AgentCore Memory"]
    Write --> Adapter["PayPal HTTPS adapter"]
    Tools --> Adapter
    Adapter --> PayPal["PayPal Sandbox"]
    Write --> Core["Deterministic Python accounting"]
    Tools --> Core
    Write --> DB
    Write --> Evidence["Private S3 evidence"]
```

The [PayPal adapter](src/kerdon_aws/paypal_live_client.py) owns OAuth and provider requests. The [commerce tools](src/kerdon_aws/paypal_agent_tools.py) call that adapter and the domain core. The [SAM template](infra/template.yaml) defines the deployment, including the three Lambda roles and the journal.

## Build and test

Use **Python 3.11+**. The local backend uses Python's standard library with synthetic fixtures.

```bash
git clone https://github.com/upgradedev/kerdon-paypal-erp.git
cd kerdon-paypal-erp
python scripts/verify_gates.py
python scripts/run_erp_benchmark.py
python scripts/serve_local.py 8080
```

Open [http://127.0.0.1:8080/](http://127.0.0.1:8080/) for the local workspace or check [local health](http://127.0.0.1:8080/health). With Sandbox credentials absent, the local connector reports `paypal-sandbox-simulated`. For the full React build, use Node.js 20+ and run `npm --prefix frontend ci` followed by `npm --prefix frontend run build`. CI builds and serves that bundle through the deployment defined in SAM.

For the Python tests, set `PYTHONPATH=src` and run `python -m unittest discover -s tests -v`. Keep `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` unset for offline tests. Supply your own Sandbox credentials through the server environment or CI secrets when exercising the real connector.

## Documentation and license

- [High-level design](docs/HLD.md) covers data, permissions and provider boundaries.
- [ERP workspace reference](docs/ERP_WORKSPACE.md) lists the user journeys, routes and deployment requirements.
- [Devpost submission copy](docs/DEVPOST.md) describes the hackathon entry.
- [MIT license](LICENSE) covers the original source and documentation.

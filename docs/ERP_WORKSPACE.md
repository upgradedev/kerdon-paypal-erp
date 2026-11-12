# PayPal ERP workspace reference

**Kerdon turns PayPal checkouts, subscriptions, disputes, and bills into a balanced double-entry ledger, seller commissions, and Four-Eyes governed payouts.**

Sofia Marinou uses the [PayPal Commerce workspace](https://d175u4e48xuu3p.cloudfront.net/#module=paypal) to open a checkout from an invoice and review the provider response. The [Financial statements workspace](https://d175u4e48xuu3p.cloudfront.net/#module=statements) shows the cash account, receivables, trial balance, cash flow and account statements from the same ledger.

## Hosted walkthrough

1. Choose **Verify Live OAuth2 Scopes**. The connector reports whether PayPal Sandbox credentials are active.
2. Run **PayPal Strands Agent** with the goal `Inspect the Sandbox connection and summarize the account. Only use the status tool.` Read the engine and tool trace.
3. Choose **Create Live Order v2**. Use **Sync Status** to read the created order's provider state. Approval happens in PayPal Sandbox, using a Sandbox buyer account.
4. After approval, select **Capture -> GL** for that order. A confirmed capture posts net cash and processing expense against gross receivables. Sample reconciled rows are available for inspection without buyer approval.

The live agent created an order that was still pending buyer approval at verification. The hosted experience also shows sample capture entries. A distinct pre-approval test verified `ORDER_NOT_APPROVED` without a settlement posting.

## API routes

The CloudFront origin is the easiest starting point. The HTTP API also serves the application under `/Prod/`. The canonical UI path is `/`. The old `/workspace` and `/cockpit` paths redirect there.

| Method and route | Behavior |
|---|---|
| `GET /health`, `GET /DEPLOYED_SHA` | Service health and deployed commit. |
| `GET /erp/operations`, `GET /erp/connectors` | Organization records, statements, connector mode and PayPal views. |
| `POST /erp/connectors/verify` | Checks connector readiness. Pass `require_live: true` to require configured provider access. |
| `POST /erp/connectors/paypal/agent` | Accepts a goal and returns tool results, runtime mode and audit status. Some tools create Sandbox resources. |
| `POST /erp/connectors/paypal/order` | Creates an order from `document_id`. Use `auto_capture: false` for the explicit buyer approval flow. |
| `POST /erp/connectors/paypal/order-status` | Reads the PayPal status for `order_id`. |
| `POST /erp/connectors/paypal/capture` | Captures an approved order. Pass its `order_id` and linked `document_id`. A provider failure returns a structured error. |
| `POST /erp/connectors/paypal/subscription` | Creates a Sandbox product, plan and subscription approval link. |
| `POST /erp/connectors/paypal/webhooks/register`, `POST /erp/connectors/paypal/webhook` | Registers a provider webhook and processes incoming events through a separate route. |
| `POST /erp/connectors/paypal/disputes/sync` | Reads disputes from PayPal Sandbox. |
| `POST /erp/treasury/approvals`, `POST /erp/connectors/paypal/payout` | Creates an approval and requests provider payout after treasury preflight. |
| `POST /erp/ai/extract-document` | Uses the Evaluator to enrich document text. Integer-cent calculation remains in the domain. |

## Build, test and deploy

Use Python 3.11 or newer. The local server defaults to synthetic data and simulated PayPal when Sandbox credentials are absent. Run from the repository root.

```bash
python scripts/verify_gates.py
python scripts/run_erp_benchmark.py
python scripts/serve_local.py 8080
```

The local workspace is at [http://127.0.0.1:8080/](http://127.0.0.1:8080/). Set `PYTHONPATH=src` to run the unit suite with `python -m unittest discover -s tests -v`. Keep `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` unset for offline tests.

The [CI workflow](../.github/workflows/ci.yml) builds the React frontend and deploys the [SAM template](../infra/template.yaml). A standalone deployment requires an AWS deployment role and PayPal Sandbox app credentials. Browser UAT writes synthetic data, so run it on a test environment you control.

## Scope of the demo

The public deployment uses demo-role fixtures. Treat it as a shared Sandbox workspace. A private customer deployment needs an identity provider, membership configuration and operational review. Invoicing v2 is previewed locally. A successful webhook registration establishes the subscription, while webhook delivery and verification are separate checks. Sandbox payout approval can remain valid if PayPal rejects the request for insufficient funds.

[Architecture](HLD.md) · [Merchant onboarding notes](GTM_PLAYBOOK.md) · [Deployed SHA](https://d175u4e48xuu3p.cloudfront.net/DEPLOYED_SHA)
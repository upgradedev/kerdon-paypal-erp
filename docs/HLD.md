# High-level design

**Kerdon turns PayPal checkouts, subscriptions, disputes, and bills into a balanced double-entry ledger, seller commissions, and Four-Eyes governed payouts.**

For Sofia Marinou, the record of a payment must tie together a PayPal ID, an ERP invoice and balanced journal lines. The PayPal edition runs on the `kerdon-paypal-dev` stack in `eu-west-1`. The [public workspace](https://d175u4e48xuu3p.cloudfront.net/#module=paypal) uses Sandbox and synthetic business records.

## Components and trust boundaries

```mermaid
flowchart TB
    UI["React and AG Grid workspace"] --> CDN["CloudFront"]
    CDN --> WEB["Private S3 web assets"]
    CDN --> API["API Gateway HTTP API"]
    API --> R["Reader Lambda"]
    API --> E["Evaluator Lambda"]
    API --> W["Writer Lambda"]
    R --> DB["DynamoDB app journal and approval table"]
    E --> N["Bedrock Nova Pro"]
    E --> M["Bedrock AgentCore Memory"]
    W --> S["Strands commerce tools"]
    W --> P["PayPal HTTPS adapter"]
    S --> N
    S --> M
    S --> P
    P --> PP["PayPal Sandbox"]
    W --> K["Python domain and ledger"]
    S --> K
    W --> DB
    W --> EV["Private S3 evidence"]
```

| Component | Responsibility |
|---|---|
| [PayPal HTTPS adapter](../src/kerdon_aws/paypal_live_client.py) | Obtains OAuth tokens, calls provider endpoints and returns structured results with resource IDs or a PayPal issue and debug ID. |
| [Strands commerce tools](../src/kerdon_aws/paypal_agent_tools.py) | Exposes inspection, checkout, subscription, webhook and payout tools. The response includes the runtime mode, tool results and audit-memory status. |
| [Accounting domain](../src/kerdon/) | Validates invoice, ledger, treasury and commission rules. Monetary arithmetic uses integer cents. The model operates through tools and does not author journal amounts. |
| [Persistence adapter](../src/kerdon_aws/persistence.py) | Reads and writes the DynamoDB journal and approval records. Supported replay paths rebuild state from recorded provider results. Evidence bytes are stored in S3. |
| [SAM deployment](../infra/template.yaml) | Separates Reader, Evaluator and Writer roles. CloudFront serves the web bundle from private S3 and routes API requests to API Gateway. |

## Order and capture

```mermaid
sequenceDiagram
    actor Operator
    actor Buyer
    participant W as Kerdon writer
    participant P as PayPal Sandbox
    participant L as Accounting domain
    Operator->>W: Choose invoice and create order
    W->>P: Create Orders v2 resource
    P-->>W: Order ID and buyer approval link
    W-->>Operator: Pending order
    Buyer->>P: Approve checkout
    Operator->>W: Capture the same order
    W->>P: Capture Orders v2 resource
    alt Confirmed capture
        P-->>W: Capture ID and settlement breakdown
        W->>L: Validate and apply payment to invoice
        L-->>Operator: Net cash and fee debits, gross receivable credit
    else Provider rejection
        P-->>W: Issue and debug ID
        W-->>Operator: Failure with no settlement posting
    end
```

Creating an order persists its provider reference without clearing the invoice. The capture path reads the PayPal settlement breakdown and posts the journal against the linked invoice. PayPal request IDs and the recorded capture reference support safe retry handling. Automated tests cover successful and repeated capture responses. In the filmed Sandbox run, the agent created order `5V401147JW927470T`, the buyer approved it and PayPal confirmed capture `3PC343616J2263823`. [Final demo](https://www.youtube.com/watch?v=WmzaWJCReQg) · [Checkout tests](../tests/test_paypal_live_suite.py)

## Payouts, disputes and subscriptions

- **Payouts.** Treasury preflight checks approval state, evidence, actor separation, beneficiary and reserve floor before the Sandbox request. A late credit note can invalidate a pending approval. The observed Sandbox response was `INSUFFICIENT_FUNDS`, and the approval remained valid for review.
- **Disputes.** The connector reads the provider's dispute list. The Sandbox query returned HTTP 200 with zero cases. The workspace prepares evidence and related commission adjustments for review. Provider submission and dispute outcome remain unverified.
- **Subscriptions and webhooks.** After Sandbox buyer approval, PayPal returned `ACTIVE` for subscription `I-20GWDNPS6BVM`. PayPal and the deployed Kerdon journal recorded the same `BILLING.SUBSCRIPTION.ACTIVATED` event. The listener verified the signature with PayPal and recorded `SUCCESS` before updating the subscription in Kerdon. Collection in a later cycle remains unverified.
- **Invoicing.** The adapter can build an Invoicing v2 preview payload. The checkout flow uses Orders v2.

## Deployment and verification

The public stack uses demo identities. Hosted review therefore uses Sandbox accounts and synthetic data. A customer deployment requires an authenticated identity provider and server-side membership enforcement. PayPal credentials are passed to CloudFormation as `NoEcho` parameters from CI secrets. The template configures separate app and approval tables, private evidence storage and AgentCore Memory.

The table records design controls relevant to the listed AI Act topics and the deployment work that remains.

| Topic | Design control | Remaining work |
|---|---|---|
| Article 10, data governance | Sample business records and content hashes for evidence. | Define production data sources, access and retention. |
| Article 13, transparency | Engine and provider mode in the tool response. | Carry that provenance into external-facing exports where appropriate. |
| Article 14, human oversight | PayPal buyer approval and treasury preflight. | Bind production reviewers to authenticated identities. |
| Article 15, accuracy and resilience | Integer-cent checks, provider error handling and automated regression tests. | Measure production behavior under concurrent load and provider failures. |
| Article 50, transparency of generated content | Agent narration is presented with its engine and tool results. | Review how generated text is labelled when shared outside the workspace. |

[Deployment and test commands](ERP_WORKSPACE.md) · [Hosted release evidence](https://github.com/upgradedev/kerdon-paypal-erp/actions/runs/43196277057)

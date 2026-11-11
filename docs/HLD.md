# High-Level Design (HLD): Kerdon PayPal Edition

## 1. Architectural Principles

1. **Deterministic Ledger Authority (`Gate A5`):** `src/kerdon/` owns all accounting, tax, commission, and treasury math in integer cents and imports zero network, clock, cloud, or LLM libraries.
2. **Fail-Closed Upstream PayPal Integration:** `src/kerdon_aws/paypal_live_client.py` communicates over HTTPS with `https://api-m.sandbox.paypal.com`. Upstream rejections (`ORDER_NOT_APPROVED`, `INSUFFICIENT_FUNDS`) raise `ExternalProviderError` (`HTTP 502`) carrying PayPal's `debug_id` and `issue` code while leaving General Ledger balances and `VALID` treasury approvals untouched.
3. **Least-Privilege Three-Role Compute (`Gate A7`):** Separate `ReaderFunction`, `EvaluatorFunction`, and `WriterFunction` AWS Lambda roles (`infra/template.yaml`) isolate read queries, non-mutating AI evaluations, and governed state mutations.

---

## 2. Hexagonal Component Topology

```mermaid
flowchart TD
    subgraph Edge["CloudFront CDN & S3 OAC"]
        SPA["React 18 + TypeScript SPA (frontend/src/runtime_paypal.ts)"]
    end
    subgraph Compute["AWS HTTP API v2 + 3-Role Lambda Separation"]
        RD["ReaderFunction (DynamoDBReadPolicy)"]
        EV["EvaluatorFunction (Bedrock + AgentCore Read/Record)"]
        WR["WriterFunction (Governed Mutations + Strands @tool)"]
    end
    subgraph Domain["Pure Hexagonal Core (src/kerdon/)"]
        GL["Double-Entry GL (ledger.py)"]
        TR["Four-Eyes Treasury (treasury.py)"]
        CM["Commissions & Clawbacks (commissions.py)"]
        PPD["PayPal Domain Schemas (paypal_schema.py, connectors.py)"]
    end
    subgraph External["Live External Services"]
        PPSB["PayPal Sandbox (api-m.sandbox.paypal.com)"]
        BED["Amazon Bedrock (eu.amazon.nova-pro-v1:0)"]
        ACM["Bedrock AgentCore Memory"]
        DDB["DynamoDB (kerdon-paypal-app / approvals)"]
    end
    SPA --> RD
    SPA --> EV
    SPA --> WR
    WR --> Domain
    WR --> PPSB
    WR --> BED
    WR --> ACM
    WR --> DDB
    RD --> DDB
```

---

## 3. PayPal Agentic Tool & Four-Eyes Payout Sequence

```mermaid
sequenceDiagram
    participant Dir as Sofia Marinou (Approver)
    participant Exe as Treasury Officer (Executor)
    participant WR as WriterFunction (paypal_routes.py)
    participant TR as Treasury Guard (treasury.py)
    participant PP as PayPal Payouts v1

    Dir->>WR: Approve Commission Case (approver_id = act-sofia-marinou)
    WR->>TR: Seal Approval + SHA-256 Evidence Digest (state = VALID)
    Exe->>WR: POST /erp/connectors/paypal/payout (executor_id = act-nikos-alexiou)
    WR->>TR: Verify Four-Eyes, Beneficiary Email, Reserve Floor & Evidence Hash
    WR->>PP: POST /v1/payments/payouts (PayPal-Request-Id)
    alt Wallet Funded (201 CREATED)
        PP-->>WR: payout_batch_id + batch_status
        WR->>PP: GET /v1/payments/payouts/{payout_batch_id}
        WR->>TR: Mark Approval EXECUTED + Mint Spoken/Braille Receipt
    else Provider Rejection (422 INSUFFICIENT_FUNDS)
        PP-->>WR: 422 + debug_id
        WR-->>Exe: HTTP 502 Fail-Closed (Approval remains VALID, zero GL drift)
    end
```

---

## 4. Security, Replay Isolation & Accessibility

- **Secret Hygiene:** `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` are injected as `NoEcho: true` CloudFormation parameters (`infra/template.yaml`) from encrypted GitHub Actions Secrets and never exposed in client payloads; `SEC-01`..`SEC-10` (`scripts/security_audit.py`) plus `Bandit` and `pip-audit` run on every push.
- **Journal Replay Determinism:** Every mutating PayPal route records `_replay_provider_receipt` in the DynamoDB event journal (`src/kerdon_aws/paypal_routes.py`), guaranteeing zero outbound PayPal or Bedrock calls during cross-Lambda state hydration (`tests/test_kerdon_aws.py`, `tests/test_paypal_live_suite.py`).
- **Accessibility & EU AI Act Controls:** Verified `0` `axe-core` violations across mobile (`375px`) and desktop (`1280px`) viewports (`scripts/browser_qa.py`), keyboard-focusable `.table-wrap` regions, Spoken + ASCII Braille payout receipts, and full alignment with EU AI Act Article 10, Article 13, Article 14, Article 15, and Article 50.

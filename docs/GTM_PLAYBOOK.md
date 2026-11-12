# Merchant onboarding and pilot

**Kerdon turns PayPal checkouts, subscriptions, disputes, and bills into a balanced double-entry ledger, seller commissions, and Four-Eyes governed payouts.**

## Intended users

Sofia Marinou, a finance operations director at a multi-store merchant, owns cash reconciliation and has to explain discrepancies between sales invoices, PayPal settlements and merchant fees. The initial workflow is review of one store's invoices and PayPal settlement entries in a single workspace.

## A Sandbox pilot

1. Start in an isolated organization with synthetic open invoices and a known starting ledger balance. Use a separate PayPal Sandbox business account and buyer account for the pilot.
2. Create an order for an open invoice, check the PayPal order ID and complete buyer approval before attempting capture.
3. Reconcile the provider's gross, fee and net amounts against the journal and account statement. Repeat the capture request in a test environment to check duplicate protection.
4. Record the provider issue and debug ID for a rejected capture. Verify that open receivables stay unchanged. A payout test needs separate reviewers, a valid approval and Sandbox funding.
5. Export the sample records and compare the reconciliation with the team's current workflow.

Track elapsed reconciliation time, unmatched invoice count, duplicate posting attempts and unexplained fee variance for the same set of transactions in both workflows. Use those measurements to establish a baseline before estimating savings or setting a service target.

## Production prerequisites

Provision private identity and organization membership, configure provider credentials and webhook signing for the intended environment, and validate opening balances and beneficiary controls. Rehearse backup and recovery, retries, simultaneous approvals and provider outages with a controlled ledger. The hosted hackathon application is a shared Sandbox with demo identities and synthetic data.

[Workspace walkthrough](ERP_WORKSPACE.md) · [High-level design](HLD.md)
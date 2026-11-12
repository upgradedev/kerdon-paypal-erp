# Kerdon PayPal Edition

**Kerdon turns PayPal checkouts, subscriptions, disputes, and bills into a balanced double-entry ledger, seller commissions, and Four-Eyes governed payouts.**

## Inspiration

Sofia Marinou, a finance operations director for a multi-store merchant, needs to know which invoices PayPal has settled and why the cash received differs from the amount billed. A checkout, a buyer approval and a settlement are different events. Keeping those events straight across stores takes time and leaves room for duplicate or premature postings.

## What it does

Kerdon puts the PayPal order, its linked invoice and the eventual accounting entry in one workspace. A Strands agent on Amazon Bedrock Nova Pro can inspect the PayPal Sandbox connection and use tools to create a checkout, check an order or request a capture. The buyer authorizes the checkout in PayPal Sandbox. A confirmed capture provides the gross amount, processing fee and net cash used by the accounting engine.

The journal debits cash for the net amount, debits expenses for the fee and credits accounts receivable for the gross amount. AG Grid shows the amounts and totals beside the provider reference. The same ledger drives the statements workspace. For payouts, the application checks approval, beneficiary and liquidity before making a provider request.

## What we verified

- **Live Sandbox and AI.** The Strands agent created order `5V401147JW927470T` for a €100.00 invoice. After buyer approval, PayPal confirmed capture `3PC343616J2263823`. A separate premature capture returned `ORDER_NOT_APPROVED` and left the ledger unchanged.
- **Accounting.** The live journal `ev-pp-cap-5v401147jw927470t` debits €95.75 cash and €4.25 processing expense against €100.00 receivables. The linked invoice shows €0 outstanding. AG Grid Community filters and exports the same settlement.
- **Subscription activation.** PayPal and Kerdon both report `ACTIVE` for the buyer-approved €1.00 monthly Sandbox subscription `I-20GWDNPS6BVM`. The deployed listener verified event `WH-9S05637553950283G-0J356622ME680244H` with `SUCCESS`. Collection in a later billing cycle remains unverified.
- **Disputes and payouts.** The live Sandbox dispute list returned HTTP 200 with zero cases. Evidence packets are prepared in Kerdon for review. Provider evidence submission and case outcome remain unverified. The observed Sandbox payout attempt returned `INSUFFICIENT_FUNDS`.
- **Release verification.** The CI run for runtime `4e444aa` includes unit, API, live Sandbox and browser checks. Automated accessibility checks cover the exercised mobile and desktop views. [Release run](https://github.com/upgradedev/kerdon-paypal-erp/actions/runs/43196277057)

[Submitted project](https://devpost.com/software/kerdon-paypal-edition) · [Final demo](https://www.youtube.com/watch?v=WmzaWJCReQg) · [Runtime source](https://github.com/upgradedev/kerdon-paypal-erp/tree/4e444aad477e454344587fa72f0acc1051c13273)

## How we built it

The PayPal HTTPS adapter owns provider calls and passes status, IDs and errors back to the workspace. Strands supplies the tool calls, Bedrock Nova Pro interprets the goal and the response reports AgentCore Memory audit status. Python domain code validates and posts money in integer cents. The React workspace uses AG Grid Community for filtering, tabular review, pinned totals and CSV export. CloudFront, API Gateway, Lambda, DynamoDB and S3 host the demo. [Architecture](HLD.md)

## Hackathon work

The PayPal edition builds on Kerdon's accounting, treasury and invoice workflows. The hackathon work adds the standalone PayPal Sandbox deployment, provider-backed order and capture handling, the commerce agent tools, and the PayPal Commerce and AG Grid review surfaces. The public edition ships under MIT. [Repository and testing instructions](https://github.com/upgradedev/kerdon-paypal-erp)

The PayPal and AI entry focuses on an agent taking a concrete checkout action with provider evidence. AG Grid is used to inspect, filter and export the resulting financial data. [Official prize categories](https://paypalaihackathon.devpost.com/rules)

## Try it

Open [PayPal Commerce](https://d175u4e48xuu3p.cloudfront.net/#module=paypal), run **Verify Live OAuth2 Scopes**, and use the agent or **Create Live Order v2** to inspect a provider-backed order. Try the [financial statements](https://d175u4e48xuu3p.cloudfront.net/#module=statements) with the supplied sample entries. Capturing a newly created order requires a PayPal Sandbox buyer account. The hosted workspace uses synthetic business data.

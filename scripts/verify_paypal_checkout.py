"""Verify a completed PayPal Sandbox checkout against its deployed Kerdon journal."""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kerdon import AccountCode  # noqa: E402
from kerdon_aws.paypal_live_client import PayPalConnectorPlugin  # noqa: E402


SANDBOX = "https://api-m.sandbox.paypal.com"
JUDGE_URL = "https://d175u4e48xuu3p.cloudfront.net"


def read_erp(path: str, tenant: str) -> dict:
    headers = {"x-active-tenant": tenant} if tenant else {}
    request = Request(JUDGE_URL + path, headers=headers)
    with urlopen(request, timeout=20) as response:  # nosec B310
        return json.load(response)


def cents(money: dict, currency: str) -> int:
    value = Decimal(money["value"]) * 100
    if money["currency_code"] != currency or not value.is_finite() or value < 0 or value != int(value):
        raise ValueError("PayPal returned an invalid amount or currency")
    return int(value)


def verify(order_id: str, tenant: str) -> dict:
    provider = PayPalConnectorPlugin(base_url=SANDBOX)
    if not provider.is_live_configured:
        raise ValueError("Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET for PayPal Sandbox")
    order = provider.get_order(order_id)
    if order.get("status") != "COMPLETED":
        raise ValueError(f"PayPal order status is {order.get('status')}")
    unit, = order["purchase_units"]
    capture, = unit["payments"]["captures"]
    if order["id"] != order_id or capture["status"] != "COMPLETED":
        raise ValueError("PayPal order or capture is inconsistent")
    currency = capture["amount"]["currency_code"]
    amounts = capture["seller_receivable_breakdown"]
    gross = cents(amounts["gross_amount"], currency)
    fee = cents(amounts["paypal_fee"], currency)
    net = cents(amounts["net_amount"], currency)
    if gross != fee + net or cents(capture["amount"], currency) != gross:
        raise ValueError("PayPal gross, fee and net do not reconcile")

    connectors = read_erp("/erp/connectors", tenant)
    matches = [record for record in connectors["paypal"]["orders"] if record["order_id"] == order_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one Kerdon settlement, found {len(matches)}")
    settlement = matches[0]
    expected = (capture["id"], unit["reference_id"], currency, gross, fee, net, "paypal-sandbox-live")
    actual = tuple(settlement[key] for key in (
        "capture_id", "document_id", "currency", "gross_cents", "paypal_fee_cents",
        "net_settled_cents", "provider_mode",
    ))
    if actual != expected:
        raise ValueError("Kerdon settlement does not match PayPal's receipt")

    event_id = settlement["journal_event_id"]
    events = read_erp("/erp/full-state", tenant)["ledger_events"]
    journal, = (event for event in events if event["event_id"] == event_id)
    postings = sorted((line["account"], line["debit_cents"], line["credit_cents"]) for line in journal["lines"])
    expected_lines = [(AccountCode.CASH_1000.value, net, 0), (AccountCode.AR_1100.value, 0, gross)]
    if fee:
        expected_lines.append((AccountCode.OPEX_GENERAL_6200.value, fee, 0))
    if (
        postings != sorted(expected_lines)
        or journal["source_document_id"] != unit["reference_id"]
        or journal["currency"] != currency
    ):
        raise ValueError("Kerdon journal does not match the expected accounts and amounts")
    return {
        "deployed_sha": read_erp("/DEPLOYED_SHA", tenant)["deployed_sha"],
        "provider": "PayPal Sandbox",
        "status": capture["status"],
        "order_id": order_id,
        "capture_id": capture["id"],
        "document_id": settlement["document_id"],
        "currency": currency,
        "gross_cents": gross,
        "fee_cents": fee,
        "net_cents": net,
        "journal_event_id": event_id,
        "journal_postings": postings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("order_id")
    parser.add_argument("--tenant", default="", help="Kerdon demo organization ID, if not the default")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9-]{1,36}", args.order_id):
        parser.error("invalid PayPal order ID")
    try:
        print(json.dumps(verify(args.order_id, args.tenant), indent=2))
    except Exception as exc:
        parser.exit(1, f"Checkout verification failed: {exc}\n")


if __name__ == "__main__":
    main()

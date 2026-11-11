"""Unit & Mocked-HTTPS Coverage Suite for PayPal Developer Platform Adapter & Strands Agent."""
from __future__ import annotations

import io
import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

import kerdon as kd
import kerdon_aws as kaws
from kerdon_aws.connectors_adapter import reset_connector_runtime_secrets
from kerdon_aws.paypal_live_client import ExternalProviderError, PayPalConnectorPlugin, parse_money_cents


class _FakeHttpResponse:
    def __init__(self, payload: dict, status: int = 200, debug_id: str = "dbg-test-001") -> None:
        self._bytes = json.dumps(payload).encode("utf-8")
        self.status = status
        self.headers = {"Paypal-Debug-Id": debug_id}

    def read(self) -> bytes:
        return self._bytes

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _make_http_error(code: int, issue: str, desc: str, debug_id: str = "dbg-err-999") -> urllib.error.HTTPError:
    body = json.dumps(
        {
            "name": issue,
            "message": desc,
            "debug_id": debug_id,
            "details": [{"issue": issue, "description": desc}],
        }
    ).encode("utf-8")
    return urllib.error.HTTPError(
        url="https://api-m.sandbox.paypal.com/test",
        code=code,
        msg=desc,
        hdrs=MagicMock(),
        fp=io.BytesIO(body),
    )


class TestPayPalLiveSuite(unittest.TestCase):
    def setUp(self) -> None:
        kd.reset_connector_states()
        reset_connector_runtime_secrets()
        self.store = kaws.MultiTenantStore()
        self.tid = self.store.workspace.default_tenant_id

    def test_parse_money_cents_and_live_plugin_all_endpoints(self) -> None:
        self.assertEqual(parse_money_cents({"currency_code": "EUR", "value": "1240.35"}), 124_035)
        self.assertEqual(parse_money_cents({"value": "bad"}, 99), 99)
        self.assertIsNone(parse_money_cents(None, None))

        plugin = PayPalConnectorPlugin(
            client_id="live-cid-test",
            client_secret="live-csec-test",
            base_url="https://api-m.sandbox.paypal.com",
        )
        self.assertTrue(plugin.is_live_configured)
        self.assertEqual(plugin.mode_label, "paypal-sandbox-live")

        oidc_start = plugin.build_oidc_authorize_url(
            redirect_uri="https://dshvkidt3tkge.cloudfront.net/erp/connectors/paypal/oauth/callback",
            state_nonce="ppoidc:t1",
        )
        self.assertIn("signin/authorize?", oidc_start["authorize_url"])

        def _fake_urlopen(req, timeout=10.0):
            url = req.full_url
            method = req.get_method()
            if url.endswith("/v1/oauth2/token"):
                return _FakeHttpResponse(
                    {
                        "access_token": "tok-123",
                        "app_id": "APP-TEST123",
                        "expires_in": 32400,
                        "scope": "openid https://uri.paypal.com/services/invoicing https://uri.paypal.com/services/subscriptions",
                    }
                )
            if "/v1/identity/oauth2/userinfo" in url:
                return _FakeHttpResponse(
                    {
                        "payer_id": "PAYER-GR-001",
                        "user_id": "uid-gr-001",
                        "name": "Sofia Marinou",
                        "verified_account": "true",
                        "emails": [{"value": "sofia-sb@kerdon-synth.eu", "primary": True}],
                    }
                )
            if url.endswith("/v2/checkout/orders") and method == "POST":
                return _FakeHttpResponse(
                    {
                        "id": "2TP999888777",
                        "status": "CREATED",
                        "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=2TP999888777"}],
                    },
                    status=201,
                )
            if url.endswith("/v2/checkout/orders/2TP999888777") and method == "GET":
                return _FakeHttpResponse({"id": "2TP999888777", "status": "APPROVED"})
            if url.endswith("/v2/checkout/orders/2TP999888777/capture") and method == "POST":
                return _FakeHttpResponse(
                    {
                        "id": "2TP999888777",
                        "status": "COMPLETED",
                        "purchase_units": [
                            {
                                "payments": {
                                    "captures": [
                                        {
                                            "id": "CAP-LIVE-001",
                                            "status": "COMPLETED",
                                            "seller_receivable_breakdown": {
                                                "gross_amount": {"currency_code": "EUR", "value": "1240.00"},
                                                "paypal_fee": {"currency_code": "EUR", "value": "36.31"},
                                                "net_amount": {"currency_code": "EUR", "value": "1203.69"},
                                            },
                                        }
                                    ]
                                }
                            }
                        ],
                    }
                )
            if url.endswith("/v1/payments/payouts") and method == "POST":
                return _FakeHttpResponse(
                    {"batch_header": {"payout_batch_id": "BATCH-LIVE-01", "batch_status": "PENDING"}},
                    status=201,
                )
            if url.endswith("/v1/payments/payouts/BATCH-LIVE-01") and method == "GET":
                return _FakeHttpResponse(
                    {
                        "batch_header": {"payout_batch_id": "BATCH-LIVE-01", "batch_status": "SUCCESS"},
                        "items": [{"payout_item_fee": {"currency_code": "EUR", "value": "0.25"}}],
                    }
                )
            if url.endswith("/v1/catalogs/products"):
                return _FakeHttpResponse({"id": "PROD-LIVE-01"}, status=201)
            if url.endswith("/v1/billing/plans"):
                return _FakeHttpResponse({"id": "P-LIVE-01", "status": "ACTIVE"}, status=201)
            if url.endswith("/v1/billing/subscriptions"):
                return _FakeHttpResponse(
                    {
                        "id": "I-LIVE-01",
                        "status": "APPROVAL_PENDING",
                        "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/webapps/billing/subscriptions?ba_token=BA-1"}],
                    },
                    status=201,
                )
            if "/v1/customer/disputes" in url:
                return _FakeHttpResponse({"items": [{"dispute_id": "PP-D-101"}]})
            if url.endswith("/v1/shipping/trackers-batch"):
                return _FakeHttpResponse({"tracker_identifiers": [{"transaction_id": "CAP-LIVE-001", "tracking_number": "DHL-1"}]})
            if url.endswith("/v1/notifications/webhooks") and method == "GET":
                return _FakeHttpResponse({"webhooks": []})
            if url.endswith("/v1/notifications/webhooks") and method == "POST":
                return _FakeHttpResponse({"id": "WH-LIVE-01", "url": "https://example.org/erp/connectors/paypal/webhook"}, status=201)
            if url.endswith("/v1/notifications/verify-webhook-signature"):
                return _FakeHttpResponse({"verification_status": "SUCCESS"})
            raise AssertionError(f"Unexpected URL in fake_urlopen: {method} {url}")

        with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            meta = plugin.obtain_oauth_metadata()
            self.assertEqual(meta["app_id"], "APP-TEST123")

            ident = plugin.exchange_oidc_code_for_identity(code="auth-code-1", redirect_uri="https://example.org/cb")
            self.assertEqual(ident["payer_id"], "PAYER-GR-001")
            self.assertTrue(ident["verified_account"])

            ord_created = plugin.create_order_or_invoice(
                tenant_id=self.tid,
                document_id="doc-101",
                amount_cents=124_000,
                currency="EUR",
                payer_email="buyer@kerdon-synth.eu",
                description="Invoice 101",
                return_url="https://example.org/#module=documents",
                cancel_url="https://example.org/#module=documents",
            )
            self.assertEqual(ord_created["order_id"], "2TP999888777")
            self.assertEqual(plugin.get_order("2TP999888777")["status"], "APPROVED")

            cap = plugin.capture_order(
                tenant_id=self.tid,
                order_id="2TP999888777",
                document_id="doc-101",
                gross_cents=124_000,
                currency="EUR",
            )
            self.assertEqual(cap["fee_cents"], 3_631)
            self.assertEqual(cap["net_cents"], 120_369)

            payout = plugin.execute_batch_payout(
                tenant_id=self.tid,
                sender_batch_id="sb-live-01",
                items=[{"recipient_type": "EMAIL", "receiver": "s@kerdon-synth.eu", "amount": {"value": "50.00", "currency": "EUR"}}],
                currency="EUR",
            )
            self.assertEqual(payout["payout_batch_id"], "BATCH-LIVE-01")
            self.assertEqual(payout["status"], "SUCCESS")

            sub = plugin.create_subscription_bundle(tenant_id=self.tid)
            self.assertEqual(sub["subscription_id"], "I-LIVE-01")
            self.assertEqual(len(plugin.list_disputes()["items"]), 1)
            trk = plugin.register_shipment_tracker(capture_id="CAP-LIVE-001", tracking_number="DHL-1")
            self.assertEqual(len(trk["tracker_identifiers"]), 1)
            wh = plugin.list_or_register_webhook(webhook_url="https://example.org/erp/connectors/paypal/webhook")
            self.assertEqual(wh["webhook_id"], "WH-LIVE-01")
            ver = plugin.verify_webhook_via_api(
                transmission_id="t1",
                transmission_time="2026-11-11T10:00:00Z",
                cert_url="https://api.sandbox.paypal.com/cert",
                auth_algo="SHA256withRSA",
                transmission_sig="sig",
                webhook_id="WH-LIVE-01",
                webhook_event={"id": "evt-1"},
            )
            self.assertEqual(ver["verification_status"], "SUCCESS")

    def test_http_routes_2step_order_fail_closed_502_oidc_and_agent_replay(self) -> None:
        # 1. GET OIDC callback returns 302 redirect without mutating state (Least Privilege A7)
        r_redir = kaws.lambda_reader(
            {
                "rawPath": "/erp/connectors/paypal/oauth/callback",
                "rawQueryString": "code=oidc-code-77&state=ppoidc:t1",
                "requestContext": {"http": {"method": "GET", "path": "/erp/connectors/paypal/oauth/callback"}},
            },
            store=self.store,
        )
        self.assertEqual(r_redir["statusCode"], 302)
        loc_hdr = r_redir["headers"].get("location") or r_redir["headers"].get("Location") or ""
        self.assertIn("paypal_oidc_code=oidc-code-77", loc_hdr)

        # 2. POST OIDC callback binds identity; Subscription, Webhook, Tracker, Agent all succeed
        def _post(sub_path: str, payload: dict) -> dict:
            return kaws.lambda_writer(
                {
                    "rawPath": f"/erp/connectors/paypal/{sub_path}",
                    "requestContext": {"http": {"method": "POST", "path": f"/erp/connectors/paypal/{sub_path}"}},
                    "body": json.dumps(payload),
                },
                store=self.store,
            )

        self.assertEqual(_post("oauth/callback", {"code": "oidc-code-77"})["statusCode"], 200)
        r_sub = _post("subscription", {"tier_name": "Pro", "monthly_price_cents": 14900})
        self.assertEqual(r_sub["statusCode"], 201)
        self.assertEqual(_post("webhooks/register", {})["statusCode"], 201)
        self.assertEqual(_post("tracker", {"capture_id": "CAP-1", "tracking_number": "DHL-99"})["statusCode"], 201)
        self.assertEqual(_post("payout-sync", {"payout_batch_id": "PPBATCH-1"})["statusCode"], 200)

        # 3. 2-Step Order creation (auto_capture=False) + Order Status sync + Agent workflow
        state = self.store.get_tenant_state(self.tid)
        doc_id = next(did for did, d in state.crm.documents.items() if d.direction.value == "SALES_REVENUE" and d.gross_cents > d.paid_cents)
        r_o2 = _post("order", {"document_id": doc_id, "auto_capture": False})
        self.assertEqual(r_o2["statusCode"], 201)
        oid = json.loads(r_o2["body"])["order"]["order_id"]
        self.assertFalse(json.loads(r_o2["body"])["captured"])
        self.assertEqual(_post("order-status", {"order_id": oid})["statusCode"], 200)

        r_ag = _post("agent", {"goal": "Run full PayPal suite: order, subscription, webhook, payout", "llm_mode": "deterministic"})
        self.assertEqual(r_ag["statusCode"], 200)
        ag_data = json.loads(r_ag["body"])
        self.assertGreaterEqual(ag_data["tools_executed_count"], 4)

        # 4. Fail-closed HTTP 502 with paypal_debug_id when PayPal rejects ORDER_NOT_APPROVED
        kaws.lambda_writer(
            {
                "rawPath": "/erp/connectors/config",
                "requestContext": {"http": {"method": "POST"}},
                "body": json.dumps({"paypal_client_id": "cid-live", "paypal_client_secret": "csec-live"}),
            },
            store=self.store,
        )

        def _err_urlopen(req, timeout=10.0):
            if req.full_url.endswith("/v1/oauth2/token"):
                return _FakeHttpResponse({"access_token": "tok-err", "app_id": "APP-1"})
            raise _make_http_error(422, "ORDER_NOT_APPROVED", "Payer has not approved the Order", "dbg-unapproved-42")

        with patch("urllib.request.urlopen", side_effect=_err_urlopen):
            r_502 = _post("capture", {"order_id": oid, "document_id": doc_id})
            self.assertEqual(r_502["statusCode"], 502)
            err_body = json.loads(r_502["body"])
            self.assertEqual(err_body["provider_issue"], "ORDER_NOT_APPROVED")
            self.assertEqual(err_body["paypal_debug_id"], "dbg-unapproved-42")


if __name__ == "__main__":
    unittest.main()

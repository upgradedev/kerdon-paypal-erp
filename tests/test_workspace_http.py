"""Financial and tenant isolation regressions for original-backend UI integration."""
import json
import unittest
from kerdon_aws import MultiTenantStore, dispatch_http_event, lambda_reader
from kerdon_aws.workspace_routes import workspace_response
from kerdon import Actor, Role, PermissionDeniedError, reset_connector_states
from kerdon.erp_services import reset_erp_extensions


class WorkspaceHttpTests(unittest.TestCase):
    def setUp(self):
        reset_erp_extensions()
        reset_connector_states()
        self.store=MultiTenantStore()
        self.tid=self.store.workspace.default_tenant_id
        self.state=self.store.get_tenant_state(self.tid)

    def request(self,suffix,method='GET',body=None,query=''):
        return dispatch_http_event({'rawPath':'/tenants/'+self.tid+'/'+suffix,'rawQueryString':query,
            'requestContext':{'http':{'method':method}},'body':json.dumps(body or {})},store=self.store)

    def invoice(self,**extra):
        return {'document_id':'workspace-test','counterparty_id':next(iter(self.state.crm.customers)),
                'direction':'SALES_REVENUE','net_cents':10000,'vat_rate_pct':24,
                'issued_date':'2026-11-07','due_date':'2026-12-07',**extra}

    def test_reads_do_not_post_or_persist(self):
        count=len(self.state.ledger.events)
        response=self.request('operations')
        self.assertEqual(response['statusCode'],200)
        self.assertEqual(len(self.state.ledger.events),count)
        self.assertEqual(self.store.dynamo_writes,[])
        self.assertFalse(json.loads(response['body'])['capabilities']['cash_write'])

    def test_tenant_membership_is_enforced(self):
        actor=Actor('restricted','Restricted',Role.ACCOUNTANT,frozenset({'another'}))
        with self.assertRaises(PermissionDeniedError):
            workspace_response('/tenants/'+self.tid+'/operations',actor,self.store,{})

    def test_head_is_bodyless(self):
        r=lambda_reader({'rawPath':'/','requestContext':{'http':{'method':'HEAD'}}},store=self.store)
        self.assertEqual(r['statusCode'],200)
        self.assertEqual(r['body'],'')
        r_legacy=lambda_reader({'rawPath':'/workspace','requestContext':{'http':{'method':'HEAD'}}},store=self.store)
        self.assertEqual(r_legacy['statusCode'],301)
        self.assertEqual(r_legacy['body'],'')

    def test_invoice_reads_back_from_operational_list(self):
        self.assertEqual(self.request('invoices','POST',self.invoice())['statusCode'],201)
        r=json.loads(self.request('operations',query='start=2026-11-01&end=2026-11-30')['body'])
        doc=next(d for d in r['records']['sales'] if d['document_id']=='workspace-test')
        self.assertEqual(doc['gross_cents'],12400)
        self.assertEqual(doc['issued_date'],'2026-11-07')
        event=next(e for e in r['ledger'] if e['event_id']=='ev-workspace-test')
        self.assertEqual(event['posted_date'],'2026-11-07')

    def test_zero_vat_is_preserved(self):
        r=self.request('invoices','POST',self.invoice(vat_rate_pct=0))
        self.assertEqual(r['statusCode'],201)
        self.assertEqual(json.loads(r['body'])['document']['vat_cents'],0)

    def test_duplicate_never_posts_twice(self):
        self.request('invoices','POST',self.invoice())
        count=len(self.state.ledger.events)
        self.assertEqual(self.request('invoices','POST',self.invoice())['statusCode'],409)
        self.assertEqual(len(self.state.ledger.events),count)

    def test_foreign_counterparty_is_rejected(self):
        self.assertEqual(self.request('invoices','POST',self.invoice(counterparty_id='foreign'))['statusCode'],400)

    def test_invalid_due_date_is_rejected(self):
        self.assertEqual(self.request('invoices','POST',self.invoice(due_date='2026-01-01'))['statusCode'],400)

    def test_boolean_vat_is_rejected(self):
        self.assertEqual(self.request('invoices','POST',self.invoice(vat_rate_pct=True))['statusCode'],400)

    def test_reversed_period_is_rejected(self):
        self.assertEqual(self.request('operations',query='start=2026-12-01&end=2026-11-01')['statusCode'],400)


    def test_atomic_unit_of_work_transact_write_rollback_and_outbox(self):
        tx_calls = []

        class MockTransactDdb:
            def __init__(self, fail=False):
                self.fail = fail

            def query(self, **kwargs):
                return {"Items": []}

            def transact_write_items(self, **kwargs):
                tx_calls.append(kwargs)
                if self.fail:
                    raise RuntimeError("Simulated DynamoDB TransactWriteItems outage")

            def put_item(self, **kwargs):
                if self.fail:
                    raise RuntimeError("Simulated DynamoDB PutItem outage")

        self.store.ddb_client = MockTransactDdb(fail=False)
        r_ok = self.request(
            'parties',
            'POST',
            {
                'kind': 'customer',
                'party_id': 'cust-uow-atomic-01',
                'legal_name': 'Atomic UoW Holdings SA',
                'tax_id': 'EL112233445',
            },
        )
        self.assertEqual(r_ok['statusCode'], 201)
        body_ok = json.loads(r_ok['body'])
        self.assertIn('uow_receipt', body_ok)
        self.assertTrue(body_ok['uow_receipt']['uow_tx_id'].startswith('uow-'))
        self.assertEqual(len(body_ok['uow_receipt']['outbox_event_ids']), 1)
        self.assertGreaterEqual(len(tx_calls), 1)
        self.assertIn('cust-uow-atomic-01', self.state.crm.customers)

        cust_count_before = len(self.state.crm.customers)
        self.store.ddb_client = MockTransactDdb(fail=True)
        r_fail = self.request(
            'parties',
            'POST',
            {
                'kind': 'customer',
                'party_id': 'cust-uow-should-rollback',
                'legal_name': 'Rollback Test Corp',
                'tax_id': 'EL556677889',
            },
        )
        self.assertEqual(r_fail['statusCode'], 503)
        self.assertNotIn('cust-uow-should-rollback', self.state.crm.customers)
        self.assertEqual(len(self.state.crm.customers), cust_count_before)
        self.store.ddb_client = None

    def test_ai_document_autofill_extraction_and_html_guard(self):
        raw_invoice = (
            "Invoice INV-AI-2026-775\n"
            "Date: 2026-10-29 Due: 2026-11-29\n"
            "Managed Cloud Infrastructure: EUR 1200.00 (24% VAT)\n"
            "Staff Training Workshop: EUR 300.00 (13% VAT)\n"
            "Exempt EU Cross-Border Advisory: EUR 500.00 (0% VAT)"
        )
        r_ext = dispatch_http_event(
            {
                'rawPath': '/erp/ai/extract-document',
                'requestContext': {'http': {'method': 'POST'}},
                'body': json.dumps({'raw_text': raw_invoice, 'module': 'sales'}),
            },
            store=self.store,
        )
        self.assertEqual(r_ext['statusCode'], 200)
        draft = json.loads(r_ext['body'])['extracted_draft']
        self.assertEqual(draft['invoice_number'], 'INV-AI-2026-775')
        self.assertEqual(len(draft['lines']), 3)
        self.assertEqual(draft['total_net_cents'], 200_000)
        self.assertEqual(draft['total_vat_cents'], 32_700)
        self.assertEqual(draft['total_gross_cents'], 232_700)

        r_html = dispatch_http_event(
            {
                'rawPath': '/erp/ai/extract-document',
                'requestContext': {'http': {'method': 'POST'}},
                'body': json.dumps(
                    {
                        'raw_text': raw_invoice,
                        'module': 'purchases',
                        'source_kind': 'HTML_BODY_TABLE',
                    }
                ),
            },
            store=self.store,
        )
        self.assertEqual(r_html['statusCode'], 422)

    def test_ddd_bounded_contexts_trial_balance_and_public_dataset_import(self):
        r_bc = dispatch_http_event(
            {
                'rawPath': '/erp/bounded-contexts',
                'requestContext': {'http': {'method': 'GET'}},
            },
            store=self.store,
        )
        self.assertEqual(r_bc['statusCode'], 200)
        bc_body = json.loads(r_bc['body'])
        self.assertEqual(len(bc_body['bounded_contexts']), 7)
        self.assertEqual(len(bc_body['public_datasets']), 4)

        for ds_id in (
            'kerdon-universal-en-v1',
            'kerdon-hellenic-eu-v1',
            'kerdon-vision-multimodal-v1',
            'open-erp-peppol-iso20022-finqa-v1',
        ):
            r_imp = self.request(
                'datasets/import',
                'POST',
                {'dataset_id': ds_id},
            )
            self.assertEqual(r_imp['statusCode'], 201)
            imp = json.loads(r_imp['body'])['imported']
            self.assertEqual(imp['dataset_id'], ds_id)
            self.assertGreaterEqual(imp['imported_documents_count'], 1)

        r_ops = self.request('operations')
        self.assertEqual(r_ops['statusCode'], 200)
        ops = json.loads(r_ops['body'])
        tb_rows = ops['trial_balance']
        self.assertGreaterEqual(len(tb_rows), 4)
        self.assertEqual(
            sum(r['debit_cents'] for r in tb_rows),
            sum(r['credit_cents'] for r in tb_rows),
        )
        self.assertGreaterEqual(len(ops['evidence_inbox']['envelopes']), 1)
        self.assertEqual(len(ops['bounded_contexts']), 7)
        self.assertEqual(len(ops['public_datasets']), 4)
        cov = ops['dataset_coverage']
        self.assertTrue(cov['all_18_modules_functional'])
        self.assertTrue(cov['trial_balance_balanced'])
        self.assertEqual(cov['modules_passed'], 18)
        self.assertEqual(cov['modules_total'], 18)

        # Also verify seeding a brand-new empty production tenant populates all 18 modules
        r_onb = dispatch_http_event(
            {
                'rawPath': '/tenants/onboard',
                'requestContext': {'http': {'method': 'POST'}},
                'body': json.dumps(
                    {
                        'slug': 'empty-seed-co',
                        'display_name': 'Empty Seed Co',
                        'legal_name': 'Empty Seed Single Member SA',
                        'tax_id': 'EL998811223',
                        'empty_state': True,
                    }
                ),
            },
            store=self.store,
        )
        self.assertEqual(r_onb['statusCode'], 201)
        empty_tid = json.loads(r_onb['body'])['tenant']['tenant_id']
        r_seed = dispatch_http_event(
            {
                'rawPath': f'/tenants/{empty_tid}/datasets/import',
                'requestContext': {'http': {'method': 'POST'}},
                'body': json.dumps({'dataset_id': 'open-erp-peppol-iso20022-finqa-v1'}),
            },
            store=self.store,
        )
        self.assertEqual(r_seed['statusCode'], 201)
        seed_cov = json.loads(r_seed['body'])['imported']['coverage_verification']
        self.assertTrue(seed_cov['all_18_modules_functional'])
        self.assertEqual(seed_cov['modules_passed'], 18)

    def _assert_full_workspace_reconciliation(self, ops: dict) -> None:
        kpis = ops['dashboard']['kpis']
        aging = ops['aging']
        recs = ops['records']
        ledger = ops['ledger']
        events_by_id = {e['event_id']: e for e in ledger}

        # 1. Receivables KPI == Aging Open AR == Sum of Sales outstanding_cents == Sum of drill-down 1100_AR events
        open_sales_sum = sum(
            max(0, d['gross_cents'] - d['paid_cents'])
            for d in recs['sales']
            if d.get('lifecycle_status') != 'REVERSED'
        )
        ar_drill_sum = sum(
            l['debit_cents'] - l['credit_cents']
            for eid in kpis['receivables']['event_ids']
            for l in events_by_id[eid]['lines']
            if str(l['account']).startswith('1100_')
        )
        self.assertEqual(kpis['receivables']['cents'], aging['receivables_aging']['total_open_cents'])
        self.assertEqual(kpis['receivables']['cents'], open_sales_sum)
        self.assertEqual(kpis['receivables']['cents'], ar_drill_sum)

        # 2. Payables KPI == Aging Open AP == Sum of Purchases outstanding_cents == Sum of drill-down 2000_AP events
        open_purch_sum = sum(
            max(0, d['gross_cents'] - d['paid_cents'])
            for d in recs['purchases']
            if d.get('lifecycle_status') != 'REVERSED'
        )
        ap_drill_sum = sum(
            l['credit_cents'] - l['debit_cents']
            for eid in kpis['payables']['event_ids']
            for l in events_by_id[eid]['lines']
            if str(l['account']).startswith('2000_')
        )
        self.assertEqual(kpis['payables']['cents'], aging['payables_aging']['total_open_cents'])
        self.assertEqual(kpis['payables']['cents'], open_purch_sum)
        self.assertEqual(kpis['payables']['cents'], ap_drill_sum)

        # 3. Cash KPI == Sum(receipts) - Sum(payments) == Sum of drill-down 1000_CASH events
        receipts_sum = sum(r['amount_cents'] for r in recs['receipts'])
        payments_sum = sum(p['amount_cents'] for p in recs['payments'])
        cash_drill_sum = sum(
            l['debit_cents'] - l['credit_cents']
            for eid in kpis['cash']['event_ids']
            for l in events_by_id[eid]['lines']
            if l['account'] == '1000_CASH'
        )
        self.assertEqual(kpis['cash']['cents'], receipts_sum - payments_sum)
        self.assertEqual(kpis['cash']['cents'], cash_drill_sum)

        # 4. Revenue KPI == Sum of drill-down 4000/4100 events
        rev_drill_sum = sum(
            l['credit_cents'] - l['debit_cents']
            for eid in kpis['revenue']['event_ids']
            for l in events_by_id[eid]['lines']
            if str(l['account']).startswith('4')
        )
        self.assertEqual(kpis['revenue']['cents'], rev_drill_sum)

        # 5. Every paid/part-paid invoice or bill has reconciled allocations summing to paid_cents
        for mod in ('sales', 'purchases'):
            for doc in recs[mod]:
                if doc['paid_cents'] > 0:
                    alloc_sum = sum(a['allocated_cents'] for a in doc.get('allocations', []))
                    self.assertEqual(alloc_sum, doc['paid_cents'], f"Mismatch on {doc['document_id']}")

        # 6. Verification matrix active record counts match exact operational table lengths
        cov_map = {c['module_id']: c['records_count'] for c in ops['dataset_coverage']['module_coverage']}
        for mod in ('customers', 'sales', 'receipts', 'suppliers', 'purchases', 'expenses', 'payments'):
            self.assertEqual(cov_map[mod], len(recs[mod]), f"Count mismatch on module {mod}")
        self.assertEqual(cov_map['accounting'], len(ledger))

        # 7. CFO Financial Statements (P&L, Balance Sheet, Statutory VAT Return) & Multi-Month Rolling Series
        self.assertGreaterEqual(len(ops['dashboard']['rolling_series']), 2)
        pf = ops['profitability']
        pnl = pf['pnl_statement']
        bs = pf['balance_sheet']
        vr = pf['vat_return']
        self.assertEqual(pnl['total_revenue_cents'], kpis['revenue']['cents'])
        self.assertEqual(pnl['ebitda_cents'], pf['ebitda_cents'])
        self.assertTrue(bs['balanced'])
        self.assertEqual(bs['total_assets_cents'], bs['total_liabilities_and_equity_cents'])
        self.assertEqual(bs['cash_1000_cents'], kpis['cash']['cents'])
        self.assertEqual(bs['accounts_receivable_1100_cents'], kpis['receivables']['cents'])
        self.assertEqual(bs['accounts_payable_2000_cents'], kpis['payables']['cents'])
        self.assertEqual(
            vr['net_vat_payable_cents'],
            vr['output_vat_2400_cents'] - vr['input_vat_1400_cents'],
        )

    def test_cross_module_kpi_tile_and_list_reconciliation(self) -> None:
        # A. Verify initial DEMO_SEED state reconciles 100% across all tiles and lists
        ops_init = json.loads(self.request('operations')['body'])
        self._assert_full_workspace_reconciliation(ops_init)

        # B. Verify after seeding public dataset
        r_seed = self.request('datasets/import', 'POST', {'dataset_id': 'kerdon-hellenic-eu-v1'})
        self.assertEqual(r_seed['statusCode'], 201)
        ops_seeded = json.loads(self.request('operations')['body'])
        self._assert_full_workspace_reconciliation(ops_seeded)

        # C. Verify after loading full 240-record portfolio mode
        r_port = self.request('portfolio/mode', 'POST', {'mode': 'FULL_240_PORTFOLIO'})
        self.assertEqual(r_port['statusCode'], 200)
        ops_port = json.loads(self.request('operations')['body'])
        self._assert_full_workspace_reconciliation(ops_port)
        self.assertGreaterEqual(len(ops_port['records']['sales']), 8)
        self.assertGreaterEqual(len(ops_port['records']['purchases']), 7)

        # D. Verify service module payloads (workforce, commissions, completeness, inventory, treasury)
        ov = json.loads(self.request('overview')['body'])
        wf = ov['workforce_fusion']
        self.assertEqual(
            wf['true_employer_cost_cents'],
            wf['gross_wages_cents'] + wf['employer_social_security_cents'],
        )
        self.assertGreater(wf['net_salary_payable_cents'], 0)
        self.assertGreater(wf['total_apd_payable_cents'], 0)
        self.assertGreater(wf['total_fmy_payable_cents'], 0)

        cm = json.loads(self.request('commissions')['body'])
        stmt_sum = sum(s['net_payable_commission_cents'] for s in cm['commission_case']['statements'])
        self.assertEqual(cm['total_payable_cents'], stmt_sum)
        for ps in cm['settlements']:
            self.assertEqual(ps['gross_cents'], ps['agreed_net_cents'] + ps['vat_cents'])

        comp = json.loads(self.request('completeness')['body'])
        for g in comp['gaps']:
            self.assertTrue(g.get('summary'))
            self.assertTrue(g.get('counterparty_name'))

        inv_in = self.request(
            'inventory/movement',
            'POST',
            {'sku_code': 'SKU-ONT-WIFI6-PRO', 'movement_kind': 'GOODS_RECEIPT', 'quantity': 20, 'unit_cost_cents': 4500},
        )
        self.assertEqual(inv_in['statusCode'], 200)
        inv_out = self.request(
            'inventory/movement',
            'POST',
            {'sku_code': 'SKU-ONT-WIFI6-PRO', 'movement_kind': 'SALE_DISPATCH', 'quantity': 5, 'unit_cost_cents': 4500},
        )
        self.assertEqual(inv_out['statusCode'], 200)

    def test_country_parametric_aade_mydata_schema_and_fiscal_regime_switching(self) -> None:
        import kerdon as kd

        # 1. Modulo-11 Greek AFM validation
        self.assertTrue(kd.validate_greek_afm('EL094259216')['valid'])
        self.assertFalse(kd.validate_greek_afm('EL094259210')['valid'])

        # 2. Default organization is Greek (country_code == 'GR') with active AADE myDATA + 17.1 Payroll
        ops_gr = json.loads(self.request('operations')['body'])
        fp_gr = ops_gr['fiscal_profile']
        self.assertEqual(fp_gr['country_code'], 'GR')
        self.assertTrue(fp_gr['is_greek_organization'])
        self.assertTrue(fp_gr['aade_mydata_enabled'])
        self.assertTrue(fp_gr['afm_validation']['valid'])
        mydata_recs = ops_gr['connectors']['mydata']['records']
        self.assertGreaterEqual(len(mydata_recs), 3)
        payroll_rec = next(r for r in mydata_recs if r['invoice_type'] == '17.1')
        self.assertIn('<invoiceType>17.1</invoiceType>', payroll_rec['xml_preview'])
        self.assertIn('<ecls:classificationType>E3_581_001</ecls:classificationType>', payroll_rec['xml_preview'])

        # 3. Create Greek party with DOY & GEMI + Greek multi-line invoice with 20% withholding tax & payment method 3
        r_party = self.request(
            'parties',
            'POST',
            {
                'kind': 'customer',
                'legal_name': 'Hellenic Fiber Networks SA',
                'tax_id': 'EL094259216',
                'country_code': 'GR',
                'doy': 'ΔΟΥ ΦΑΕ ΑΘΗΝΩΝ',
                'gemi_number': '123456701000',
                'city': 'Αθήνα',
                'postal_code': '11526',
                'address': 'Λεωφ. Κηφισίας 44',
            },
        )
        self.assertEqual(r_party['statusCode'], 201)
        party_id = json.loads(r_party['body'])['party']['id']

        r_inv = self.request(
            'invoices',
            'POST',
            {
                'document_id': 'doc-aade-full-01',
                'direction': 'SALES_REVENUE',
                'counterparty_id': party_id,
                'counterparty_name': 'Hellenic Fiber Networks SA',
                'counterparty_tax_id': 'EL094259216',
                'invoice_number': 'TΠY-2026-501',
                'issued_date': '2026-10-30',
                'due_date': '2026-11-30',
                'invoice_type': '2.1',
                'series': 'A',
                'aa': '501',
                'payment_method_code': 1,
                'withheld_tax_pct': 20,
                'vat_exemption_category': '',
                'lines': [
                    {'description': 'Consulting Services 24%', 'quantity': 2, 'measurement_unit': 1, 'unit_price_cents': 50000, 'vat_rate_pct': 24},
                    {'description': 'Technical Workshop 13%', 'quantity': 1, 'measurement_unit': 3, 'unit_price_cents': 20000, 'vat_rate_pct': 13},
                ],
            },
        )
        self.assertEqual(r_inv['statusCode'], 201)
        inv_payload = json.loads(r_inv['body'])
        mrec = inv_payload['mydata_record']
        self.assertEqual(mrec['invoice_type'], '2.1')
        self.assertEqual(mrec['payment_method_code'], 1)
        self.assertEqual(mrec['withheld_tax_cents'], 24000)  # 20% of 1200.00 EUR net
        self.assertFalse(mrec['b2b_cash_limit_violation'])
        self.assertTrue(mrec['xsd_valid'])
        self.assertEqual(mrec['xsd_checks_passed'], 16)
        xml_str = mrec['xml_preview']
        self.assertIn('<paymentMethods>', xml_str)
        self.assertIn('<type>1</type>', xml_str)
        self.assertIn('<taxesTotals>', xml_str)
        self.assertIn('<taxAmount>240.00</taxAmount>', xml_str)
        self.assertIn('<measurementUnit>3</measurementUnit>', xml_str)

        # 4. Switch organization country to DE (Germany) -> AADE myDATA parametrically disabled
        r_de = self.request('connectors/fiscal-profile', 'POST', {'country_code': 'DE'})
        self.assertEqual(r_de['statusCode'], 200)
        de_body = json.loads(r_de['body'])
        self.assertEqual(de_body['fiscal_profile']['country_code'], 'DE')
        self.assertFalse(de_body['fiscal_profile']['is_greek_organization'])
        self.assertFalse(de_body['fiscal_profile']['aade_mydata_enabled'])
        self.assertEqual(de_body['connectors']['mydata']['records'], [])

        # Attempting to transmit to AADE myDATA when organization is DE returns 400
        r_tx_blocked = self.request('connectors/mydata/transmit', 'POST', {'document_id': 'doc-aade-full-01'})
        self.assertEqual(r_tx_blocked['statusCode'], 400)

        # 5. Switch back to GR (Greece) and transmit-all
        r_back_gr = self.request(
            'connectors/fiscal-profile',
            'POST',
            {'country_code': 'GR', 'doy': 'ΔΟΥ ΦΑΕ ΑΘΗΝΩΝ', 'gemi_number': '123456701000'},
        )
        self.assertEqual(r_back_gr['statusCode'], 200)
        self.assertTrue(json.loads(r_back_gr['body'])['fiscal_profile']['aade_mydata_enabled'])

        r_tx_all = self.request('connectors/mydata/transmit-all', 'POST', {})
        self.assertEqual(r_tx_all['statusCode'], 200)
        tx_all_body = json.loads(r_tx_all['body'])
        self.assertGreaterEqual(tx_all_body['mydata']['transmitted_count'], 4)

    def test_paypal_agentic_commerce_end_to_end(self) -> None:
        # 1. Cold-start GET /erp/connectors has pre-seeded PayPal orders, disputes, payouts & 6 Agentic Tools
        r_conn = self.request('connectors')
        self.assertEqual(r_conn['statusCode'], 200)
        conn = json.loads(r_conn['body'])['paypal']
        self.assertEqual(len(conn['agentic_tools']), 6)
        self.assertGreaterEqual(len(conn['orders']), 1)
        self.assertGreaterEqual(len(conn['disputes']), 1)
        self.assertGreaterEqual(len(conn['payouts']), 1)
        self.assertEqual(
            conn['disputes'][0]['evidence_defense_packet']['evidence_type'],
            'PROOF_OF_FULFILLMENT',
        )

        # 2. Capture unpaid sales invoice via PayPal Orders v2 + Invoicing v2 preview
        ops = json.loads(self.request('operations')['body'])
        unpaid_doc = next(
            d['document_id']
            for d in ops['records']['sales']
            if d['paid_cents'] < d['gross_cents']
        )
        r_ord = self.request(
            'connectors/paypal/order',
            'POST',
            {'document_id': unpaid_doc, 'auto_capture': True},
        )
        self.assertEqual(r_ord['statusCode'], 201)
        ord_body = json.loads(r_ord['body'])
        self.assertTrue(ord_body['captured'])
        self.assertIn('invoicing_v2_preview', ord_body)
        self.assertTrue(
            ord_body['invoicing_v2_preview']['paypal_invoice_id'].startswith('INV2-')
        )

        # 3. Trigger PayPal Dispute -> Seller Clawback + Autonomous Evidence Defense Packet
        r_disp = self.request(
            'connectors/paypal/dispute',
            'POST',
            {
                'dispute_id': 'PPDISP-TEST-901',
                'document_id': unpaid_doc,
                'disputed_amount_cents': 124_000,
                'reason_code': 'MERCHANDISE_OR_SERVICE_NOT_RECEIVED',
            },
        )
        self.assertEqual(r_disp['statusCode'], 201)
        disp_body = json.loads(r_disp['body'])
        self.assertEqual(
            disp_body['evidence_defense_packet']['evidence_type'],
            'PROOF_OF_FULFILLMENT',
        )
        self.assertEqual(
            disp_body['evidence_defense_packet']['evidence_checks_passed'], 4
        )

        # 4. Verify PayPal Webhook signature (POST /erp/connectors/paypal/webhook)
        import kerdon as kd

        res_payload = {'id': ord_body['order']['capture_id']}
        raw_res_json = json.dumps(res_payload, sort_keys=True)
        valid_sig = kd.compute_paypal_webhook_signature(
            raw_body=raw_res_json,
            transmission_id='PPTX-TEST-01',
            transmission_time='2026-10-30T10:00:00Z',
            webhook_id='WH-KERDON-PAYPAL-01',
        )
        r_wh = self.request(
            'connectors/paypal/webhook',
            'POST',
            {
                'event_id': 'WH-EVT-PP-01',
                'event_type': 'PAYMENT.CAPTURE.COMPLETED',
                'transmission_id': 'PPTX-TEST-01',
                'transmission_time': '2026-10-30T10:00:00Z',
                'webhook_id': 'WH-KERDON-PAYPAL-01',
                'transmission_sig': valid_sig,
                'resource': res_payload,
            },
        )
        self.assertEqual(r_wh['statusCode'], 200)
        self.assertEqual(
            json.loads(r_wh['body'])['verification']['verification_status'],
            'SUCCESS',
        )
        # Empty webhook and prefix-spoofed webhook must fail closed
        self.assertEqual(self.request('connectors/paypal/webhook', 'POST', {})['statusCode'], 400)
        self.assertEqual(
            self.request(
                'connectors/paypal/webhook',
                'POST',
                {
                    'event_id': 'WH-EVT-PP-SPOOF',
                    'event_type': 'PAYMENT.CAPTURE.COMPLETED',
                    'transmission_id': 'PPTX-TEST-02',
                    'transmission_time': '2026-10-30T10:00:00Z',
                    'webhook_id': 'WH-KERDON-PAYPAL-01',
                    'transmission_sig': 'PPSIG-VALID-SPOOF',
                    'resource': res_payload,
                },
            )['statusCode'],
            403,
        )
        # Duplicate webhook event_id rejected with 409
        self.assertEqual(
            self.request(
                'connectors/paypal/webhook',
                'POST',
                {
                    'event_id': 'WH-EVT-PP-01',
                    'event_type': 'PAYMENT.CAPTURE.COMPLETED',
                    'transmission_id': 'PPTX-TEST-01',
                    'transmission_time': '2026-10-30T10:00:00Z',
                    'webhook_id': 'WH-KERDON-PAYPAL-01',
                    'transmission_sig': valid_sig,
                    'resource': res_payload,
                },
            )['statusCode'],
            409,
        )

        # 5. Grounded NL query about PayPal checkout & disputes
        r_q = self.request(
            'query',
            'POST',
            {'question': 'How do PayPal checkout fees and disputes impact our GL?'},
        )
        self.assertEqual(r_q['statusCode'], 200)
        q_body = json.loads(r_q['body'])
        self.assertIn('PayPal', q_body.get('answer_text', q_body.get('answer', '')))

    def test_english_default_and_bilingual_support(self) -> None:
        import re

        greek_pat = re.compile(r'[\u0370-\u03ff\u1f00-\u1fff]')
        # 1. Default fiscal profile and operations payload have English defaults (country_name, doy, city, street)
        r_fp = self.request('operations')
        self.assertEqual(r_fp['statusCode'], 200)
        fp = json.loads(r_fp['body'])['fiscal_profile']
        self.assertEqual(fp['country_name'], 'Greece')
        self.assertEqual(fp['country_name_el'], 'Ελλάδα')
        self.assertFalse(greek_pat.search(fp['doy']))
        self.assertFalse(greek_pat.search(fp['city']))
        self.assertFalse(greek_pat.search(fp['street']))
        # All myDATA invoice_types default 'name' is English while 'name_el' is Greek
        for it in fp['mydata_catalogs']['invoice_types']:
            self.assertFalse(greek_pat.search(it['name']), it['name'])
            self.assertTrue(greek_pat.search(it['name_el']), it['name_el'])

        # 2. Canonical '/' SPA HTML (outside <script> i18n dictionary) has 0 Greek characters in default render
        r_root = dispatch_http_event({'rawPath': '/', 'requestContext': {'http': {'method': 'GET', 'path': '/'}}}, store=self.store)
        self.assertEqual(r_root['statusCode'], 200)
        self.assertIn('id="lang-select"', r_root['body'])
        self.assertIn('EN · English', r_root['body'])
        markup_without_script = re.sub(r'<script\b[^>]*>.*?</script>', '', r_root['body'], flags=re.DOTALL)
        self.assertFalse(greek_pat.search(markup_without_script))

        # 3. Legacy '/workspace' and '/cockpit' paths canonicalize cleanly via HTTP 301
        r_ws = dispatch_http_event({'rawPath': '/workspace', 'requestContext': {'http': {'method': 'GET', 'path': '/workspace'}}}, store=self.store)
        self.assertEqual(r_ws['statusCode'], 301)
        self.assertEqual(r_ws['headers']['location'], '/')
        r_cp = dispatch_http_event({'rawPath': '/cockpit', 'requestContext': {'http': {'method': 'GET', 'path': '/cockpit'}}}, store=self.store)
        self.assertEqual(r_cp['statusCode'], 301)
        self.assertEqual(r_cp['headers']['location'], '/')

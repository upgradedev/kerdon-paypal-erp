"""Concrete financial invariants for operational projections."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kerdon.crm import CommercialRegistry, Customer, Supplier
from kerdon.ledger import GeneralLedger, LedgerLine, FinancialEvent, AccountCode as A
from kerdon.operational import party_statement, dashboard_projection, operational_records


class OperationalProjectionTests(unittest.TestCase):
    def setUp(self):
        crm = CommercialRegistry('tenant-a')
        crm.upsert_customer(Customer('customer-a','tenant-a','Customer A','1','a@example.test'))
        crm.upsert_supplier(Supplier('supplier-a','tenant-a','Supplier A','2','IBAN','services'))
        self.state = SimpleNamespace(tenant=SimpleNamespace(tenant_id='tenant-a'),crm=crm,ledger=GeneralLedger('tenant-a'))
        self.post('opening','2026-09-20',[(A.AR_1100,10000,0,'customer-a'),(A.REVENUE_SALES_4000,0,10000,'customer-a')])
        self.post('invoice','2026-10-05',[(A.AR_1100,24800,0,'customer-a'),(A.REVENUE_SALES_4000,0,20000,'customer-a'),(A.VAT_OUTPUT_2400,0,4800,'customer-a')])
        self.post('receipt','2026-10-15',[(A.CASH_1000,8000,0,'customer-a'),(A.AR_1100,0,8000,'customer-a')])
        self.post('bill','2026-10-07',[(A.OPEX_GENERAL_6200,5000,0,'supplier-a'),(A.AP_2000,0,5000,'supplier-a')])
        self.post('payment','2026-10-18',[(A.AP_2000,2000,0,'supplier-a'),(A.CASH_1000,0,2000,'supplier-a')])

    def post(self, identifier, day, lines):
        self.state.ledger.post(FinancialEvent(identifier,'tenant-a',day[:7],day,identifier,'doc-'+identifier,'source-hash',tuple(LedgerLine(*line) for line in lines)))

    def test_customer_statement_opening_movements_and_closing(self):
        result=party_statement(self.state,'customer-a','customer','2026-10-01','2026-10-31')
        self.assertEqual(result['opening_cents'],10000)
        self.assertEqual([row['balance_cents'] for row in result['rows']],[34800,26800])
        self.assertEqual(result['closing_cents'],26800)

    def test_supplier_credit_normal_balance(self):
        result=party_statement(self.state,'supplier-a','supplier','2026-10-01','2026-10-31')
        self.assertEqual(result['closing_cents'],3000)
        self.assertEqual([row['decrease_cents'] for row in result['rows']],[0,2000])

    def test_revenue_excludes_prior_period_and_vat(self):
        result=dashboard_projection(self.state,'2026-10-01','2026-10-31')
        self.assertEqual(result['kpis']['revenue']['cents'],20000)
        self.assertEqual(result['kpis']['revenue']['event_ids'],['invoice'])

    def test_cumulative_cash_and_month_series(self):
        result=dashboard_projection(self.state,'2026-10-01','2026-10-31')
        self.assertEqual(result['kpis']['cash']['cents'],6000)
        self.assertEqual(result['series'][0]['inflow_cents'],8000)
        self.assertEqual(result['series'][0]['outflow_cents'],2000)

    def test_cash_records_distinguish_payment_from_receipt(self):
        self.assertEqual(operational_records(self.state,'payments')[0]['amount_cents'],2000)
        self.assertEqual(operational_records(self.state,'receipts')[0]['amount_cents'],8000)

    def test_unknown_party_and_reversed_period_are_rejected(self):
        with self.assertRaises(KeyError):
            party_statement(self.state,'other-tenant-party','customer','2026-10-01','2026-10-31')
        with self.assertRaises(ValueError):
            dashboard_projection(self.state,'2026-11-01','2026-10-01')

    def test_reads_never_post(self):
        before=len(self.state.ledger.events)
        dashboard_projection(self.state,'2026-10-01','2026-10-31')
        party_statement(self.state,'supplier-a','supplier','2026-10-01','2026-10-31')
        self.assertEqual(len(self.state.ledger.events),before)

if __name__=='__main__':unittest.main()

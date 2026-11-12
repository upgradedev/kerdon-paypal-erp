export type ModuleKey =
  | 'dashboard'
  | 'statements'
  | 'customers'
  | 'suppliers'
  | 'sales'
  | 'purchases'
  | 'expenses'
  | 'payments'
  | 'receipts'
  | 'targets'
  | 'accounting'
  | 'treasury'
  | 'close'
  | 'commissions'
  | 'inventory'
  | 'documents'
  | 'workforce'
  | 'intelligence'
  | 'billing';

export interface KpiMetric {
  cents: number;
  event_ids: string[];
}

export interface PeriodSeriesPoint {
  period: string;
  inflow_cents: number;
  outflow_cents: number;
  revenue_cents: number;
  event_ids: string[];
}

export interface DashboardProjection {
  start: string;
  end: string;
  kpis: {
    cash: KpiMetric;
    revenue: KpiMetric;
    receivables: KpiMetric;
    payables: KpiMetric;
  };
  series: PeriodSeriesPoint[];
}

export interface AgingBucket {
  current_cents: number;
  days_1_30_cents: number;
  days_31_60_cents: number;
  days_61_90_cents: number;
  days_over_90_cents: number;
  total_open_cents?: number;
}

export interface CashFlowStatement {
  standard: string;
  start: string;
  end: string;
  currency: string;
  opening_cash_cents: number;
  operating_activities: {
    receipts_from_customers_cents: number;
    payments_to_suppliers_cents: number;
    payments_for_workforce_and_taxes_cents: number;
    payments_for_rent_and_opex_cents: number;
    vat_and_income_tax_settlements_cents: number;
    other_operating_cash_cents: number;
    net_operating_cash_cents: number;
  };
  investing_activities: {
    capex_and_asset_acquisitions_cents: number;
    net_investing_cash_cents: number;
  };
  financing_activities: {
    debt_and_equity_financing_cents: number;
    net_financing_cash_cents: number;
  };
  memorandum_items: {
    payment_processor_fees_deducted_at_source_cents: number;
  };
  net_change_in_cash_cents: number;
  closing_cash_cents: number;
  reconciled: boolean;
}

export interface CashAccountStatement {
  tenant_id: string;
  account_code: string;
  start: string;
  end: string;
  currency: string;
  opening_cents: number;
  total_debit_cents: number;
  total_credit_cents: number;
  net_change_cents: number;
  closing_cents: number;
  memorandum_processor_fees_cents: number;
  reconciled: boolean;
  rows: Record<string, any>[];
}

export interface OperationsPayload {
  tenant: {
    tenant_id: string;
    display_name: string;
    slug?: string;
    inbox_address?: string;
    fiscal_identity?: Record<string, any>;
  };
  durability: string;
  dashboard: DashboardProjection;
  records: Record<string, Record<string, any>[]>;
  ledger: Record<string, any>[];
  trial_balance?: Record<string, any>[];
  aging?: {
    as_of?: string;
    receivables_aging: AgingBucket;
    payables_aging: AgingBucket;
  };
  profitability?: {
    gross_profit_cents: number;
    ebitda_cents: number;
    pnl_statement?: Record<string, any>;
    balance_sheet?: Record<string, any>;
    cash_flow_statement?: CashFlowStatement;
    cash_account_statement?: CashAccountStatement;
    vat_return?: Record<string, any>;
    working_capital_ratios?: Record<string, any>;
    cash_forecast?: {
      projected_net_cash_cents: number;
    };
  };
  targets_summary?: {
    saved_targets: Record<string, any>[];
  };
  connectors?: Record<string, any>;
  organization_access?: {
    members: Record<string, any>[];
  };
  capabilities: {
    invoice_submission: boolean;
  };
}

export type ModuleKey =
  | 'dashboard'
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
}

export interface OperationsPayload {
  tenant: {
    tenant_id: string;
    display_name: string;
    slug?: string;
    inbox_address?: string;
  };
  durability: string;
  dashboard: DashboardProjection;
  records: Record<string, Record<string, any>[]>;
  ledger: Record<string, any>[];
  aging?: {
    receivables_aging: AgingBucket;
    payables_aging: AgingBucket;
  };
  profitability?: {
    gross_profit_cents: number;
    ebitda_cents: number;
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

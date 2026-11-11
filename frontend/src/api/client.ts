import { ModuleKey } from '../types/erp';

export const MODULES: Record<ModuleKey, string> = {
  dashboard: 'Dashboard',
  customers: 'Customers',
  suppliers: 'Suppliers',
  sales: 'Sales',
  purchases: 'Purchases',
  expenses: 'Expenses',
  payments: 'Payments',
  receipts: 'Cash receipts',
  targets: 'Sales targets',
  accounting: 'Accounting',
  treasury: 'Treasury',
  close: 'Close & completeness',
  commissions: 'Commissions',
  inventory: 'Inventory',
  documents: 'Documents & evidence',
  workforce: 'Workforce',
  intelligence: 'Ask Kerdon',
  billing: 'Subscription & fleet',
};

export const NAVIGATION_GROUPS: [string, ModuleKey[]][] = [
  ['Overview & Intelligence', ['dashboard', 'intelligence']],
  ['Order-to-Cash (AR)', ['customers', 'sales', 'receipts']],
  ['Procure-to-Pay (AP)', ['suppliers', 'purchases', 'expenses', 'payments']],
  ['Sales & Commissions', ['targets', 'commissions']],
  ['Inventory & Supply Chain', ['inventory']],
  ['Record-to-Report (GL & Tax)', ['accounting', 'close', 'workforce', 'documents']],
  ['Treasury & Governance', ['treasury', 'billing']],
];

export const MODULE_BOUNDED_CONTEXT: Record<ModuleKey, { code: string; name: string; standard: string }> = {
  dashboard: { code: 'BC-FP&A', name: 'Overview & Intelligence', standard: 'IFRS 18 / APQC 9.1 Dual-Basis FP&A' },
  intelligence: { code: 'BC-FP&A', name: 'Overview & Intelligence', standard: 'ADR-041 Grounded Fact-Sheet NL Query' },
  customers: { code: 'BC-O2C', name: 'Order-to-Cash (AR)', standard: 'OASIS UBL 2.1 AccountingCustomerParty' },
  sales: { code: 'BC-O2C', name: 'Order-to-Cash (AR)', standard: 'EN 16931 / Peppol BIS Billing 3.0 (380/381)' },
  receipts: { code: 'BC-O2C', name: 'Order-to-Cash (AR)', standard: 'ISO 20022 camt.053 CRDT Remittance' },
  suppliers: { code: 'BC-P2P', name: 'Procure-to-Pay (AP)', standard: 'OASIS UBL 2.1 AccountingSupplierParty' },
  purchases: { code: 'BC-P2P', name: 'Procure-to-Pay (AP)', standard: 'ADR-030 Fiscal Identity Sign Classification' },
  expenses: { code: 'BC-P2P', name: 'Procure-to-Pay (AP)', standard: 'ICDAR SROIE / CORD Operating Expense Schema' },
  payments: { code: 'BC-P2P', name: 'Procure-to-Pay (AP)', standard: 'ISO 20022 pain.001 DBIT Disbursement' },
  targets: { code: 'BC-ICM', name: 'Sales & Commissions', standard: 'APQC 3.5 Store & Category Quota Planning' },
  commissions: { code: 'BC-ICM', name: 'Sales & Commissions', standard: 'ADR-029/048/049 MonthlyCommissionCase & ICM' },
  inventory: { code: 'BC-WMS', name: 'Inventory & Supply Chain', standard: 'IAS 2 Weighted Average Cost (WAC) & GS1 SKU' },
  accounting: { code: 'BC-R2R', name: 'Record-to-Report (GL & Tax)', standard: 'ADR-012 Double-Entry GL & Trial Balance' },
  close: { code: 'BC-R2R', name: 'Record-to-Report (GL & Tax)', standard: 'ADR-023/024/042 24-Rule Completeness & GapReasoner' },
  workforce: { code: 'BC-R2R', name: 'Record-to-Report (GL & Tax)', standard: 'ADR-031 3-Document Payroll Fusion (Register + APD + FMY)' },
  documents: { code: 'BC-R2R', name: 'Record-to-Report (GL & Tax)', standard: 'ADR-022/028/048 Evidence Inbox, DocGen & AADE myDATA v1.0.8' },
  treasury: { code: 'BC-TRM', name: 'Treasury & Governance', standard: 'ISO 20022 Multi-Currency Treasury & Stale-Approval Guard' },
  billing: { code: 'BC-TRM', name: 'Treasury & Governance', standard: 'ADR-044/052 Multi-Tenant RBAC, Connectors & Public Datasets' },
};

const svg = (paths: string) =>
  `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;

export const MODULE_ICONS: Record<ModuleKey, string> = {
  dashboard: svg('<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>'),
  intelligence: svg('<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z"/><path d="M5 3v4"/><path d="M3 5h4"/><path d="M19 17v4"/><path d="M17 19h4"/>'),
  customers: svg('<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'),
  sales: svg('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M9 15l2 2 4-4"/>'),
  receipts: svg('<path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/>'),
  suppliers: svg('<path d="M3 21h18"/><path d="M5 21V7l8-4v18"/><path d="M19 21V11l-6-4"/><path d="M9 9v.01"/><path d="M9 12v.01"/><path d="M9 15v.01"/>'),
  purchases: svg('<path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/>'),
  expenses: svg('<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/><path d="M14 8H8"/><path d="M16 12H8"/><path d="M13 16H8"/>'),
  payments: svg('<rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/><line x1="6" y1="15" x2="10" y2="15"/>'),
  targets: svg('<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>'),
  commissions: svg('<circle cx="12" cy="8" r="6"/><path d="M15.477 12.89 17 22l-5-3-5 3 1.523-9.11"/>'),
  inventory: svg('<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>'),
  accounting: svg('<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/><path d="M8 7h6"/><path d="M8 11h8"/>'),
  close: svg('<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>'),
  workforce: svg('<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>'),
  documents: svg('<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>'),
  treasury: svg('<line x1="3" y1="22" x2="21" y2="22"/><line x1="6" y1="18" x2="6" y2="11"/><line x1="10" y1="18" x2="10" y2="11"/><line x1="14" y1="18" x2="14" y2="11"/><line x1="18" y1="18" x2="18" y2="11"/><polygon points="12 2 20 7 4 7"/>'),
  billing: svg('<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>'),
};

export function formatMoney(cents: number | undefined | null): string {
  return new Intl.NumberFormat('en-IE', {
    style: 'currency',
    currency: 'EUR',
  }).format((cents || 0) / 100);
}

export function resolveApiBase(): string {
  return window.location.pathname.replace(/\/(workspace\/?)?$/, '');
}

import { syncAgTheme } from './ag_grid_bridge';
import { renderDashboard, renderList } from './runtime_dashboard_list';
import { renderDetail, renderTargets } from './runtime_detail_targets';
import { renderStatements } from './runtime_statements';
import { renderServices } from './runtime_services_a';
import { consumePayPalOidcCallbackIfPresent } from './runtime_paypal';
import { cents, csv, download, downloadPdfBase64, fetchAndDownloadPdf, createFormHandlers } from './runtime_forms';
import { MODULES, MODULE_BOUNDED_CONTEXT, MODULE_ICONS, NAVIGATION_GROUPS, formatMoney, resolveApiBase } from './api/client';

declare global {
  interface Window {
    __KERDON_INITIAL_TENANTS__?: Array<{ tenant_id: string; display_name: string }>;
  }
}

const NUMERIC_HEADER_RE =
  /\b(net|vat|gross|paid|outstanding|amount|balance|debit|credit|revenue|cash|cost|price|valuation|qty|quantity|target|actual|remaining|allocated|invoiced|ebitda|withheld|fee|inflow|outflow|lines|count|attainment)\b|%/i;

function isNumericCellValue(raw: string): boolean {
  const plain = raw.replace(/<[^>]+>/g, '').trim();
  if (!plain || plain === '-') return false;
  return /^[+-]?€\s?[\d,]+(\.\d+)?$/.test(plain) || /^€[\d,.-]+/.test(plain) || /^-?[\d,]+(\.\d+)?\s?(%|x|pcs|days|docs)?$/.test(plain);
}

const ROLE_ALLOWED_MODULES: Record<string, Set<string> | null> = {
  MSP_FINOPS_DIRECTOR: null,
  CLIENT_OWNER: null,
  ACCOUNTANT: new Set([
    'dashboard', 'statements', 'customers', 'suppliers', 'sales', 'purchases',
    'expenses', 'payments', 'receipts', 'accounting', 'paypal', 'close',
    'workforce', 'documents', 'intelligence', 'billing',
  ]),
  STORE_MANAGER: new Set([
    'dashboard', 'statements', 'customers', 'suppliers', 'sales', 'purchases',
    'expenses', 'receipts', 'targets', 'commissions', 'inventory', 'paypal',
    'documents', 'billing',
  ]),
  SELLER: new Set(['commissions', 'billing']),
  PUBLIC_AUDITOR: new Set(['dashboard', 'statements', 'accounting', 'paypal', 'close', 'documents', 'billing']),
};

export function mountWorkspaceRuntime(): void {
  const $ = (id: string) => document.getElementById(id) as any;
  const esc = (v: unknown) =>
    String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] || c));
  const money = (c: number) => formatMoney(c);
  const base = resolveApiBase();
  const modules: Record<string, string> = MODULES;
  const groups = NAVIGATION_GROUPS;
  const icons: Record<string, string> = MODULE_ICONS;
  const bcMeta: Record<string, { code: string; name: string; standard: string }> = MODULE_BOUNDED_CONTEXT;

  let data: any = null;
  let lang: 'en' | 'el' = 'en';
  let activeRole = 'MSP_FINOPS_DIRECTOR';
  const t = (en: string, el: string) => (lang === 'el' ? el : en);

  const MODULES_EL: Record<string, string> = {
    dashboard: 'Πίνακας Ελέγχου',
    statements: 'Οικονομικές Καταστάσεις',
    customers: 'Πελάτες',
    sales: 'Πωλήσεις',
    receipts: 'Εισπράξεις',
    targets: 'Στόχοι Πωλήσεων',
    commissions: 'Προμήθειες',
    suppliers: 'Προμηθευτές',
    purchases: 'Αγορές',
    expenses: 'Έξοδα',
    payments: 'Πληρωμές',
    inventory: 'Αποθήκη',
    accounting: 'Λογιστική & Ημερολόγιο',
    paypal: 'PayPal & Agentic Commerce',
    treasury: 'Διαθέσιμα & Εγκρίσεις',
    workforce: 'Μισθοδοσία & ΦΠΑ',
    close: 'Κλείσιμο & Πληρότητα',
    documents: 'Inbox & Παραστατικά',
    intelligence: 'Ερώτηση στο Kerdon AI',
    billing: 'Οργανισμός, Ρόλοι & Connectors',
  };
  const GROUPS_EL: Record<string, string> = {
    'Overview & Intelligence': 'Επισκόπηση & Καταστάσεις CFO',
    'Order-to-Cash (AR)': 'Πωλήσεις & Εισπράξεις (AR)',
    'Procure-to-Pay (AP)': 'Αγορές & Πληρωμές (AP)',
    'Sales & Commissions': 'Πωλήσεις & Προμήθειες',
    'Inventory & Supply Chain': 'Αποθήκη & Εφοδιαστική Αλυσίδα',
    'Record-to-Report (GL & Tax)': 'Λογιστήριο, Μισθοδοσία & ΦΠΑ',
    'Treasury & Governance': 'Διαθέσιμα & Διακυβέρνηση',
  };
  const modLabel = (m: string) => (lang === 'el' ? MODULES_EL[m] || modules[m] : modules[m]);
  const grpLabel = (g: string) => (lang === 'el' ? GROUPS_EL[g] || g : g);

  let module = 'dashboard';
  let selected = '';
  let tab = 'General';
  let eventIds: string[] | null = null;
  let kpiFilter = '';
  let listStatusFilter = '';
  let target: number | null = null;
  let generation = 0;
  let inFlightMutations = 0;

  async function api(pathStr: string, body?: Record<string, unknown>, extraHeaders?: Record<string, string>): Promise<any> {
    const hdrs: Record<string, string> = body ? { 'Content-Type': 'application/json' } : {};
    if ($('tenant') && $('tenant').value) hdrs['X-Active-Tenant'] = $('tenant').value;
    if (activeRole) hdrs['X-Kerdon-Role'] = activeRole;
    if (extraHeaders) Object.assign(hdrs, extraHeaders);
    if (body) {
      inFlightMutations += 1;
      if ($('connection')) $('connection').textContent = 'Processing…';
    }
    try {
      const r = await fetch(base + pathStr, {
        method: body ? 'POST' : 'GET',
        credentials: 'same-origin',
        headers: hdrs,
        body: body ? JSON.stringify(body) : undefined,
      });
      const text = await r.text();
      let value: any;
      try {
        value = JSON.parse(text);
      } catch {
        throw Error('Unexpected service response [' + r.status + ']');
      }
      if (!r.ok) {
        const dbg =
          value.paypal_debug_id && !String(value.error || '').includes(value.paypal_debug_id)
            ? ' [PayPal debug_id=' + value.paypal_debug_id + ']'
            : '';
        throw Error('Service [' + r.status + ']: ' + (value.error || text) + dbg);
      }
      return value;
    } finally {
      if (body) {
        inFlightMutations = Math.max(0, inFlightMutations - 1);
        if (inFlightMutations === 0 && $('connection') && $('connection').textContent === 'Processing…') {
          $('connection').textContent = 'Connected';
        }
      }
    }
  }

  const tid = () => $('tenant')?.value || '';
  const path = (s: string) => '/erp/' + s;
  const id = (r: any) => r.id || r.document_id || r.event_id;
  const date = (r: any) => r.issued_date || r.posted_date || '';
  const amount = (r: any) => r.gross_cents ?? r.amount_cents ?? 0;
  const status = (r: any) =>
    r.lifecycle_status === 'REVERSED'
      ? 'Reversed'
      : r.document_id
        ? r.paid_cents >= r.gross_cents
          ? 'Paid'
          : r.paid_cents
            ? 'Part paid'
            : 'Open'
        : r.event_id
          ? 'Posted'
          : 'Registered';

  function go(m: string, record = '', tName = 'General', events: string[] | null = null, kpi = '') {
    const q = new URLSearchParams({ module: m });
    if (record) q.set('record', record);
    if (tName !== 'General') q.set('tab', tName);
    if (events) q.set('events', events.join(','));
    if (kpi) q.set('kpi', kpi);
    document.body.classList.remove('menu-open');
    window.location.hash = q.toString();
  }

  const MODULE_ALIASES: Record<string, string> = {
    commercial: 'billing',
    gtm: 'billing',
    overview: 'dashboard',
    reports: 'statements',
    cards: 'statements',
    ask: 'intelligence',
    mydata: 'documents',
    paypal_hub: 'paypal',
  };

  function route() {
    const q = new URLSearchParams(window.location.hash.slice(1));
    const rawMod = q.get('module') || '';
    const resolvedMod = MODULE_ALIASES[rawMod] || rawMod;
    module = modules[resolvedMod] ? resolvedMod : activeRole === 'SELLER' ? 'commissions' : 'dashboard';
    selected = q.get('record') || '';
    tab = q.get('tab') || 'General';
    eventIds = q.has('events') ? (q.get('events') || '').split(',') : null;
    kpiFilter = q.get('kpi') || '';
    listStatusFilter = q.get('status') || '';
    document.body.classList.remove('menu-open');
    render();
  }

  function fail(e: any) {
    $('error').hidden = false;
    $('error').textContent = e.message;
  }

  function fp() {
    return (
      data?.fiscal_profile ||
      data?.connectors?.fiscal_profile || {
        country_code: data?.tenant?.fiscal_identity?.country_code || 'GR',
        country_name: t('Greece', 'Ελλάδα'),
        is_greek_organization: (data?.tenant?.fiscal_identity?.country_code || 'GR') === 'GR',
        aade_mydata_enabled: (data?.tenant?.fiscal_identity?.country_code || 'GR') === 'GR',
        einvoice_standard: 'AADE myDATA REST API v1.0.8 / v1.0.9',
        doy: t('Athens Corporate Tax Office (KEFODE Attikis)', 'ΚΕΦΟΔΕ ΑΤΤΙΚΗΣ'),
        gemi_number: '148920301000',
        statutory_vat_rates: [24, 13, 6, 0],
      }
    );
  }

  function isGreekOrg() {
    return Boolean(fp().is_greek_organization);
  }

  function isPayPalActive() {
    return (data?.connectors?.config?.payment_connector || 'PAYPAL') === 'PAYPAL';
  }

  function updateCompanyHeader() {
    if (!data?.tenant) return;
    const prof = fp();
    const taxId = data.tenant.fiscal_identity?.tax_id || '';
    if ($('sidebar-org-pill')) {
      $('sidebar-org-pill').textContent = prof.is_greek_organization
        ? 'GR · ' + t('TIN ', 'ΑΦΜ ') + taxId + ' · myDATA'
        : (prof.country_code || 'EU') + ' · ' + taxId + ' · Peppol';
    }
    if ($('company-name')) {
      $('company-name').textContent = data.tenant.display_name;
    }
  }

  function syncRoleBadge() {
    const badge = $('role-preview-badge');
    if (!badge) return;
    if (activeRole && activeRole !== 'MSP_FINOPS_DIRECTOR') {
      badge.hidden = false;
      badge.textContent = t('Role Preview: ' + activeRole + ' · Reset ×', 'Προεπισκόπηση Ρόλου: ' + activeRole + ' · Επαναφορά ×');
    } else {
      badge.hidden = true;
    }
  }

  async function setActiveRole(nextRole: string) {
    activeRole = nextRole || 'MSP_FINOPS_DIRECTOR';
    syncRoleBadge();
    const allowed = ROLE_ALLOWED_MODULES[activeRole];
    if (allowed && !allowed.has(module)) {
      module = activeRole === 'SELLER' ? 'commissions' : 'dashboard';
      window.location.hash = 'module=' + module;
    }
    await load();
  }

  async function load(customNotice?: unknown) {
    const noticeOverride = typeof customNotice === 'string' ? customNotice : '';
    const n = ++generation;
    try {
      $('connection').textContent = 'Refreshing';
      if (activeRole === 'SELLER') {
        const comm = await api(path('commissions'));
        if (n !== generation) return;
        data = {
          tenant: { tenant_id: tid(), display_name: $('tenant')?.selectedOptions?.[0]?.textContent || tid() },
          durability: 'in-memory',
          dashboard: { start: '2026-10-01', end: '2026-10-31', kpis: { cash: { cents: 0, event_ids: [] }, revenue: { cents: 0, event_ids: [] }, receivables: { cents: 0, event_ids: [] }, payables: { cents: 0, event_ids: [] } }, series: [] },
          records: {},
          ledger: [],
          seller_commissions_preview: comm,
          capabilities: { invoice_submission: false },
        };
        $('connection').textContent = 'Connected';
        $('notice').textContent = t(
          'Seller Restricted RBAC View · Financial statements, bank balances, and supplier payables are isolated (VIEW_OWN_SALES only).',
          'Περιορισμένη Προβολή Πωλητή (RBAC) · Πρόσβαση αποκλειστικά σε ίδιες πωλήσεις και προμήθειες.'
        );
        $('error').hidden = true;
        render();
        return;
      }
      const q = new URLSearchParams();
      if ($('start').value) q.set('start', $('start').value);
      if ($('end').value) q.set('end', $('end').value);
      const r = await api(path('operations') + '?' + q);
      if (n !== generation) return;
      data = r;
      $('start').value = r.dashboard.start;
      $('end').value = r.dashboard.end;
      updateCompanyHeader();
      $('connection').textContent = 'Connected';
      $('notice').textContent =
        noticeOverride ||
        'Executive Financial Operations · ' +
          (r.durability === 'in-memory' ? 'In-memory sandbox state; changes are not durable.' : 'DynamoDB journal & entity versioning active.') +
          ' Cash records reconcile 100% to General Ledger 1000_CASH.';
      $('error').hidden = true;
      render();
    } catch (e) {
      $('connection').textContent = 'Unavailable';
      fail(e);
      $('content').innerHTML = '<div class="empty">Records unavailable. Refresh to retry.</div>';
    }
  }

  function table(headers: string[], rows: string[][]) {
    const colNumeric = headers.map((h, colIdx) => {
      if (colIdx === 0) return false;
      if (NUMERIC_HEADER_RE.test(h.replace(/<[^>]+>/g, ''))) return true;
      return rows.length > 0 && rows.every((r) => isNumericCellValue(String(r[colIdx] ?? '')));
    });
    return (
      '<div class="table-wrap" tabindex="0"><table><thead><tr>' +
      headers.map((h, idx) => '<th' + (colNumeric[idx] ? ' class="num"' : '') + '>' + h + '</th>').join('') +
      '</tr></thead><tbody>' +
      rows
        .map(
          (values) =>
            '<tr>' +
            values
              .map((v, idx) => '<td' + (colNumeric[idx] || isNumericCellValue(String(v ?? '')) ? ' class="num"' : '') + '>' + v + '</td>')
              .join('') +
            '</tr>'
        )
        .join('') +
      '</tbody></table>' +
      (rows.length ? '' : '<div class="empty">No records in this view.</div>') +
      '</div>'
    );
  }

  function link(m: string, record: string, label: string, tName = 'General') {
    return '<button type="button" class="row-link" data-go="' + esc(m) + '" data-id="' + esc(record) + '" data-tab="' + esc(tName) + '">' + esc(label) + '</button>';
  }

  function bind() {
    document.querySelectorAll('[data-go]').forEach((b: any) => {
      b.onclick = () => go(b.dataset.go, b.dataset.id, b.dataset.tab);
    });
  }

  const LABEL_MAP: Record<string, string> = {
    gross_profit_cents: 'Gross Profit (Net Revenue - COGS)',
    ebitda_cents: 'Operating EBITDA',
    projected_net_cash_cents: 'Projected Ending Cash (After AR/AP)',
    true_employer_cost_cents: 'Total Employer Workforce Cost (GL 6000)',
    gross_wages_cents: 'Gross Employee Salaries',
    employer_social_security_cents: 'Employer Social Security (EFKA)',
    net_salary_payable_cents: 'Net Take-Home Pay (GL 2500)',
    total_apd_payable_cents: 'EFKA Social Security Payable (GL 2510)',
    total_fmy_payable_cents: 'Withheld Payroll Tax Payable (GL 2520)',
    bank_only_understatement_prevented_cents: 'P&L Understatement Prevented vs Bank Feed',
    selected_dashboard_kpi: 'Selected Dashboard KPI',
    gl_account_basis: 'General Ledger Account Basis',
    dashboard_tile_cents: 'Dashboard KPI Balance',
    reconciled_events_sum_cents: 'Reconciled Journal Sum',
    reconciliation_status: 'Reconciliation Audit Status',
    total_liquidity_cents: 'Total Treasury Cash Balance',
    reserve_floor_cents: 'Mandatory Reserve Floor',
    available_above_floor_cents: 'Free Liquidity Above Reserve Floor',
    active_approvals: 'Four-Eyes Approval Queue',
    executed_payout_receipts: 'Executed Payout Receipts',
    total_payable_cents: 'Net Payable Seller Commissions',
    approved_sales_volume_cents: 'Approved Attributed Sales Volume',
    gross_tier_commission_cents: 'Gross Tier Commission Earned',
    clawback_deduction_cents: 'Dispute & Cancellation Clawbacks',
    case_status: 'Monthly Commission Case Status',
    unattributed_sales_queue: 'Unattributed Sales Queue',
    four_eyes_actors: 'Four-Eyes Preparer / Approver',
    total_skus: 'Active Warehouse SKUs',
    total_inventory_valuation_cents: 'Total Inventory Valuation (WAC)',
    total_cogs_cents: 'Posted Cost of Goods Sold (GL 5000)',
    low_stock_alert_count: 'Low-Stock Reorder Alerts',
    auto_reorder_pos_drafted: 'Auto-Drafted Supplier Purchase Orders',
  };

  function prettyLabel(k: string) {
    if (LABEL_MAP[k]) return LABEL_MAP[k];
    const clean = k.replace(/_cents$/, '').replace(/_pct$/, ' %').replaceAll('_', ' ');
    return clean.replace(/\b\w/g, (c) => c.toUpperCase());
  }

  function facts(obj: Record<string, any>) {
    const skip = new Set([
      'lines',
      'line_items',
      'allocations',
      'historical_invoice_cents',
      'tenant_id',
      'afm_validation',
    ]);
    return (
      '<div class="facts">' +
      Object.entries(obj)
        .filter(([k]) => !skip.has(k))
        .map(([k, v]) => {
          const lbl = prettyLabel(k);
          const val =
            k.endsWith('_cents') && typeof v === 'number'
              ? money(v)
              : k.endsWith('_pct') && typeof v === 'number'
                ? v.toFixed(1) + '%'
                : Array.isArray(v)
                  ? v.length + ' items'
                  : v && typeof v === 'object'
                    ? Object.entries(v)
                        .slice(0, 4)
                        .map(([sk, sv]) => prettyLabel(sk) + ': ' + (sk.endsWith('_cents') && typeof sv === 'number' ? money(sv) : sv))
                        .join(' · ')
                    : v;
          return '<div class="fact"><small>' + esc(lbl) + '</small><strong>' + esc(val) + '</strong></div>';
        })
        .join('') +
      '</div>'
    );
  }

  function hbarChart(title: string, sub: string, items: Array<{ label: string; value: number; text?: string; color?: string }>) {
    const maxVal = Math.max(1, ...items.map((i) => Math.abs(i.value)));
    return (
      '<div class="chart-card"><h3>' +
      esc(title) +
      '</h3><div class="chart-sub">' +
      esc(sub) +
      '</div><div class="hbar-list">' +
      items
        .map((it) => {
          const pct = Math.min(100, Math.max(2, Math.round((Math.abs(it.value) / maxVal) * 100)));
          const clr = it.color || 'var(--primary)';
          return (
            '<div class="hbar-row"><span class="hbar-label" title="' +
            esc(it.label) +
            '">' +
            esc(it.label) +
            '</span><div class="hbar-track"><div class="hbar-fill" style="width:' +
            pct +
            '%;background:' +
            clr +
            '"></div></div><span class="hbar-val">' +
            esc(it.text ?? money(it.value)) +
            '</span></div>'
          );
        })
        .join('') +
      '</div></div>'
    );
  }

  function stackedChart(title: string, sub: string, segs: Array<{ label: string; value: number; color: string }>) {
    const total = Math.max(1, segs.reduce((s, x) => s + Math.max(0, x.value), 0));
    return (
      '<div class="chart-card"><h3>' +
      esc(title) +
      '</h3><div class="chart-sub">' +
      esc(sub) +
      '</div><div class="stacked-bar">' +
      segs
        .filter((s) => s.value > 0)
        .map((s) => {
          const pct = Math.max(2, Math.round((s.value / total) * 100));
          return '<div class="stacked-seg" style="width:' + pct + '%;background:' + s.color + '" title="' + esc(s.label + ': ' + money(s.value)) + '"></div>';
        })
        .join('') +
      '</div><div class="hbar-list" style="margin-top:12px">' +
      segs
        .map((s) => {
          const share = total > 0 ? ((Math.max(0, s.value) / total) * 100).toFixed(1) + '%' : '0.0%';
          return (
            '<div class="hbar-row"><span class="hbar-label"><span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:' +
            s.color +
            ';margin-right:7px"></span>' +
            esc(s.label) +
            '</span><span style="color:var(--muted);font-size:11px">' +
            share +
            '</span><span class="hbar-val">' +
            money(s.value) +
            '</span></div>'
          );
        })
        .join('') +
      '</div></div>'
    );
  }

  function source(docId: string) {
    for (const m of ['sales', 'purchases']) {
      if ((data.records?.[m] || []).some((r: any) => r.document_id === docId)) return link(m, docId, docId);
    }
    return esc(docId || '-');
  }

  function party(partyId: string) {
    for (const m of ['customers', 'suppliers']) {
      const r = (data.records?.[m] || []).find((rec: any) => rec.id === partyId);
      if (r) return link(m, partyId, r.legal_name);
    }
    return esc(partyId || '-');
  }

  function eventKpiImpact(e: any, kpi = '') {
    const lines = e.lines || [];
    if (kpi === 'revenue') {
      return lines.filter((l: any) => String(l.account).startsWith('4')).reduce((s: number, l: any) => s + l.credit_cents - l.debit_cents, 0);
    }
    if (kpi === 'receivables') {
      return lines.filter((l: any) => String(l.account).startsWith('1100_')).reduce((s: number, l: any) => s + l.debit_cents - l.credit_cents, 0);
    }
    if (kpi === 'payables') {
      return lines.filter((l: any) => String(l.account).startsWith('2000_')).reduce((s: number, l: any) => s + l.credit_cents - l.debit_cents, 0);
    }
    return lines.filter((l: any) => String(l.account).startsWith('1000_')).reduce((s: number, l: any) => s + l.debit_cents - l.credit_cents, 0);
  }

  function journal(events: any[], kpi = '') {
    const colLabel =
      kpi === 'revenue'
        ? 'Net revenue (4000/4100)'
        : kpi === 'receivables'
          ? 'AR movement (1100_AR)'
          : kpi === 'payables'
            ? 'AP movement (2000_AP)'
            : 'Cash movement (1000_CASH)';
    const rows = events.map((e) => [
      esc(e.posted_date),
      link('accounting', e.event_id, e.event_id),
      source(e.source_document_id),
      esc(e.description),
      money(eventKpiImpact(e, kpi)),
      money((e.lines || []).reduce((s: number, l: any) => s + l.debit_cents, 0)),
    ]);
    if (rows.length > 1) {
      const totalImpact = events.reduce((s: number, e: any) => s + eventKpiImpact(e, kpi), 0);
      const totalDebit = events.reduce((s: number, e: any) => s + (e.lines || []).reduce((ls: number, l: any) => ls + l.debit_cents, 0), 0);
      rows.push([
        '<strong>Total (' + events.length + ' events)</strong>',
        '-',
        '-',
        '<strong>Reconciled sum of listed events</strong>',
        '<strong>' + money(totalImpact) + '</strong>',
        '<strong>' + money(totalDebit) + '</strong>',
      ]);
    }
    return table(['Date', 'Journal event', 'Source document', 'Description', colLabel, 'Event debit / credit'], rows);
  }

  function journalLines(lines: any[]) {
    return table(
      ['Account', 'Counterparty', 'Debit', 'Credit'],
      lines.map((l) => [esc(l.account), party(l.counterparty_id), money(l.debit_cents), money(l.credit_cents)])
    );
  }

  function shouldShowPeriodFilter(): boolean {
    if (activeRole === 'SELLER') return false;
    if (['dashboard', 'statements', 'accounting', 'sales', 'purchases', 'receipts', 'payments', 'expenses', 'targets'].includes(module)) {
      return !selected || ['Account statement', 'Statistics'].includes(tab);
    }
    if (['customers', 'suppliers'].includes(module) && selected && ['Account statement', 'Statistics'].includes(tab)) {
      return true;
    }
    return false;
  }

  function render() {
    const allowed = ROLE_ALLOWED_MODULES[activeRole];
    $('nav').innerHTML = groups
      .map(([g, items]) => {
        const visibleItems = allowed ? items.filter((m) => allowed.has(m)) : items;
        if (!visibleItems.length) return '';
        return (
          '<div class="nav-group">' +
          esc(grpLabel(g)) +
          '</div>' +
          visibleItems
            .map(
              (m) =>
                '<a aria-label="' +
                modules[m] +
                '" class="nav-link ' +
                (module === m ? 'active' : '') +
                '" href="#module=' +
                m +
                '"><span class="nav-icon" aria-hidden="true">' +
                (icons[m] || '') +
                '</span><span>' +
                esc(modLabel(m)) +
                '</span></a>'
            )
            .join('')
        );
      })
      .join('');

    const bc = bcMeta[module];
    $('title').textContent = modLabel(module);
    $('crumb').textContent = bc ? bc.code + ' · ' + modLabel(module) : 'Workspace / ' + modLabel(module);
    if ($('page-eyebrow') && bc) {
      $('page-eyebrow').textContent = bc.code + ' · ' + bc.standard;
    }
    if ($('j5-tagline')) {
      $('j5-tagline').hidden = module !== 'dashboard';
    }
    if ($('period-bar')) {
      $('period-bar').hidden = !shouldShowPeriodFilter();
    }
    syncRoleBadge();

    if (!data) return;
    if (module === 'dashboard') renderDashboard(ctx);
    else if (module === 'statements') renderStatements(ctx);
    else if (module === 'targets') renderTargets(ctx);
    else if (data.records && data.records[module]) selected ? renderDetail(ctx) : renderList(ctx);
    else renderServices(ctx);
  }

  const ctx: any = {
    $,
    esc,
    money,
    base,
    modules,
    groups,
    icons,
    bcMeta,
    t,
    modLabel,
    grpLabel,
    api,
    tid,
    path,
    id,
    date,
    amount,
    status,
    go,
    route,
    fail,
    fp,
    isGreekOrg,
    isPayPalActive,
    updateCompanyHeader,
    setActiveRole,
    load,
    table,
    link,
    bind,
    prettyLabel,
    facts,
    hbarChart,
    stackedChart,
    source,
    party,
    eventKpiImpact,
    journal,
    journalLines,
    render,
    cents,
    download,
    downloadPdfBase64,
    fetchAndDownloadPdf,
    csv,
    get data() {
      return data;
    },
    get lang() {
      return lang;
    },
    get activeRole() {
      return activeRole;
    },
    get module() {
      return module;
    },
    get selected() {
      return selected;
    },
    get tab() {
      return tab;
    },
    get eventIds() {
      return eventIds;
    },
    get kpiFilter() {
      return kpiFilter;
    },
    get listStatusFilter() {
      return listStatusFilter;
    },
    get target() {
      return target;
    },
    set target(v: number | null) {
      target = v;
    },
  };

  const formHandlers = createFormHandlers(ctx);
  ctx.newDraft = formHandlers.newDraft;
  ctx.openCmd = formHandlers.openCmd;
  formHandlers.bindFormEvents();

  if ($('content')) {
    $('content').addEventListener('click', (ev: MouseEvent) => {
      const targetEl = (ev.target as HTMLElement | null)?.closest?.('[data-go]') as HTMLElement | null;
      if (targetEl) {
        go(targetEl.dataset.go || 'dashboard', targetEl.dataset.id || '', targetEl.dataset.tab || 'General');
      }
    });
  }

  if ($('menu')) $('menu').onclick = () => document.body.classList.toggle('menu-open');
  if ($('theme-toggle')) {
    $('theme-toggle').onclick = () => {
      document.body.classList.toggle('theme-light');
      $('theme-toggle').textContent = document.body.classList.contains('theme-light') ? '☾ Dark' : '☀ Theme';
      syncAgTheme();
    };
  }
  if ($('role-preview-badge')) {
    $('role-preview-badge').onclick = () => setActiveRole('MSP_FINOPS_DIRECTOR');
  }
  $('tenant').onchange = () => {
    target = null;
    load();
  };
  if ($('lang-select')) {
    $('lang-select').onchange = () => {
      lang = $('lang-select').value === 'el' ? 'el' : 'en';
      document.documentElement.lang = lang;
      const elOpt = $('lang-select').querySelector('option[value="el"]');
      if (elOpt) elOpt.textContent = lang === 'el' ? 'EL · Ελληνικά' : 'EL · Greek';
      updateCompanyHeader();
      render();
    };
  }
  $('start').onchange = load;
  $('end').onchange = load;
  if ($('apply')) $('apply').onclick = load;
  $('refresh').onclick = load;
  window.addEventListener('hashchange', route);

  (async () => {
    try {
      let tenants: any[] = [];
      let activeId = '';
      try {
        const orgs = await api('/erp/organizations');
        tenants = orgs.organizations || orgs.tenants || [];
        activeId = orgs.active_tenant_id || '';
      } catch {
        const fallback = await api('/tenants');
        tenants = fallback.tenants || [];
      }
      $('tenant').innerHTML = tenants.map((tItem: any) => '<option value="' + esc(tItem.tenant_id) + '">' + esc(tItem.display_name) + '</option>').join('');
      if (activeId) $('tenant').value = activeId;
      await consumePayPalOidcCallbackIfPresent(ctx);
      route();
      await load();
    } catch (e) {
      fail(e);
    }
  })();
}

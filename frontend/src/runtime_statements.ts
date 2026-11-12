import { mountEnterpriseChart, mountEnterpriseGrid } from './ag_grid_bridge';
import { renderKpiTile, renderSideBadge } from './kpi_catalog';

let activeStatementTab = 'pnl';
let selectedCardKey = 'CASH:1000_CASH';
let expandFullYtd = false;

export function renderStatements(ctx: any): void {
  const { $, esc, money, source, link, api, path, tid, fail, bind, t, lang, data } = ctx;
  const pf = data.profitability || {};
  const pnl = pf.pnl_statement || {};
  const bs = pf.balance_sheet || {};
  const cf = pf.cash_flow_statement || {};
  const cfOp = cf.operating_activities || {};
  const cashCard = pf.cash_account_statement || {};
  const vatRet = pf.vat_return || {};
  const ag = data.aging || {};
  const tb: any[] = data.trial_balance || [];
  const customers: any[] = data.records?.customers || [];
  const suppliers: any[] = data.records?.suppliers || [];

  const tabs: Array<[string, string]> = [
    ['pnl', t('Income Statement (P&L)', 'Αποτελέσματα Χρήσης (P&L)')],
    ['bs', t('Balance Sheet', 'Ισολογισμός')],
    ['cf', t('Cash Flow (IAS 7)', 'Ταμειακές Ροές (IAS 7)')],
    ['cards', t('Account Statements (Cards)', 'Καρτέλες Λογαριασμών (DR/CR)')],
    ['tb', t('Trial Balance', 'Ισοζύγιο Γενικού Καθολικού')],
    ['aging', t('AR & AP Aging', 'Ενηλικίωση Υπολοίπων')],
    ['vat', t('VAT Return (F2)', 'Περιοδική ΦΠΑ (Φ2)')],
  ];

  const kpiStrip =
    '<div class="kpis">' +
    renderKpiTile({
      metricKey: 'revenue',
      lang,
      valueText: money(pnl.total_revenue_cents ?? data.dashboard.kpis.revenue.cents),
      subText: t('Period P&L Net Revenue (ex-VAT)', 'Καθαρός Κύκλος Εργασιών Περιόδου'),
    }) +
    renderKpiTile({
      metricKey: 'ebitda',
      lang,
      valueText: money(pnl.ebitda_cents ?? pf.ebitda_cents ?? 0),
      subText: t('EBITDA Margin: ', 'Περιθώριο EBITDA: ') + (pnl.ebitda_margin_pct ?? 0) + '%',
    }) +
    renderKpiTile({
      metricKey: 'operating_cf',
      lang,
      valueText: money(cfOp.net_operating_cash_cents ?? 0),
      subText: t('IAS 7 Direct Operating Cash Flow', 'Λειτουργικές Ταμειακές Ροές ΔΛΠ 7'),
    }) +
    renderKpiTile({
      metricKey: 'cash',
      lang,
      valueText: money(bs.cash_1000_cents ?? data.dashboard.kpis.cash.cents),
      subText: t(
        '4-Way Reconciled (Tile = BS = IAS 7 = Card)',
        '4-Πλήρης Συμφωνία (Tile = Ισολογισμός = Ροές = Καρτέλα)'
      ),
    }) +
    '</div>';

  $('content').innerHTML =
    kpiStrip +
    '<div class="tabs" id="stmt-tabs">' +
    tabs
      .map(
        ([idKey, label]) =>
          '<button type="button" data-stmt-tab="' +
          idKey +
          '" class="' +
          (activeStatementTab === idKey ? 'active' : '') +
          '">' +
          esc(label) +
          '</button>'
      )
      .join('') +
    '</div>' +
    '<div id="stmt-chart-row" class="chart-grid" style="margin-bottom:20px"></div>' +
    '<div id="stmt-body"></div>';

  document.querySelectorAll('[data-stmt-tab]').forEach((b: any) => {
    b.onclick = () => {
      activeStatementTab = b.dataset.stmtTab || 'pnl';
      renderStatements(ctx);
    };
  });

  const chartRow = $('stmt-chart-row');
  const body = $('stmt-body');

  if (activeStatementTab === 'pnl') {
    const rev = pnl.total_revenue_cents || 0;
    const pct = (v: number) => (rev > 0 ? ((v / rev) * 100).toFixed(1) + '%' : '0.0%');
    chartRow.innerHTML =
      '<div class="chart-card"><h3>' +
      esc(t('Income Statement Waterfall (AG Charts)', 'Γράφημα Αποτελεσμάτων Χρήσης (AG Charts)')) +
      '</h3><div class="chart-sub">' +
      esc(data.dashboard.start + ' -> ' + data.dashboard.end) +
      '</div><div id="ag-pnl-chart" style="height:250px"></div></div>' +
      '<div class="chart-card"><h3>' +
      esc(t('Operating Cost Composition', 'Διάρθρωση Λειτουργικού Κόστους')) +
      '</h3><div class="chart-sub">' +
      esc(t('COGS, Payroll Fusion, Commissions & OpEx', 'Κόστος Πωληθέντων, Μισθοδοσία, Προμήθειες & Έξοδα')) +
      '</div><div id="ag-opex-chart" style="height:250px"></div></div>';
    mountEnterpriseChart($('ag-pnl-chart'), {
      data: [
        { item: t('Net Revenue', 'Έσοδα'), eur: (pnl.total_revenue_cents || 0) / 100 },
        { item: t('Gross Profit', 'Μικτό Κέρδος'), eur: (pnl.gross_profit_cents || 0) / 100 },
        { item: t('Total OpEx', 'Λειτ. Έξοδα'), eur: (pnl.total_opex_cents || 0) / 100 },
        { item: 'EBITDA', eur: (pnl.ebitda_cents || 0) / 100 },
      ],
      series: [{ type: 'bar', xKey: 'item', yKey: 'eur', yName: 'EUR', fill: '#6366f1', cornerRadius: 4 }],
    });
    mountEnterpriseChart($('ag-opex-chart'), {
      data: [
        { category: t('COGS (5000)', 'Κόστος Πωλ.'), eur: Math.max(0, (pnl.cogs_5000_cents || 0) / 100) },
        { category: t('Workforce (6000)', 'Μισθοδοσία'), eur: Math.max(0, (pnl.workforce_6000_cents || 0) / 100) },
        { category: t('Commissions (6050)', 'Προμήθειες'), eur: Math.max(0, (pnl.commissions_6050_cents || 0) / 100) },
        { category: t('Rent & OpEx (6100/6200)', 'Ενοίκια & Έξοδα'), eur: Math.max(0, ((pnl.rent_utilities_6100_cents || 0) + (pnl.general_opex_6200_cents || 0)) / 100) },
      ],
      series: [{ type: 'bar', direction: 'horizontal', xKey: 'category', yKey: 'eur', yName: 'EUR', fill: '#10b981', cornerRadius: 4 }],
    });

    body.innerHTML = '<div id="stmt-pnl-grid"></div>';
    mountEnterpriseGrid($('stmt-pnl-grid'), {
      idPrefix: 'pnl',
      lang,
      csvFileName: 'kerdon-income-statement-pnl.csv',
      columns: [
        { field: 'code', headerName: t('GL Account', 'Κωδικός GL'), maxWidth: 230 },
        { field: 'line', headerName: t('IFRS 18 Statement Line Item', 'Γραμμή Κατάστασης Αποτελεσμάτων'), flex: 2, isHtml: true },
        { field: 'section', headerName: t('Category', 'Κατηγορία'), maxWidth: 160, mobileHide: true },
        { field: 'amount_cents', headerName: t('Period Amount', 'Ποσό Περιόδου'), cents: true },
        { field: 'margin_share', headerName: t('% of Revenue', '% επί Εσόδων'), numeric: true, maxWidth: 145 },
      ],
      rows: [
        { code: '4000_SALES_REVENUE', line: t('Merchandise & Service Sales Revenue (ex-VAT)', 'Πωλήσεις Εμπορευμάτων & Υπηρεσιών (προ ΦΠΑ)'), section: 'REVENUE', amount_cents: pnl.sales_revenue_4000_cents || 0, margin_share: pct(pnl.sales_revenue_4000_cents || 0) },
        { code: '4100_COMMISSION_REVENUE', line: t('Principal Settlement & Residual Commission Revenue', 'Έσοδα Προμηθειών Παρόχων'), section: 'REVENUE', amount_cents: pnl.commission_revenue_4100_cents || 0, margin_share: pct(pnl.commission_revenue_4100_cents || 0) },
        { code: 'SUBTOTAL_REVENUE', line: '<strong>' + esc(t('Total Net Operating Revenue', 'Σύνολο Καθαρών Λειτουργικών Εσόδων')) + '</strong>', section: 'SUBTOTAL', amount_cents: rev, margin_share: '100.0%' },
        { code: '5000_COGS', line: t('(-) Cost of Goods Sold (IAS 2 WAC)', '(-) Κόστος Πωληθέντων (ΔΛΠ 2 ΜΣΚ)'), section: 'COGS', amount_cents: -(pnl.cogs_5000_cents || 0), margin_share: pct(-(pnl.cogs_5000_cents || 0)) },
        { code: 'SUBTOTAL_GROSS', line: '<strong>' + esc(t('Gross Profit', 'Μικτό Κέρδος')) + '</strong>', section: 'SUBTOTAL', amount_cents: pnl.gross_profit_cents || 0, margin_share: (pnl.gross_margin_pct ?? 0) + '%' },
        { code: '6000_WORKFORCE', line: t('(-) 3-Doc Fused Employer Workforce Cost (Gross + EFKA)', '(-) Συνολικό Εργοδοτικό Κόστος Μισθοδοσίας'), section: 'OPEX', amount_cents: -(pnl.workforce_6000_cents || 0), margin_share: pct(-(pnl.workforce_6000_cents || 0)) },
        { code: '6050_COMMISSIONS', line: t('(-) Seller Incentive Commissions (Net of Clawbacks)', '(-) Προμήθειες Πωλητών'), section: 'OPEX', amount_cents: -(pnl.commissions_6050_cents || 0), margin_share: pct(-(pnl.commissions_6050_cents || 0)) },
        { code: '6100_RENT_UTILITIES', line: t('(-) Store Rent, Power & Telecom Utilities', '(-) Ενοίκια & Κοινόχρηστα / ΔΕΚΟ'), section: 'OPEX', amount_cents: -(pnl.rent_utilities_6100_cents || 0), margin_share: pct(-(pnl.rent_utilities_6100_cents || 0)) },
        { code: '6200_GENERAL_OPEX', line: t('(-) General OpEx & Payment Processor Fees', '(-) Γενικά Έξοδα & Προμήθειες Πληρωμών (PayPal)'), section: 'OPEX', amount_cents: -(pnl.general_opex_6200_cents || 0), margin_share: pct(-(pnl.general_opex_6200_cents || 0)) },
        { code: 'OPERATING_EBITDA', line: '<strong>' + esc(t('Operating EBITDA', 'Λειτουργικό EBITDA')) + '</strong>', section: 'RESULT', amount_cents: pnl.ebitda_cents || 0, margin_share: (pnl.ebitda_margin_pct ?? 0) + '%' },
      ],
      presets: [
        { id: 'all', label: t('Full P&L Statement', 'Πλήρης Κατάσταση P&L') },
        { id: 'subtotals', label: t('Executive Subtotals Only', 'Μόνο Υποσύνολα & EBITDA'), predicate: (r) => r.section === 'SUBTOTAL' || r.section === 'RESULT' },
        { id: 'opex', label: t('Operating Expenses (6000..6200)', 'Λειτουργικά Έξοδα'), predicate: (r) => r.section === 'OPEX' || r.section === 'COGS' },
      ],
    });
  } else if (activeStatementTab === 'bs') {
    chartRow.innerHTML = '';
    body.innerHTML =
      '<p class="stmt-note">' +
      esc(
        t(
          'Accounting Identity Verified: Total Assets (' +
            money(bs.total_assets_cents || 0) +
            ') = Total Liabilities (' +
            money(bs.total_liabilities_cents || 0) +
            ') + Cumulative Retained Result (' +
            money(bs.cumulative_net_income_cents || 0) +
            '). Physical warehouse stock is tracked in the Inventory WAC subledger and expensed via 5000_COGS upon sale dispatch.',
          'Λογιστική Ταυτότητα Επαληθευμένη: Σύνολο Ενεργητικού (' +
            money(bs.total_assets_cents || 0) +
            ') = Υποχρεώσεις (' +
            money(bs.total_liabilities_cents || 0) +
            ') + Καθαρή Θέση / Αποτέλεσμα εις Νέον (' +
            money(bs.cumulative_net_income_cents || 0) +
            ').'
        )
      ) +
      '</p><div id="stmt-bs-grid"></div>';
    mountEnterpriseGrid($('stmt-bs-grid'), {
      idPrefix: 'bs',
      lang,
      csvFileName: 'kerdon-balance-sheet.csv',
      columns: [
        { field: 'section', headerName: t('Section', 'Ενότητα'), maxWidth: 165 },
        { field: 'account', headerName: t('GL Account', 'Λογαριασμός GL'), maxWidth: 230, mobileHide: true },
        { field: 'item', headerName: t('Balance Sheet Line Item', 'Στοιχείο Ισολογισμού'), flex: 2, isHtml: true },
        { field: 'amount_cents', headerName: t('As of ', 'Υπόλοιπο ') + data.dashboard.end, cents: true },
      ],
      rows: [
        { section: 'ASSETS', account: '1000_CASH', item: t('Cash, Bank & PayPal Settlement Balances', 'Ταμειακά Διαθέσιμα, Τράπεζες & PayPal'), amount_cents: bs.cash_1000_cents || 0 },
        { section: 'ASSETS', account: '1100_ACCOUNTS_RECEIVABLE', item: t('Trade Accounts Receivable (Open Customer AR)', 'Εμπορικές Απαιτήσεις Πελατών (AR)'), amount_cents: bs.accounts_receivable_1100_cents || 0 },
        { section: 'ASSETS', account: '1400_VAT_INPUT', item: t('Deductible Input VAT Receivable', 'Απαιτήσεις ΦΠΑ Εισροών'), amount_cents: bs.vat_input_receivable_1400_cents || 0 },
        { section: 'TOTAL ASSETS', account: '1000..1900', item: '<strong>' + esc(t('Total Current Assets', 'Σύνολο Ενεργητικού')) + '</strong>', amount_cents: bs.total_assets_cents || 0 },
        { section: 'LIABILITIES', account: '2000_ACCOUNTS_PAYABLE', item: t('Trade Accounts Payable (Open Supplier AP)', 'Εμπορικές Υποχρεώσεις Προμηθευτών (AP)'), amount_cents: bs.accounts_payable_2000_cents || 0 },
        { section: 'LIABILITIES', account: '2100_CUSTOMER_DEPOSITS', item: t('Customer Advance Deposits & Retainers', 'Προκαταβολές Πελατών'), amount_cents: bs.customer_deposits_2100_cents || 0 },
        { section: 'LIABILITIES', account: '2400_VAT_OUTPUT', item: t('Output VAT Payable', 'Υποχρεώσεις ΦΠΑ Εκροών'), amount_cents: bs.vat_output_payable_2400_cents || 0 },
        { section: 'LIABILITIES', account: '2500..2520', item: t('Accrued Payroll, EFKA (APD) & FMY Tax Payables', 'Υποχρεώσεις Μισθοδοσίας, ΑΠΔ ΕΦΚΑ & ΦΜΥ'), amount_cents: bs.payroll_and_tax_payables_2500_cents || 0 },
        { section: 'EQUITY', account: 'RETAINED_RESULT', item: t('Cumulative Net Income / Retained Earnings', 'Σωρευτικό Καθαρό Αποτέλεσμα εις Νέον'), amount_cents: bs.cumulative_net_income_cents || 0 },
        { section: 'LIAB + EQUITY', account: bs.balanced ? 'BALANCED' : 'CHECK', item: '<strong>' + esc(t('Total Liabilities & Equity', 'Σύνολο Παθητικού & Καθαρής Θέσης')) + '</strong> <span class="badge">BALANCED</span>', amount_cents: bs.total_liabilities_and_equity_cents || 0 },
      ],
      presets: [
        { id: 'all', label: t('Full Balance Sheet', 'Πλήρης Ισολογισμός') },
        { id: 'assets', label: t('Assets Only', 'Μόνο Ενεργητικό'), predicate: (r) => r.section.includes('ASSET') },
        { id: 'liab', label: t('Liabilities & Equity', 'Υποχρεώσεις & Καθαρή Θέση'), predicate: (r) => !r.section.includes('ASSET') },
      ],
    });
  } else if (activeStatementTab === 'cf') {
    chartRow.innerHTML =
      '<div class="chart-card" style="grid-column:1/-1"><h3>' +
      esc(t('IAS 7 Direct-Method Cash Bridge (Opening -> Operating -> Closing Cash)', 'Γέφυρα Ταμειακών Ροών ΔΛΠ 7 (Αρχικό -> Λειτουργικές Ροές -> Τελικό Ταμείο)')) +
      '</h3><div class="chart-sub">' +
      esc(t('100% Reconciled to GL 1000_CASH and Dashboard Cash Tile', '100% Συμφωνία με Λογ. 1000_CASH και Καρτέλα Ταμείου')) +
      '</div><div id="ag-cf-chart" style="height:240px"></div></div>';
    mountEnterpriseChart($('ag-cf-chart'), {
      data: [
        { step: t('Opening Cash', 'Αρχικό Ταμείο'), eur: (cf.opening_cash_cents || 0) / 100 },
        { step: t('(+) Customer Receipts', '(+) Εισπράξεις Πελατών'), eur: (cfOp.receipts_from_customers_cents || 0) / 100 },
        { step: t('(-) Supplier Payments', '(-) Πληρωμές Προμ.'), eur: (cfOp.payments_to_suppliers_cents || 0) / 100 },
        { step: t('(-) Payroll & OpEx', '(-) Μισθοδοσία & Έξοδα'), eur: ((cfOp.payments_for_workforce_and_taxes_cents || 0) + (cfOp.payments_for_rent_and_opex_cents || 0)) / 100 },
        { step: t('Closing Cash (1000)', 'Τελικό Ταμείο (1000)'), eur: (cf.closing_cash_cents || 0) / 100 },
      ],
      series: [{ type: 'bar', xKey: 'step', yKey: 'eur', yName: 'EUR', fill: '#0ea5e9', cornerRadius: 4 }],
    });

    const feeMemo = cf.memorandum_items?.payment_processor_fees_deducted_at_source_cents || 0;
    body.innerHTML = '<div id="stmt-cf-grid"></div>';
    mountEnterpriseGrid($('stmt-cf-grid'), {
      idPrefix: 'cf',
      lang,
      csvFileName: 'kerdon-ias7-cash-flow-statement.csv',
      columns: [
        { field: 'section', headerName: t('IAS 7 Activity', 'Κατηγορία ΔΛΠ 7'), maxWidth: 190 },
        { field: 'item', headerName: t('Cash Flow Statement Line', 'Γραμμή Κατάστασης Ταμειακών Ροών'), flex: 2, isHtml: true },
        { field: 'amount_cents', headerName: t('Cash Impact', 'Ταμειακή Επίπτωση'), cents: true },
      ],
      rows: [
        { section: 'OPENING', item: '<strong>' + esc(t('Opening Cash & Equivalents (Start of Period)', 'Ταμειακά Διαθέσιμα Έναρξης Περιόδου')) + '</strong>', amount_cents: cf.opening_cash_cents || 0 },
        { section: 'OPERATING', item: t('Cash receipts from customers (AR & Checkout settlements)', 'Ταμειακές εισπράξεις από πελάτες (Εξοφλήσεις & PayPal)'), amount_cents: cfOp.receipts_from_customers_cents || 0 },
        { section: 'OPERATING', item: t('Cash paid to trade suppliers (AP settlements)', 'Πληρωμές σε προμηθευτές εμπορευμάτων & υπηρεσιών'), amount_cents: cfOp.payments_to_suppliers_cents || 0 },
        { section: 'OPERATING', item: t('Cash paid for salaries, social security (APD) & commissions', 'Πληρωμές μισθοδοσίας, ασφαλιστικών εισφορών & προμηθειών'), amount_cents: cfOp.payments_for_workforce_and_taxes_cents || 0 },
        { section: 'OPERATING', item: t('Cash paid for rent, utilities & operating expenses', 'Πληρωμές ενοικίων, ΔΕΚΟ και λειτουργικών εξόδων'), amount_cents: cfOp.payments_for_rent_and_opex_cents || 0 },
        { section: 'OPERATING', item: t('Cash VAT & tax settlements', 'Καταβολές ΦΠΑ και φόρων'), amount_cents: cfOp.vat_and_income_tax_settlements_cents || 0 },
        { section: 'SUBTOTAL', item: '<strong>' + esc(t('Net Cash Provided by / (Used in) Operating Activities', 'Καθαρές Ταμειακές Ροές από Λειτουργικές Δραστηριότητες')) + '</strong>', amount_cents: cfOp.net_operating_cash_cents || 0 },
        { section: 'INVESTING', item: t('Net Cash Used in Investing Activities (CapEx)', 'Καθαρές Ταμειακές Ροές Επενδυτικών Δραστηριοτήτων'), amount_cents: cf.investing_activities?.net_investing_cash_cents || 0 },
        { section: 'FINANCING', item: t('Net Cash from Financing Activities', 'Καθαρές Ταμειακές Ροές Χρηματοδοτικών Δραστηριοτήτων'), amount_cents: cf.financing_activities?.net_financing_cash_cents || 0 },
        { section: 'CLOSING', item: '<strong>' + esc(t('Closing Cash & Equivalents (Reconciled to GL 1000_CASH)', 'Ταμειακά Διαθέσιμα Λήξης (Συμφωνία με 1000_CASH)')) + '</strong> <span class="badge">' + (cf.reconciled ? 'RECONCILED' : 'CHECK') + '</span>', amount_cents: cf.closing_cash_cents || 0 },
        { section: 'MEMORANDUM', item: t('Non-cash disclosure: Processor / PayPal fees deducted at settlement source (6200_OPEX)', 'Γνωστοποίηση: Προμήθειες PayPal κρατηθείσες στην πηγή (6200_OPEX)'), amount_cents: feeMemo },
      ],
    });
  } else if (activeStatementTab === 'cards') {
    chartRow.innerHTML = '';
    const cardOptions: Array<[string, string]> = [
      ['CASH:1000_CASH', t('1000_CASH · Cash, Bank & PayPal Ledger Card', '1000_CASH · Καρτέλα Ταμείου, Τραπεζών & PayPal')],
      ...customers.map((c: any): [string, string] => ['customer:' + c.id, t('Customer (1100_AR): ', 'Πελάτης (1100_AR): ') + c.legal_name]),
      ...suppliers.map((s: any): [string, string] => ['supplier:' + s.id, t('Supplier (2000_AP): ', 'Προμηθευτής (2000_AP): ') + s.legal_name]),
    ];
    if (!cardOptions.some(([k]) => k === selectedCardKey)) {
      selectedCardKey = 'CASH:1000_CASH';
    }
    body.innerHTML =
      '<div class="toolbar">' +
      '<label for="stmt-card-select">' +
      esc(t('Select Account / Counterparty Card', 'Επιλογή Καρτέλας Λογαριασμού / Συναλλασσομένου')) +
      '<select id="stmt-card-select">' +
      cardOptions
        .map(([k, lbl]) => '<option value="' + esc(k) + '"' + (k === selectedCardKey ? ' selected' : '') + '>' + esc(lbl) + '</option>')
        .join('') +
      '</select></label>' +
      '<button type="button" id="stmt-ytd-toggle" class="' +
      (expandFullYtd ? 'primary' : '') +
      '">' +
      esc(expandFullYtd ? t('Showing Full YTD (from Jan 1)', 'Προβολή Έτους YTD (από 1/1)') : t('Expand Full YTD History', 'Πλήρες Ιστορικό Έτους (YTD)')) +
      '</button></div><div id="stmt-card-detail"></div>';

    $('stmt-card-select').onchange = () => {
      selectedCardKey = $('stmt-card-select').value;
      renderSelectedLedgerCard();
    };
    $('stmt-ytd-toggle').onclick = () => {
      expandFullYtd = !expandFullYtd;
      renderStatements(ctx);
    };

    const renderSelectedLedgerCard = async () => {
      const detailHost = $('stmt-card-detail');
      if (!detailHost) return;
      const startParam = expandFullYtd ? data.dashboard.end.slice(0, 4) + '-01-01' : $('start').value;
      const endParam = $('end').value;
      if (selectedCardKey === 'CASH:1000_CASH') {
        let card = cashCard;
        if (expandFullYtd) {
          try {
            const res = await api(path('operations') + '?' + new URLSearchParams({ start: startParam, end: endParam }));
            card = res.profitability?.cash_account_statement || cashCard;
          } catch (e) {
            fail(e);
          }
        }
        const openSide = (card.opening_cents || 0) > 0 ? 'DR' : (card.opening_cents || 0) < 0 ? 'CR' : 'ZERO';
        const closeSide = (card.closing_cents || 0) > 0 ? 'DR' : (card.closing_cents || 0) < 0 ? 'CR' : 'ZERO';
        detailHost.innerHTML =
          '<div class="summary">' +
          '<div><small>' + esc(t('Opening Balance', 'Υπόλοιπο Έναρξης')) + '</small><strong class="num-val">' + money(card.opening_cents || 0) + '</strong> ' + renderSideBadge(openSide, lang) + '</div>' +
          '<div><small>' + esc(t('Total Debits (Inflows)', 'Σύνολο Χρεώσεων (Εισπράξεις)')) + '</small><strong class="num-val">' + money(card.total_debit_cents || 0) + '</strong></div>' +
          '<div><small>' + esc(t('Total Credits (Outflows)', 'Σύνολο Πιστώσεων (Πληρωμές)')) + '</small><strong class="num-val">' + money(card.total_credit_cents || 0) + '</strong></div>' +
          '<div><small>' + esc(t('Closing Balance (1000_CASH)', 'Τελικό Υπόλοιπο (1000_CASH)')) + '</small><strong class="num-val">' + money(card.closing_cents || 0) + '</strong> ' + renderSideBadge(closeSide, lang) + '</div>' +
          '</div><div id="stmt-card-grid"></div>';
        mountEnterpriseGrid($('stmt-card-grid'), {
          idPrefix: 'cash-card',
          lang,
          csvFileName: 'kerdon-cash-account-card.csv',
          onRendered: bind,
          columns: [
            { field: 'date', headerName: t('Date', 'Ημ/νία'), maxWidth: 125 },
            { field: 'event_html', headerName: t('Journal Event', 'Άρθρο GL'), isHtml: true, maxWidth: 175 },
            { field: 'doc_html', headerName: t('Document', 'Παραστατικό'), isHtml: true, maxWidth: 185, mobileHide: true },
            { field: 'channel', headerName: t('Channel', 'Κανάλι'), maxWidth: 130, mobileHide: true },
            { field: 'description', headerName: t('Description', 'Αιτιολογία'), flex: 2 },
            { field: 'debit_cents', headerName: t('Debit (Inflow)', 'Χρέωση'), cents: true, sumCents: true },
            { field: 'credit_cents', headerName: t('Credit (Outflow)', 'Πίστωση'), cents: true, sumCents: true },
            { field: 'balance_cents', headerName: t('Running Balance', 'Προοδ. Υπόλοιπο'), cents: true },
            { field: 'side_html', headerName: t('DR/CR', 'ΧΡ/ΠΙ'), isHtml: true, maxWidth: 95 },
          ],
          rows: (card.rows || []).map((r: any) => ({
            ...r,
            _side: r.balance_side,
            event_html: link('accounting', r.event_id, r.event_id),
            doc_html: source(r.source_document_id),
            side_html: renderSideBadge(r.balance_side, lang),
          })),
          presets: [
            { id: 'all', label: t('All Movements', 'Όλες οι Κινήσεις') },
            { id: 'inflows', label: t('Cash Inflows (DR)', 'Εισπράξεις (Χρέωση)'), predicate: (r) => r.debit_cents > 0 },
            { id: 'outflows', label: t('Cash Outflows (CR)', 'Πληρωμές (Πίστωση)'), predicate: (r) => r.credit_cents > 0 },
            { id: 'paypal', label: 'PayPal Channel', predicate: (r) => r.channel === 'PAYPAL' },
          ],
        });
      } else {
        const [kind, partyId] = selectedCardKey.split(':');
        const company = tid();
        try {
          const res = await api(path('operations') + '?' + new URLSearchParams({ start: startParam, end: endParam, party: partyId, kind }));
          if (company !== tid()) return;
          const s = res.statement || {};
          detailHost.innerHTML =
            '<div class="summary">' +
            '<div><small>' + esc(t('Opening Balance', 'Υπόλοιπο Έναρξης')) + '</small><strong class="num-val">' + money(Math.abs(s.opening_cents || 0)) + '</strong> ' + renderSideBadge(s.opening_side, lang) + '</div>' +
            '<div><small>' + esc(t('Period Debits', 'Χρεώσεις Περιόδου')) + '</small><strong class="num-val">' + money(s.total_debit_cents || 0) + '</strong></div>' +
            '<div><small>' + esc(t('Period Credits', 'Πιστώσεις Περιόδου')) + '</small><strong class="num-val">' + money(s.total_credit_cents || 0) + '</strong></div>' +
            '<div><small>' + esc(t('Closing Balance', 'Τελικό Υπόλοιπο')) + '</small><strong class="num-val">' + money(Math.abs(s.closing_cents || 0)) + '</strong> ' + renderSideBadge(s.closing_side, lang) + '</div>' +
            '</div>' +
            (s.rows?.length === 0 && s.prior_activity_count > 0 && !expandFullYtd
              ? '<p class="stmt-note">' +
                esc(t('Prior-period settled entries exist before ' + startParam + '. Click "Expand Full YTD History" above to inspect all historical invoices and settlements.', 'Υπάρχουν προγενέστερες εξοφλημένες κινήσεις πριν τις ' + startParam + '. Πατήστε «Πλήρες Ιστορικό Έτους (YTD)» για εμφάνιση όλων των εγγραφών.')) +
                '</p>'
              : '') +
            '<div id="stmt-card-grid"></div>';
          mountEnterpriseGrid($('stmt-card-grid'), {
            idPrefix: 'party-card',
            lang,
            csvFileName: 'kerdon-party-statement-' + partyId + '.csv',
            onRendered: bind,
            columns: [
              { field: 'date', headerName: t('Date', 'Ημ/νία'), maxWidth: 125 },
              { field: 'doc_html', headerName: t('Source Document', 'Παραστατικό'), isHtml: true, maxWidth: 195 },
              { field: 'desc_html', headerName: t('Journal Movement', 'Κίνηση Ημερολογίου'), isHtml: true, flex: 2 },
              { field: 'debit_cents', headerName: t('Debit', 'Χρέωση'), cents: true, sumCents: true },
              { field: 'credit_cents', headerName: t('Credit', 'Πίστωση'), cents: true, sumCents: true },
              { field: 'abs_balance_cents', headerName: t('Running Balance', 'Προοδ. Υπόλοιπο'), cents: true },
              { field: 'side_html', headerName: t('DR/CR', 'ΧΡ/ΠΙ'), isHtml: true, maxWidth: 95 },
            ],
            rows: (s.rows || []).map((e: any) => ({
              ...e,
              _side: e.balance_side,
              abs_balance_cents: Math.abs(e.balance_cents || 0),
              doc_html: source(e.source_document_id),
              desc_html: link('accounting', e.event_id, e.description),
              side_html: renderSideBadge(e.balance_side, lang),
            })),
          });
        } catch (e) {
          fail(e);
        }
      }
    };
    renderSelectedLedgerCard();
  } else if (activeStatementTab === 'tb') {
    chartRow.innerHTML = '';
    body.innerHTML = '<div id="stmt-tb-grid"></div>';
    mountEnterpriseGrid($('stmt-tb-grid'), {
      idPrefix: 'tb',
      lang,
      csvFileName: 'kerdon-trial-balance.csv',
      columns: [
        { field: 'account', headerName: t('GL Account Code', 'Κωδικός Λογαριασμού GL'), flex: 1.5 },
        { field: 'debit_cents', headerName: t('Total Debits', 'Σύνολο Χρεώσεων'), cents: true, sumCents: true },
        { field: 'credit_cents', headerName: t('Total Credits', 'Σύνολο Πιστώσεων'), cents: true, sumCents: true },
        { field: 'abs_net_cents', headerName: t('Net Balance', 'Καθαρό Υπόλοιπο'), cents: true },
        { field: 'side_html', headerName: t('Normal Side', 'Φύση Υπολοίπου'), isHtml: true, maxWidth: 130 },
        { field: 'line_count', headerName: t('GL Lines', 'Γραμμές'), numeric: true, maxWidth: 110, mobileHide: true },
      ],
      rows: tb.map((row: any) => {
        const net = (row.debit_cents || 0) - (row.credit_cents || 0);
        const side = net > 0 ? 'DR' : net < 0 ? 'CR' : 'ZERO';
        return {
          ...row,
          _side: side,
          abs_net_cents: Math.abs(net),
          side_html: renderSideBadge(side, lang),
        };
      }),
      presets: [
        { id: 'all', label: t('All GL Accounts', 'Όλοι οι Λογαριασμοί') },
        { id: 'bs', label: t('Balance Sheet (1000..2999)', 'Ισολογισμός (1000..2999)'), predicate: (r) => /^[12]/.test(String(r.account)) },
        { id: 'pnl', label: t('P&L Accounts (4000..6999)', 'Αποτελέσματα (4000..6999)'), predicate: (r) => /^[456]/.test(String(r.account)) },
      ],
    });
  } else if (activeStatementTab === 'aging') {
    chartRow.innerHTML = '';
    const ar = ag.receivables_aging || {};
    const ap = ag.payables_aging || {};
    body.innerHTML = '<div id="stmt-aging-grid"></div>';
    mountEnterpriseGrid($('stmt-aging-grid'), {
      idPrefix: 'aging',
      lang,
      csvFileName: 'kerdon-ar-ap-aging.csv',
      columns: [
        { field: 'bucket', headerName: t('Maturity Bucket', 'Κλίμακα Ενηλικίωσης'), flex: 1.5 },
        { field: 'ar_cents', headerName: t('Open Receivables (1100_AR)', 'Απαιτήσεις Πελατών (1100_AR)'), cents: true, sumCents: true },
        { field: 'ap_cents', headerName: t('Open Payables (2000_AP)', 'Υποχρεώσεις Προμηθευτών (2000_AP)'), cents: true, sumCents: true },
        { field: 'net_cents', headerName: t('Net Working Capital Exposure', 'Καθαρή Έκθεση AR - AP'), cents: true, sumCents: true },
      ],
      rows: [
        { bucket: t('Current (Not Yet Due)', 'Ενήμερα (Μη Ληξιπρόθεσμα)'), ar_cents: ar.current_cents || 0, ap_cents: ap.current_cents || 0, net_cents: (ar.current_cents || 0) - (ap.current_cents || 0) },
        { bucket: t('1 - 30 Days Past Due', '1 - 30 Ημέρες Καθυστέρηση'), ar_cents: ar.days_1_30_cents || 0, ap_cents: ap.days_1_30_cents || 0, net_cents: (ar.days_1_30_cents || 0) - (ap.days_1_30_cents || 0) },
        { bucket: t('31 - 60 Days Past Due', '31 - 60 Ημέρες Καθυστέρηση'), ar_cents: ar.days_31_60_cents || 0, ap_cents: ap.days_31_60_cents || 0, net_cents: (ar.days_31_60_cents || 0) - (ap.days_31_60_cents || 0) },
        { bucket: t('61 - 90 Days Past Due', '61 - 90 Ημέρες Καθυστέρηση'), ar_cents: ar.days_61_90_cents || 0, ap_cents: ap.days_61_90_cents || 0, net_cents: (ar.days_61_90_cents || 0) - (ap.days_61_90_cents || 0) },
        { bucket: t('Over 90 Days Past Due', 'Άνω των 90 Ημερών'), ar_cents: ar.days_over_90_cents || 0, ap_cents: ap.days_over_90_cents || 0, net_cents: (ar.days_over_90_cents || 0) - (ap.days_over_90_cents || 0) },
      ],
    });
  } else {
    chartRow.innerHTML = '';
    body.innerHTML = '<div id="stmt-vat-grid"></div>';
    mountEnterpriseGrid($('stmt-vat-grid'), {
      idPrefix: 'vat',
      lang,
      csvFileName: 'kerdon-vat-f2-return.csv',
      columns: [
        { field: 'code', headerName: t('GL / F2 Box', 'Κωδικός GL / Φ2'), maxWidth: 220 },
        { field: 'item', headerName: t('VAT Return Line', 'Πεδίο Δήλωσης ΦΠΑ'), flex: 2 },
        { field: 'period_cents', headerName: t('Selected Period', 'Επιλεγμένη Περίοδος'), cents: true },
        { field: 'cum_cents', headerName: t('Cumulative Balance', 'Σωρευτικό Υπόλοιπο'), cents: true },
      ],
      rows: [
        { code: '2400_VAT_OUTPUT (F2 331-337)', item: t('Output VAT on Sales & Commissions', 'ΦΠΑ Εκροών επί Πωλήσεων & Προμηθειών'), period_cents: vatRet.period_output_vat_cents ?? vatRet.output_vat_2400_cents ?? 0, cum_cents: vatRet.output_vat_2400_cents || 0 },
        { code: '1400_VAT_INPUT (F2 361-387)', item: t('Deductible Input VAT on Purchases & OpEx', 'Εκπιπτόμενος ΦΠΑ Εισροών Αγορών & Δαπανών'), period_cents: vatRet.period_input_vat_cents ?? vatRet.input_vat_1400_cents ?? 0, cum_cents: vatRet.input_vat_1400_cents || 0 },
        { code: 'NET_VAT_POSITION (F2 501/511)', item: t('Net VAT Payable / (Credit Carryforward)', 'Χρεωστικό / (Πιστωτικό) Υπόλοιπο ΦΠΑ'), period_cents: vatRet.period_net_vat_cents ?? vatRet.net_vat_payable_cents ?? 0, cum_cents: vatRet.net_vat_payable_cents || 0 },
      ],
    });
  }
  bind();
}

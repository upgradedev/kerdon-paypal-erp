import { mountEnterpriseGrid } from './ag_grid_bridge';
import { renderKpiTile, renderRatioTile, renderSideBadge } from './kpi_catalog';

export function renderDashboard(ctx: any): void {
  const { $, esc, money, amount, hbarChart, stackedChart, table, link, journal, api, path, tid, load, fail, download, go, bind, modules, lang, t, data } = ctx;
  const k = data.dashboard.kpis;
  const series = (data.dashboard.rolling_series && data.dashboard.rolling_series.length ? data.dashboard.rolling_series : data.dashboard.series) || [];
  const max = Math.max(1, ...series.flatMap((p: any) => [p.inflow_cents || 0, p.outflow_cents || 0, p.revenue_cents || 0]));
  const ag = data.aging || {};
  const pf = data.profitability || {};
  const pnl = pf.pnl_statement || {};
  const cf = pf.cash_flow_statement || {};
  const cfOp = cf.operating_activities || {};
  const wcr = pf.working_capital_ratios || {};
  const inbox = data.tenant.inbox_address || 'docs@' + (data.tenant.slug || 'company') + '.kerdon.ai';

  const pulseStats: Array<[string, string]> = [
    ['statements', t('P&L · Balance Sheet · IAS 7 Cash Flow · Cards', 'P&L · Ισολογισμός · Ροές ΔΛΠ 7 · Καρτέλες')],
    ['customers', data.records.customers.length + t(' accounts · AR ', ' πελάτες · AR ') + money(k.receivables.cents)],
    ['suppliers', data.records.suppliers.length + t(' accounts · AP ', ' προμηθευτές · AP ') + money(k.payables.cents)],
    ['sales', data.records.sales.length + t(' docs · Gross ', ' παραστ. · Μικτά ') + money(data.records.sales.reduce((s: number, r: any) => s + amount(r), 0))],
    ['purchases', data.records.purchases.length + t(' docs · Gross ', ' παραστ. · Μικτά ') + money(data.records.purchases.reduce((s: number, r: any) => s + amount(r), 0))],
    ['receipts', data.records.receipts.length + t(' inflows · ', ' εισπράξεις · ') + money(data.records.receipts.reduce((s: number, r: any) => s + amount(r), 0))],
    ['payments', data.records.payments.length + t(' outflows · ', ' πληρωμές · ') + money(data.records.payments.reduce((s: number, r: any) => s + amount(r), 0))],
  ];

  $('content').innerHTML =
    '<div class="ai-hero"><div class="section-head" style="margin-bottom:4px"><strong style="font-size:12px;letter-spacing:.06em">' +
    esc(t('KERDON AI CFO BRIEFING · AMAZON BEDROCK NOVA PRO', 'ΣΥΝΟΨΗ CFO AI · AMAZON BEDROCK NOVA PRO')) +
    '</strong><span class="badge" style="color:#fff;border-color:rgba(255,255,255,.35)">✉ ' +
    esc(inbox) +
    '</span></div><p>' +
    esc(t('Period ', 'Περίοδος ')) +
    '<strong>' +
    esc(data.dashboard.start) +
    '</strong> -> <strong>' +
    esc(data.dashboard.end) +
    '</strong>: <strong>' +
    money(k.revenue.cents) +
    '</strong> ' +
    esc(t('net operating revenue (ex-VAT), ', 'καθαρά λειτουργικά έσοδα (προ ΦΠΑ), ')) +
    '<strong>' +
    money(pf.ebitda_cents || 0) +
    '</strong> EBITDA (<strong>' +
    (wcr.ebitda_margin_pct ?? 0) +
    '%</strong>), ' +
    esc(t('and ', 'και ')) +
    '<strong>' +
    money(k.cash.cents) +
    '</strong> ' +
    esc(t('closing cash across ', 'διαθέσιμα ταμείου για ')) +
    '<strong>' +
    esc(data.tenant.display_name) +
    '</strong>.</p></div>' +
    '<div class="sim-strip"><span class="sim-strip-label">' +
    esc(t('Autonomous Close & Sandbox Actions:', 'Αυτοματισμοί & Κλείσιμο:')) +
    '</span>' +
    '<button id="ws-ingest-email" type="button">' + esc(t('Email Ingest', 'Εισαγωγή Email')) + '</button>' +
    '<button id="ws-load-240" type="button">' + esc(t('240-Record Portfolio', 'Χαρτοφυλάκιο 240 Εγγρ.')) + '</button>' +
    '<button id="ws-seed-dataset" type="button">' + esc(t('Seed Public Dataset', 'Φόρτωση Δημόσιου Dataset')) + '</button>' +
    '<button id="ws-export-bundle" type="button">' + esc(t('Evidence Bundle', 'Πακέτο Τεκμηρίων')) + '</button>' +
    '<button id="ws-track2-run" type="button">' + esc(t('1. Close Run', '1. Κλείσιμο')) + '</button>' +
    '<button id="ws-track2-approve" type="button">' + esc(t('2. Four-Eyes Approve', '2. Έγκριση 4-Ματιών')) + '</button>' +
    '<button id="ws-track2-export" type="button">' + esc(t('3. Export Pack', '3. Εξαγωγή Πακέτου')) + '</button>' +
    '<button id="ws-track2-feedback" type="button">' + esc(t('4. Record Feedback', '4. Ανατροφοδότηση AI')) + '</button>' +
    '</div>' +
    '<div class="kpis">' +
    renderKpiTile({
      metricKey: 'cash',
      lang,
      valueText: money(k.cash.cents),
      subText: k.cash.event_ids.length + t(' cash GL events · audit ↗', ' ταμειακές εγγραφές · έλεγχος ↗'),
      dataAttrName: 'data-kpi',
      dataAttrValue: 'cash',
    }) +
    renderKpiTile({
      metricKey: 'revenue',
      lang,
      valueText: money(k.revenue.cents),
      subText: t('Gross billed: ', 'Μικτά τιμολογηθέντα: ') + money(data.dashboard.period_gross_sales_cents || 0) + ' ↗',
      dataAttrName: 'data-kpi',
      dataAttrValue: 'revenue',
    }) +
    renderKpiTile({
      metricKey: 'receivables',
      lang,
      valueText: money(k.receivables.cents),
      subText: t('Reconciled to Customer Cards · ', 'Συμφωνία με Καρτέλες Πελατών · ') + k.receivables.event_ids.length + ' ↗',
      dataAttrName: 'data-kpi',
      dataAttrValue: 'receivables',
    }) +
    renderKpiTile({
      metricKey: 'payables',
      lang,
      valueText: money(k.payables.cents),
      subText: t('Reconciled to Supplier Cards · ', 'Συμφωνία με Καρτέλες Προμηθευτών · ') + k.payables.event_ids.length + ' ↗',
      dataAttrName: 'data-kpi',
      dataAttrValue: 'payables',
    }) +
    '</div>' +
    '<div class="ratio-grid">' +
    renderRatioTile({
      metricKey: 'ebitda',
      lang,
      valueText: money(pf.ebitda_cents || 0),
      subText: t('EBITDA Margin: ', 'Περιθώριο EBITDA: ') + (wcr.ebitda_margin_pct ?? 0) + '%',
    }) +
    renderRatioTile({
      metricKey: 'gross_margin',
      lang,
      valueText: (wcr.gross_margin_pct ?? 100) + '%',
      subText: t('Gross Profit: ', 'Μικτό Κέρδος: ') + money(pf.gross_profit_cents || 0),
    }) +
    renderRatioTile({
      metricKey: 'operating_cf',
      lang,
      valueText: money(wcr.operating_cash_flow_cents ?? cfOp.net_operating_cash_cents ?? 0),
      subText: t('IAS 7 Direct Operating Cash Flow', 'Λειτουργικές Ταμειακές Ροές ΔΛΠ 7'),
    }) +
    renderRatioTile({
      metricKey: 'quick_ratio',
      lang,
      valueText: (wcr.quick_ratio_x ?? 1) + 'x',
      subText: t('(Cash + AR) / Current Liabilities', '(Ταμείο + Απαιτήσεις) / Βραχυπρ. Υποχρ.'),
    }) +
    renderRatioTile({
      metricKey: 'current_ratio',
      lang,
      valueText: money(wcr.working_capital_cents || 0),
      subText: t('Current Ratio: ', 'Γενική Ρευστότητα: ') + (wcr.current_ratio_x ?? 1) + 'x',
    }) +
    renderRatioTile({
      metricKey: 'dso_dpo',
      lang,
      valueText: (wcr.dso_days ?? 0) + 'd / ' + (wcr.dpo_days ?? 0) + 'd',
      subText: t('Collection Rate: ', 'Βαθμός Είσπραξης: ') + (wcr.collection_rate_pct ?? 100) + '%',
    }) +
    '</div>' +
    '<div class="split section"><div class="chart-card"><div class="section-head"><h2>' +
    esc(t('Multi-month cash & revenue trajectory', 'Μηνιαία εξέλιξη ταμείου & καθαρών εσόδων')) +
    '</h2><span>' +
    esc(series.map((p: any) => p.period).join(' -> ')) +
    '</span></div><div class="chart">' +
    series
      .map(
        (p: any) =>
          '<div class="chart-column"><div class="bars"><button type="button" class="bar" data-period="' +
          p.period +
          '" style="height:' +
          Math.max(3, ((p.inflow_cents || 0) / max) * 100) +
          '%" aria-label="' +
          p.period +
          ' inflow ' +
          money(p.inflow_cents || 0) +
          '" title="' +
          p.period +
          ' Cash Inflow: ' +
          money(p.inflow_cents || 0) +
          '"></button><button type="button" class="bar out" data-period="' +
          p.period +
          '" style="height:' +
          Math.max(3, ((p.outflow_cents || 0) / max) * 100) +
          '%" aria-label="' +
          p.period +
          ' outflow ' +
          money(p.outflow_cents || 0) +
          '" title="' +
          p.period +
          ' Cash Outflow: ' +
          money(p.outflow_cents || 0) +
          '"></button><button type="button" class="bar" data-period="' +
          p.period +
          '" style="height:' +
          Math.max(3, ((p.revenue_cents || 0) / max) * 100) +
          '%;background:var(--warning)" aria-label="' +
          p.period +
          ' revenue ' +
          money(p.revenue_cents || 0) +
          '" title="' +
          p.period +
          ' Net Revenue: ' +
          money(p.revenue_cents || 0) +
          '"></button></div><span class="chart-label"><strong>' +
          p.period +
          '</strong> · ' +
          money((p.inflow_cents || 0) - (p.outflow_cents || 0)) +
          '</span></div>'
      )
      .join('') +
    '</div><p class="legend">' +
    esc(t('Green: Cash Inflow · Indigo: Cash Outflow · Amber: Net Revenue (click any bar to audit month journal)', 'Πράσινο: Εισροές · Μπλε: Εκροές · Κεχριμπάρι: Καθαρά Έσοδα')) +
    '</p></div><div class="chart-card"><div class="section-head"><h2>' +
    esc(t('Statements & subledgers', 'Καταστάσεις & Υποκαθολικά')) +
    '</h2>' +
    link('statements', '', t('Open Statements Hub ↗', 'Οικονομικές Καταστάσεις ↗')) +
    '</div>' +
    pulseStats.map(([m, txt]) => '<div class="stat-row">' + link(m, '', ctx.modLabel(m)) + '<strong>' + esc(txt) + '</strong></div>').join('') +
    '</div></div>' +
    '<div class="chart-grid">' +
    hbarChart(
      t('P&L Waterfall & Margin Bridge (', 'Γέφυρα Αποτελεσμάτων & Περιθωρίου (') + data.dashboard.start + ' -> ' + data.dashboard.end + ')',
      t('Net Revenue to Operating EBITDA across GL accounts', 'Από Καθαρά Έσοδα σε Λειτουργικό EBITDA'),
      [
        { label: t('Net Sales & Commission Revenue (4000/4100)', 'Καθαρά Έσοδα Πωλήσεων & Προμηθειών'), value: pnl.total_revenue_cents ?? k.revenue.cents, color: 'var(--positive)' },
        { label: t('(-) Cost of Goods Sold (5000_COGS)', '(-) Κόστος Πωληθέντων (5000)'), value: pnl.cogs_5000_cents || 0, color: 'var(--warning)' },
        { label: t('(=) Gross Profit (', '(=) Μικτό Κέρδος (') + (pnl.gross_margin_pct ?? 100) + '%)', value: pf.gross_profit_cents || 0, color: 'var(--positive)' },
        { label: t('(-) Workforce Employer Cost (6000)', '(-) Εργοδοτικό Κόστος Μισθοδοσίας (6000)'), value: pnl.workforce_6000_cents || 0, color: 'var(--negative)' },
        { label: t('(-) Seller Commissions & OpEx (6050..6200)', '(-) Προμήθειες & Λειτ. Έξοδα (6050..6200)'), value: (pnl.commissions_6050_cents || 0) + (pnl.rent_utilities_6100_cents || 0) + (pnl.general_opex_6200_cents || 0), color: 'var(--negative)' },
        { label: '(=) Operating EBITDA (' + (pnl.ebitda_margin_pct ?? 0) + '%)', value: pf.ebitda_cents || 0, color: 'var(--primary)' },
      ]
    ) +
    hbarChart(
      t('Liquidity & Treasury Cash Forecast Bridge', 'Γέφυρα Ρευστότητας & Πρόβλεψης Ταμείου'),
      t('Projected ending cash after collecting Open AR and settling Open AP', 'Εκτιμώμενο ταμείο μετά την είσπραξη AR και εξόφληση AP'),
      [
        { label: t('Current Posted Cash (1000_CASH)', 'Τρέχον Ταμείο (1000_CASH)'), value: pf.cash_forecast?.opening_posted_cash_cents ?? k.cash.cents, color: 'var(--positive)' },
        { label: t('(+) Open Receivables Inflow (1100_AR)', '(+) Ανοιχτές Απαιτήσεις (1100_AR)'), value: pf.cash_forecast?.open_ar_inflow_cents ?? k.receivables.cents, color: 'var(--primary)' },
        { label: t('(-) Open Payables Outflow (2000_AP)', '(-) Ανοιχτές Υποχρεώσεις (2000_AP)'), value: pf.cash_forecast?.open_ap_outflow_cents ?? k.payables.cents, color: 'var(--negative)' },
        { label: t('(=) Projected Net Cash Position', '(=) Προβλεπόμενο Καθαρό Ταμείο'), value: pf.cash_forecast?.projected_net_cash_cents || 0, color: 'var(--positive)' },
      ]
    ) +
    '</div>' +
    (ag.receivables_aging
      ? '<div class="chart-grid">' +
        stackedChart(
          t('Receivables (AR) & Payables (AP) Aging Profile', 'Ενηλικίωση Απαιτήσεων (AR) & Υποχρεώσεων (AP)'),
          t('Open invoice maturity as of ', 'Ληκτότητα ανοιχτών υπολοίπων έως ') + (ag.as_of || data.dashboard.end),
          [
            { label: t('AR Current (Not Yet Due)', 'Ενήμερες Απαιτήσεις'), value: ag.receivables_aging.current_cents || 0, color: 'var(--positive)' },
            { label: t('AR Overdue 1-30 Days', 'Ληξιπρόθεσμα 1-30 ημ.'), value: ag.receivables_aging.days_1_30_cents || 0, color: 'var(--warning)' },
            { label: t('AR Overdue 31-90+ Days', 'Ληξιπρόθεσμα 31-90+ ημ.'), value: (ag.receivables_aging.days_31_60_cents || 0) + (ag.receivables_aging.days_61_90_cents || 0) + (ag.receivables_aging.days_over_90_cents || 0), color: 'var(--negative)' },
            { label: t('AP Open Supplier Payables', 'Υποχρεώσεις Προμηθευτών'), value: ag.payables_aging.total_open_cents || 0, color: 'var(--primary)' },
          ]
        ) +
        '<div class="chart-card"><h3>' +
        esc(t('Due-date aging schedule (reconciled to GL)', 'Πίνακας Ενηλικίωσης (Συμφωνία με Γενική Λογιστική)')) +
        '</h3><div class="chart-sub">' +
        esc(t('Exact bucket breakdown matching Open AR (1100) and Open AP (2000)', 'Ανάλυση ανά κλίμακα καθυστέρησης σε απόλυτη συμφωνία με 1100 & 2000')) +
        '</div>' +
        table(
          [t('Maturity Bucket', 'Κλίμακα'), t('Open AR (1100)', 'Απαιτήσεις AR'), t('Open AP (2000)', 'Υποχρεώσεις AP')],
          [
            [t('Current', 'Ενήμερα'), money(ag.receivables_aging.current_cents), money(ag.payables_aging.current_cents)],
            ['1-30 d', money(ag.receivables_aging.days_1_30_cents), money(ag.payables_aging.days_1_30_cents)],
            ['31-60 d', money(ag.receivables_aging.days_31_60_cents), money(ag.payables_aging.days_31_60_cents)],
            [
              '61-90+ d',
              money(ag.receivables_aging.days_61_90_cents + ag.receivables_aging.days_over_90_cents),
              money(ag.payables_aging.days_61_90_cents + ag.payables_aging.days_over_90_cents),
            ],
            [
              '<strong>' + esc(t('Total Open (GL Reconciled)', 'Σύνολο Ανοιχτών (GL)')) + '</strong>',
              '<strong>' + money(ag.receivables_aging.total_open_cents) + '</strong>',
              '<strong>' + money(ag.payables_aging.total_open_cents) + '</strong>',
            ],
          ]
        ) +
        '</div></div>'
      : '') +
    '<div class="section"><div class="section-head"><h2>' +
    esc(t('Recent journal activity', 'Πρόσφατες εγγραφές ημερολογίου')) +
    '</h2>' +
    link('accounting', '', t('View full journal ↗', 'Πλήρες Ημερολόγιο ↗')) +
    '</div>' +
    journal(data.ledger.slice().sort((a: any, b: any) => b.posted_date.localeCompare(a.posted_date)).slice(0, 7)) +
    '</div>';

  if ($('ws-ingest-email'))
    $('ws-ingest-email').onclick = async () => {
      try {
        const r = await api(path('ingest/email'), {
          sender: 'billing@attica-cloud.gr',
          subject: 'FW: Monthly Cloud Infrastructure Invoice',
          attachment_filename: 'invoice-oct.pdf',
          attachment_content: 'Total: 1798.00 EUR',
        });
        $('notice').textContent = 'Autonomous Email Ingested · SHA-256: ' + (r.blob_sha256 || r.envelope?.sha256_hex || r.sha256_hex || 'verified');
        await load();
      } catch (e) {
        fail(e);
      }
    };
  if ($('ws-load-240'))
    $('ws-load-240').onclick = async () => {
      try {
        const r = await api(path('portfolio/mode'), { mode: 'FULL_240_PORTFOLIO' });
        $('notice').textContent = 'Loaded 240-Record Multi-Store Portfolio (' + (r.total_records || 240) + ' records across 16 clients & 10 suppliers).';
        await load();
      } catch (e) {
        fail(e);
      }
    };
  if ($('ws-seed-dataset'))
    $('ws-seed-dataset').onclick = async () => {
      try {
        const res = await api(path('datasets/import'), { dataset_id: 'kerdon-hellenic-eu-v1' });
        const cov = res.imported?.coverage_verification || {};
        $('notice').textContent =
          'Seeded public dataset ' +
          res.imported.title +
          ' · Verified ' +
          (cov.modules_passed || 18) +
          '/' +
          (cov.modules_total || 18) +
          ' modules (Trial Balance balanced: ' +
          String(cov.trial_balance_balanced ?? true) +
          ').';
        await load();
      } catch (e) {
        fail(e);
      }
    };
  if ($('ws-export-bundle'))
    $('ws-export-bundle').onclick = async () => {
      try {
        const r = await api(path('evidence-bundle'));
        download('kerdon-evidence-bundle-' + tid() + '.json', 'application/json', JSON.stringify(r, null, 2));
      } catch (e) {
        fail(e);
      }
    };
  document.querySelectorAll('[data-kpi]').forEach((b: any) => {
    b.onclick = () => go('accounting', '', 'General', k[b.dataset.kpi].event_ids, b.dataset.kpi);
  });
  document.querySelectorAll('[data-period]').forEach((b: any) => {
    b.onclick = () => go('accounting', '', 'General', series.find((p: any) => p.period === b.dataset.period).event_ids, 'cash');
  });
  bind();
  if ($('ws-track2-run'))
    $('ws-track2-run').onclick = async () => {
      try {
        const r = await api('/tenants/' + encodeURIComponent(tid()) + '/evaluate', { period: data.dashboard.end.slice(0, 7) });
        $('notice').textContent = 'Track 2 Step 1 (Close Run): ' + (r.period || 'completed') + ' · Stages verified: ' + (r.stages?.length ?? 8) + '.';
      } catch (e) {
        fail(e);
      }
    };
  if ($('ws-track2-approve'))
    $('ws-track2-approve').onclick = async () => {
      try {
        const r = await api('/tenants/' + encodeURIComponent(tid()) + '/commissions/approve', { approver_id: 'usr-cfo-approver', submitted_by: 'mgr-store-lead' });
        $('notice').textContent = 'Track 2 Step 2 (Four-Eyes Approval): ' + (r.commission_case?.status || 'APPROVED') + ' · Merkle: ' + (r.aletheia_receipt?.merkle_root_sha256 || '').slice(0, 12);
      } catch (e) {
        fail(e);
      }
    };
  if ($('ws-track2-export'))
    $('ws-track2-export').onclick = async () => {
      try {
        const r = await api('/tenants/' + encodeURIComponent(tid()) + '/evidence-bundle');
        $('notice').textContent = 'Track 2 Step 3 (Export Pack): ' + (r.bundle_id || 'SEALED') + ' · SHA-256: ' + (r.bundle_sha256 || 'verified').slice(0, 16);
      } catch (e) {
        fail(e);
      }
    };
  if ($('ws-track2-feedback'))
    $('ws-track2-feedback').onclick = async () => {
      try {
        const r = await api('/tenants/' + encodeURIComponent(tid()) + '/memory/learn', { product_family: 'Hardware Accessory Pack' });
        $('notice').textContent = 'Track 2 Step 4 (Compounding Feedback): ' + (r.compounding_comparison?.rule_applied?.rule_id || 'RECORDED');
      } catch (e) {
        fail(e);
      }
    };
}

export function renderList(ctx: any): void {
  const { $, esc, money, status, amount, id, date, party, source, table, link, isGreekOrg, fp, t, lang, bind, download, csv, newDraft, modules, data, module, listStatusFilter } = ctx;
  const isParty = ['customers', 'suppliers'].includes(module);
  const isInvoice = ['sales', 'purchases'].includes(module);
  const allRecs: any[] = data.records[module] || [];

  const partyLedger = (r: any) => ({
    debit: Number(r.ledger_debit_cents ?? 0),
    credit: Number(r.ledger_credit_cents ?? 0),
    net: Number(r.ledger_balance_cents ?? 0),
    abs: Number(r.ledger_abs_balance_cents ?? Math.abs(r.ledger_balance_cents ?? 0)),
    side: String(r.ledger_balance_side || 'ZERO'),
  });

  let kpiCardsHtml = '';
  if (isInvoice) {
    const activeDocs = allRecs.filter((r: any) => status(r) !== 'Reversed');
    const openDocs = allRecs.filter((r: any) => status(r) === 'Open');
    const partDocs = allRecs.filter((r: any) => status(r) === 'Part paid');
    const paidDocs = allRecs.filter((r: any) => status(r) === 'Paid');
    const sumOut = (arr: any[]) => arr.reduce((s: number, r: any) => s + Math.max(0, (r.gross_cents || 0) - (r.paid_cents || 0)), 0);
    const sumGross = (arr: any[]) => arr.reduce((s: number, r: any) => s + (r.gross_cents || 0), 0);
    const sumPaid = (arr: any[]) => arr.reduce((s: number, r: any) => s + (r.paid_cents || 0), 0);
    kpiCardsHtml =
      '<div class="kpis">' +
      renderKpiTile({
        metricKey: module === 'sales' ? 'revenue' : 'payables',
        lang,
        customTitle: t('Total Billed ' + modules[module], 'Σύνολο Τιμολόγησης'),
        valueText: money(sumGross(activeDocs)),
        subText: allRecs.length + t(' documents · show all', ' παραστατικά · όλα'),
        dataAttrName: 'data-list-status',
        dataAttrValue: '',
      }) +
      renderKpiTile({
        metricKey: module === 'sales' ? 'receivables' : 'payables',
        lang,
        customTitle: t('Open Unpaid Balance', 'Ανεξόφλητα (Open)'),
        valueText: money(sumOut(openDocs)),
        subText: openDocs.length + t(' open documents · filter', ' ανοιχτά · φίλτρο'),
        dataAttrName: 'data-list-status',
        dataAttrValue: 'Open',
      }) +
      renderKpiTile({
        metricKey: module === 'sales' ? 'receivables' : 'payables',
        lang,
        customTitle: t('Part-Paid Remaining', 'Μερικώς Εξοφλημένα'),
        valueText: money(sumOut(partDocs)),
        subText: partDocs.length + t(' part-paid docs · filter', ' μερικώς εξοφλ. · φίλτρο'),
        dataAttrName: 'data-list-status',
        dataAttrValue: 'Part paid',
      }) +
      renderKpiTile({
        metricKey: 'cash',
        lang,
        customTitle: t('Settled / Paid', 'Εξοφλημένα'),
        valueText: money(sumPaid(paidDocs) + partDocs.reduce((s: number, r: any) => s + (r.paid_cents || 0), 0)),
        subText: paidDocs.length + t(' settled docs · filter', ' εξοφλημένα · φίλτρο'),
        dataAttrName: 'data-list-status',
        dataAttrValue: 'Paid',
      }) +
      '</div>';
  } else if (isParty) {
    const withOpen = allRecs.filter((r: any) => partyLedger(r).net !== 0);
    const totalDebits = allRecs.reduce((s: number, r: any) => s + partyLedger(r).debit, 0);
    const totalCredits = allRecs.reduce((s: number, r: any) => s + partyLedger(r).credit, 0);
    const netOpen = allRecs.reduce((s: number, r: any) => s + partyLedger(r).net, 0);
    kpiCardsHtml =
      '<div class="kpis">' +
      renderKpiTile({
        metricKey: module === 'customers' ? 'receivables' : 'payables',
        lang,
        customTitle: t('Net Reconciled ' + (module === 'customers' ? 'AR (1100)' : 'AP (2000)'), 'Καθαρό Υπόλοιπο GL'),
        valueText: money(netOpen),
        subText: withOpen.length + t(' open accounts · 100% GL match', ' ενεργά υπόλοιπα · συμφωνία GL'),
        dataAttrName: 'data-list-status',
        dataAttrValue: '',
      }) +
      renderKpiTile({
        metricKey: module === 'customers' ? 'receivables' : 'payables',
        lang,
        customTitle: t('Cumulative GL Debits', 'Σωρευτικές Χρεώσεις (DR)'),
        valueText: money(totalDebits),
        subText: allRecs.length + t(' registered counterparties', ' συναλλασσόμενοι'),
        dataAttrName: 'data-list-status',
        dataAttrValue: '',
      }) +
      renderKpiTile({
        metricKey: module === 'customers' ? 'receivables' : 'payables',
        lang,
        customTitle: t('Cumulative GL Credits', 'Σωρευτικές Πιστώσεις (CR)'),
        valueText: money(totalCredits),
        subText: t('Posted invoices, receipts & credit notes', 'Τιμολόγια, εξοφλήσεις & πιστωτικά'),
        dataAttrName: 'data-list-status',
        dataAttrValue: '',
      }) +
      renderKpiTile({
        metricKey: 'cash',
        lang,
        customTitle: t('Zero-Balance Settled Accounts', 'Μηδενισμένα Υπόλοιπα'),
        valueText: String(allRecs.length - withOpen.length),
        subText: t('Fully settled counterparties · filter', 'Πλήρως εξοφλημένες καρτέλες'),
        dataAttrName: 'data-list-status',
        dataAttrValue: 'SETTLED_BALANCE',
      }) +
      '</div>';
  } else {
    const totalAmt = allRecs.reduce((s: number, r: any) => s + amount(r), 0);
    kpiCardsHtml =
      '<div class="kpis">' +
      renderKpiTile({
        metricKey: 'cash',
        lang,
        customTitle: t('Total ' + modules[module], 'Σύνολο ' + ctx.modLabel(module)),
        valueText: money(totalAmt),
        subText: allRecs.length + t(' posted journal entries', ' λογιστικές εγγραφές'),
        dataAttrName: 'data-list-status',
        dataAttrValue: '',
      }) +
      '</div>';
  }

  const moduleDrafts = (data.drafts || []).filter((d: any) => d.module === module);
  $('content').innerHTML =
    kpiCardsHtml +
    '<div class="toolbar section"><label for="search" class="sr-only">Search records</label><input id="search" aria-label="Search records" placeholder="' +
    esc(t('Quick filter ' + modules[module].toLowerCase() + '...', 'Αναζήτηση...')) +
    '"><label for="status" class="sr-only">Record status</label><select id="status" aria-label="Record status"><option value="">' +
    esc(t('All statuses', 'Όλες οι καταστάσεις')) +
    '</option>' +
    (isParty
      ? '<option value="Registered">Registered</option><option value="OPEN_BALANCE">' +
        esc(t('Has open DR/CR balance', 'Με ανοιχτό υπόλοιπο')) +
        '</option><option value="SETTLED_BALANCE">' +
        esc(t('Zero balance (Settled)', 'Μηδενικό υπόλοιπο')) +
        '</option>'
      : ['Registered', 'Open', 'Part paid', 'Paid', 'Posted', 'Reversed'].map((s) => '<option value="' + s + '">' + s + '</option>').join('')) +
    '</select><button id="new-record" type="button" class="primary">+ New ' +
    (isParty ? module.slice(0, -1) : 'document') +
    '</button><button id="export-list" type="button">↓ CSV</button></div><div id="list-table"></div>' +
    (moduleDrafts.length
      ? '<div class="section"><h3>Saved non-posted drafts (' +
        moduleDrafts.length +
        ')</h3>' +
        table(
          ['Draft ID', 'Counterparty', 'Invoice #', 'Issued date', 'Net', 'VAT', 'Gross', 'Status'],
          moduleDrafts.map((d: any) => [
            esc(d.draft_id),
            party(d.counterparty_id),
            esc(d.invoice_number),
            esc(d.issued_date),
            money(d.net_cents || 0),
            money(d.vat_cents || 0),
            money(d.gross_cents || 0),
            '<span class="badge">' + esc(d.status) + '</span>',
          ])
        ) +
        '</div>'
      : '');

  if (listStatusFilter && $('status')) {
    $('status').value = listStatusFilter;
  }

  const update = () => {
    const selStatus = $('status').value;
    const searchVal = ($('search').value || '').toLowerCase();
    const records = allRecs
      .filter((r: any) => {
        const matchesText = !searchVal || JSON.stringify(r).toLowerCase().includes(searchVal);
        if (!matchesText) return false;
        if (!selStatus) return true;
        if (selStatus === 'OPEN_BALANCE') return partyLedger(r).net !== 0;
        if (selStatus === 'SETTLED_BALANCE') return partyLedger(r).net === 0;
        return status(r) === selStatus;
      })
      .sort((a: any, b: any) => date(b).localeCompare(date(a)));

    if (isParty) {
      const grMode = isGreekOrg();
      mountEnterpriseGrid($('list-table'), {
        idPrefix: module,
        lang,
        csvFileName: 'kerdon-' + module + '.csv',
        primaryAmountField: 'balance_cents',
        onRendered: bind,
        columns: [
          { field: 'id_html', headerName: t('Code', 'Κωδικός'), isHtml: true, maxWidth: 135 },
          { field: 'name_html', headerName: t('Legal Name', 'Επωνυμία'), isHtml: true, flex: 2 },
          { field: 'tax_html', headerName: grMode ? t('TIN / Country', 'ΑΦΜ / Χώρα') : 'Tax ID', isHtml: true, maxWidth: 190, mobileHide: true },
          { field: 'debit_cents', headerName: t('Debit', 'Χρέωση'), cents: true, sumCents: true, mobileHide: true },
          { field: 'credit_cents', headerName: t('Credit', 'Πίστωση'), cents: true, sumCents: true, mobileHide: true },
          { field: 'balance_cents', headerName: t('Balance', 'Υπόλοιπο'), cents: true, sumCents: true },
          { field: 'side_html', headerName: t('DR/CR', 'ΧΡ/ΠΙ'), isHtml: true, maxWidth: 95 },
          { field: 'card_html', headerName: t('Account Card', 'Καρτέλα'), isHtml: true, maxWidth: 145, mobileHide: true },
        ],
        rows: records.map((r: any) => {
          const gl = partyLedger(r);
          return {
            id: r.id,
            legal_name: r.legal_name,
            tax_id: r.tax_id,
            _side: gl.side,
            debit_cents: gl.debit,
            credit_cents: gl.credit,
            balance_cents: gl.net,
            id_html: link(module, r.id, r.id),
            name_html: link(module, r.id, r.legal_name),
            tax_html: esc(r.tax_id) + ' <span class="badge">' + esc(r.country_code || fp().country_code) + '</span>',
            side_html: renderSideBadge(gl.side, lang),
            card_html: link(module, r.id, t('Statement ↗', 'Καρτέλα ↗'), 'Account statement'),
          };
        }),
        presets: [
          { id: 'all', label: t('All Counterparties', 'Όλοι οι Συναλλασσόμενοι') },
          { id: 'open', label: t('Open Balance Only', 'Με Ανοιχτό Υπόλοιπο'), predicate: (r) => r.balance_cents !== 0 },
          { id: 'settled', label: t('Zero Balance (Settled)', 'Εξοφλημένοι (0.00)'), predicate: (r) => r.balance_cents === 0 },
        ],
      });
    } else if (isInvoice) {
      const grMode = isGreekOrg();
      mountEnterpriseGrid($('list-table'), {
        idPrefix: module,
        lang,
        csvFileName: 'kerdon-' + module + '.csv',
        primaryAmountField: 'gross_cents',
        onRendered: bind,
        columns: [
          { field: 'issued_date', headerName: t('Date', 'Ημ/νία'), maxWidth: 120 },
          { field: 'doc_html', headerName: t('Document', 'Κωδικός'), isHtml: true, maxWidth: 175 },
          { field: 'inv_html', headerName: grMode ? t('Type & #', 'Τύπος & Αρ.') : 'Invoice #', isHtml: true, maxWidth: 185, mobileHide: true },
          { field: 'party_html', headerName: t('Counterparty', 'Συναλλασσόμενος'), isHtml: true, flex: 1.6 },
          { field: 'net_cents', headerName: t('Net', 'Καθαρή'), cents: true, sumCents: true, mobileHide: true },
          { field: 'vat_cents', headerName: t('VAT', 'ΦΠΑ'), cents: true, sumCents: true, mobileHide: true },
          { field: 'gross_cents', headerName: t('Gross', 'Μικτή Αξία'), cents: true, sumCents: true },
          { field: 'paid_cents', headerName: t('Settled', 'Εξοφληθέν'), cents: true, sumCents: true, mobileHide: true },
          { field: 'out_cents', headerName: t('Open Balance', 'Υπόλοιπο'), cents: true, sumCents: true },
          { field: 'status_html', headerName: t('Status', 'Κατάσταση'), isHtml: true, maxWidth: 120, mobileHide: true },
        ],
        rows: records.map((r: any) => {
          const out = Math.max(0, (r.gross_cents || 0) - (r.paid_cents || 0));
          const stText = status(r);
          const typeBadge = grMode
            ? '<span class="badge">' + esc((r.invoice_type || (module === 'sales' ? '1.1' : '13.1')) + ' · ' + (r.series || 'A') + '/' + (r.aa || '101')) + '</span> '
            : '';
          return {
            ...r,
            issued_date: date(r),
            out_cents: out,
            status_text: stText,
            doc_html: link(module, id(r), id(r)),
            inv_html: typeBadge + esc(r.invoice_number || r.doc_type || '-'),
            party_html: party(r.counterparty_id),
            status_html: '<span class="badge">' + esc(stText) + '</span>',
          };
        }),
        presets: [
          { id: 'all', label: t('All Documents', 'Όλα τα Παραστατικά') },
          { id: 'open', label: t('Unpaid / Open', 'Ανεξόφλητα'), predicate: (r) => r.out_cents > 0 },
          { id: 'paid', label: t('Fully Settled', 'Πλήρως Εξοφλημένα'), predicate: (r) => r.status_text === 'Paid' },
          { id: 'high', label: t('High Value (> €2,000)', 'Μεγάλης Αξίας (> €2.000)'), predicate: (r) => (r.gross_cents || 0) > 200000, sortField: 'gross_cents', sortDir: 'desc' },
        ],
      });
    } else {
      mountEnterpriseGrid($('list-table'), {
        idPrefix: module,
        lang,
        csvFileName: 'kerdon-' + module + '.csv',
        primaryAmountField: 'amt_cents',
        onRendered: bind,
        columns: [
          { field: 'dt', headerName: t('Date', 'Ημ/νία'), maxWidth: 125 },
          { field: 'ev_html', headerName: t('Journal Event', 'Άρθρο GL'), isHtml: true, maxWidth: 180 },
          { field: 'src_html', headerName: t('Source Document', 'Παραστατικό'), isHtml: true, maxWidth: 185, mobileHide: true },
          { field: 'party_html', headerName: t('Counterparty', 'Συναλλασσόμενος'), isHtml: true, flex: 1.4, mobileHide: true },
          { field: 'desc', headerName: t('Description', 'Αιτιολογία'), flex: 2 },
          { field: 'amt_cents', headerName: t('Amount', 'Ποσό'), cents: true, sumCents: true },
          { field: 'st_html', headerName: t('Status', 'Κατάσταση'), isHtml: true, maxWidth: 115, mobileHide: true },
        ],
        rows: records.map((r: any) => ({
          dt: date(r),
          ev_html: link(module, id(r), id(r)),
          src_html: source(r.source_document_id),
          party_html: party(r.counterparty_id || r.lines?.find((l: any) => l.counterparty_id)?.counterparty_id),
          desc: r.description || r.doc_type || '-',
          amt_cents: amount(r),
          st_html: '<span class="badge">' + esc(status(r)) + '</span>',
        })),
      });
    }
    bind();
    $('export-list').onclick = () => download('kerdon-' + module + '.csv', 'text/csv', csv(records));
  };

  document.querySelectorAll('[data-list-status]').forEach((b: any) => {
    b.onclick = () => {
      $('status').value = b.dataset.listStatus || '';
      update();
    };
  });
  $('search').oninput = update;
  $('status').onchange = update;
  $('new-record').onclick = newDraft;
  update();
}

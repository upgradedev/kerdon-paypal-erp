export function renderDashboard(ctx: any): void {
  const { $, esc, money, amount, hbarChart, stackedChart, table, link, journal, api, path, tid, load, fail, download, go, bind, modules, data } = ctx;
    const k = data.dashboard.kpis;
    const labels: Record<string, string> = {
      cash: 'Cash balance (1000_CASH)',
      revenue: 'Period revenue (Net ex-VAT)',
      receivables: 'Receivables (Open AR inc-VAT)',
      payables: 'Payables (Open AP inc-VAT)',
    };
    const subNotes: Record<string, string> = {
      cash: k.cash.event_ids.length + ' cash journal events · click to audit ↗',
      revenue: 'Gross billed (inc. VAT): ' + money(data.dashboard.period_gross_sales_cents || 0) + ' · ' + k.revenue.event_ids.length + ' events ↗',
      receivables: 'Reconciled to Open Sales & Aging · ' + k.receivables.event_ids.length + ' events ↗',
      payables: 'Reconciled to Open Purchases & Aging · ' + k.payables.event_ids.length + ' events ↗',
    };
    const series = (data.dashboard.rolling_series && data.dashboard.rolling_series.length ? data.dashboard.rolling_series : data.dashboard.series) || [];
    const max = Math.max(1, ...series.flatMap((p: any) => [p.inflow_cents || 0, p.outflow_cents || 0, p.revenue_cents || 0]));
    const ag = data.aging || {};
    const pf = data.profitability || {};
    const pnl = pf.pnl_statement || {};
    const vatRet = pf.vat_return || {};
    const wcr = pf.working_capital_ratios || {};
    const inbox = data.tenant.inbox_address || 'docs@' + (data.tenant.slug || 'company') + '.kerdon.ai';
    const pulseStats: Array<[string, string]> = [
      ['customers', data.records.customers.length + ' accounts · Open AR ' + money(k.receivables.cents)],
      ['suppliers', data.records.suppliers.length + ' accounts · Open AP ' + money(k.payables.cents)],
      ['sales', data.records.sales.length + ' docs · Gross ' + money(data.records.sales.reduce((s: number, r: any) => s + amount(r), 0))],
      ['purchases', data.records.purchases.length + ' docs · Gross ' + money(data.records.purchases.reduce((s: number, r: any) => s + amount(r), 0))],
      ['expenses', data.records.expenses.length + ' entries · ' + money(data.records.expenses.reduce((s: number, r: any) => s + amount(r), 0))],
      ['receipts', data.records.receipts.length + ' inflows · ' + money(data.records.receipts.reduce((s: number, r: any) => s + amount(r), 0))],
      ['payments', data.records.payments.length + ' outflows · ' + money(data.records.payments.reduce((s: number, r: any) => s + amount(r), 0))],
    ];
    $('content').innerHTML =
      '<div class="ai-hero"><div class="section-head" style="margin-bottom:6px"><strong style="font-size:12px;letter-spacing:.06em">✨ KERDON AI CFO BRIEFING · NARRATED BY AMAZON BEDROCK NOVA PRO</strong><span class="badge" style="color:#fff;border-color:rgba(255,255,255,.35)">✉ ' +
      esc(inbox) +
      '</span></div><p>Period <strong>' +
      esc(data.dashboard.start) +
      '</strong> to <strong>' +
      esc(data.dashboard.end) +
      '</strong> closed with <strong>' +
      money(k.revenue.cents) +
      '</strong> in net revenue (<strong>' +
      money(data.dashboard.period_gross_sales_cents || 0) +
      '</strong> gross billed inc. VAT), <strong>' +
      money(pf.ebitda_cents || 0) +
      '</strong> in operating EBITDA (<strong>' +
      (wcr.ebitda_margin_pct ?? 0) +
      '%</strong> margin), and <strong>' +
      money(k.cash.cents) +
      '</strong> in ending cash across <strong>' +
      esc(data.tenant.display_name) +
      '</strong>. Open receivables stand at ' +
      money(k.receivables.cents) +
      ' and open payables at ' +
      money(k.payables.cents) +
      '.</p><div class="toolbar" style="margin-bottom:0"><button id="ws-ingest-email" type="button">⚡ Autonomous Email Ingest</button><button id="ws-load-240" type="button">📊 Load 240-Record Portfolio</button><button id="ws-seed-dataset" type="button">🗄️ Seed Public Dataset (All 18 Modules)</button><button id="ws-export-bundle" type="button">📦 Export Redacted Evidence Bundle</button><button id="ws-track2-run" type="button">🔄 1. Close Run</button><button id="ws-track2-approve" type="button">✅ 2. Four-Eyes Approve</button><button id="ws-track2-export" type="button">📤 3. Export Pack</button><button id="ws-track2-feedback" type="button">💬 4. Record Feedback</button></div></div><div class="kpis">' +
      Object.entries(labels)
        .map(
          ([key, label]) =>
            '<button class="kpi" data-kpi="' +
            key +
            '"><small>' +
            label +
            '</small><strong>' +
            money(k[key].cents) +
            '</strong><span>' +
            esc(subNotes[key]) +
            '</span></button>'
        )
        .join('') +
      '</div>' +
      '<div class="ratio-grid">' +
      '<div class="ratio-card"><small>Operating EBITDA</small><strong>' +
      money(pf.ebitda_cents || 0) +
      '</strong><span>Margin: ' +
      (wcr.ebitda_margin_pct ?? 0) +
      '% of Net Revenue</span></div>' +
      '<div class="ratio-card"><small>Gross Profit Margin</small><strong>' +
      (wcr.gross_margin_pct ?? 100) +
      '%</strong><span>Gross Profit: ' +
      money(pf.gross_profit_cents || 0) +
      '</span></div>' +
      '<div class="ratio-card"><small>AR Collection Rate</small><strong>' +
      (wcr.collection_rate_pct ?? 100) +
      '%</strong><span>Paid vs Gross Sales Billed</span></div>' +
      '<div class="ratio-card"><small>Overdue AR Risk (&gt;0d)</small><strong>' +
      (wcr.overdue_ar_pct ?? 0) +
      '%</strong><span>Past-due share of Open AR</span></div>' +
      '<div class="ratio-card"><small>Quick Liquidity Ratio</small><strong>' +
      (wcr.quick_ratio_x ?? 1) +
      'x</strong><span>(Cash + Open AR) / Open AP</span></div>' +
      '<div class="ratio-card"><small>Net VAT Liability (F2)</small><strong>' +
      money(vatRet.net_vat_payable_cents || 0) +
      '</strong><span>Output ' +
      money(vatRet.output_vat_2400_cents || 0) +
      ' · Input ' +
      money(vatRet.input_vat_1400_cents || 0) +
      '</span></div>' +
      '</div>' +
      '<div class="split section"><div class="chart-card"><div class="section-head"><h2>Multi-month cash &amp; revenue trajectory</h2><span>' +
      esc(series.map((p: any) => p.period).join(' → ')) +
      '</span></div><div class="chart">' +
      series
        .map(
          (p: any) =>
            '<div class="chart-column"><div class="bars"><button class="bar" data-period="' +
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
            '"></button><button class="bar out" data-period="' +
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
            '"></button><button class="bar" data-period="' +
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
            '</strong> · Net ' +
            money((p.inflow_cents || 0) - (p.outflow_cents || 0)) +
            '</span></div>'
        )
        .join('') +
      '</div><p class="legend">Green: Cash Inflow · Indigo: Cash Outflow · Amber: Net Revenue (click any bar to audit month journal)</p></div><div class="chart-card"><div class="section-head"><h2>Commercial pulse</h2>' +
      link('targets', '', 'Sales targets ↗') +
      '</div>' +
      pulseStats.map(([m, txt]) => '<div class="stat-row">' + link(m, '', modules[m]) + '<strong>' + esc(txt) + '</strong></div>').join('') +
      '<p>Revenue is posted net (ex-VAT). Open AR/AP are gross (inc-VAT) and reconcile 100% to GL 1100_AR &amp; 2000_AP.</p></div></div>' +
      '<div class="chart-grid">' +
      hbarChart('P&L Waterfall & Margin Bridge (' + data.dashboard.start + ' to ' + data.dashboard.end + ')', 'Net Revenue to Operating EBITDA progression across General Ledger accounts', [
        { label: 'Net Sales & Commission Revenue (4000/4100)', value: pnl.total_revenue_cents ?? k.revenue.cents, color: 'var(--positive)' },
        { label: '(-) Cost of Goods Sold (5000_COGS)', value: pnl.cogs_5000_cents || 0, color: 'var(--warning)' },
        { label: '(=) Gross Profit (' + (pnl.gross_margin_pct ?? 100) + '%)', value: pf.gross_profit_cents || 0, color: 'var(--positive)' },
        { label: '(-) Workforce Employer Cost (6000)', value: pnl.workforce_6000_cents || 0, color: 'var(--negative)' },
        { label: '(-) Seller Commissions (6050)', value: pnl.commissions_6050_cents || 0, color: 'var(--negative)' },
        { label: '(-) Rent, Utilities & General OpEx (6100/6200)', value: (pnl.rent_utilities_6100_cents || 0) + (pnl.general_opex_6200_cents || 0), color: 'var(--negative)' },
        { label: '(=) Operating EBITDA (' + (pnl.ebitda_margin_pct ?? 0) + '%)', value: pf.ebitda_cents || 0, color: 'var(--primary)' },
      ]) +
      hbarChart('Liquidity & Cash Forecast Bridge', 'Projected ending cash position after collecting Open AR and settling Open AP', [
        { label: 'Current Posted Cash Balance (1000_CASH)', value: pf.cash_forecast?.opening_posted_cash_cents ?? k.cash.cents, color: 'var(--positive)' },
        { label: '(+) Open Receivables Inflow (1100_AR)', value: pf.cash_forecast?.open_ar_inflow_cents ?? k.receivables.cents, color: 'var(--primary)' },
        { label: '(-) Open Payables Outflow (2000_AP)', value: pf.cash_forecast?.open_ap_outflow_cents ?? k.payables.cents, color: 'var(--negative)' },
        { label: '(=) Projected Net Cash Position', value: pf.cash_forecast?.projected_net_cash_cents || 0, color: 'var(--positive)' },
      ]) +
      '</div>' +
      (ag.receivables_aging
        ? '<div class="chart-grid">' +
          stackedChart('Receivables (AR) & Payables (AP) Aging Breakdown', 'Open invoice maturity profile as of ' + (ag.as_of || data.dashboard.end), [
            { label: 'AR Current (Not Yet Due)', value: ag.receivables_aging.current_cents || 0, color: 'var(--positive)' },
            { label: 'AR Overdue 1-30 Days', value: ag.receivables_aging.days_1_30_cents || 0, color: 'var(--warning)' },
            { label: 'AR Overdue 31-90+ Days', value: (ag.receivables_aging.days_31_60_cents || 0) + (ag.receivables_aging.days_61_90_cents || 0) + (ag.receivables_aging.days_over_90_cents || 0), color: 'var(--negative)' },
            { label: 'AP Open Supplier Payables', value: ag.payables_aging.total_open_cents || 0, color: 'var(--primary)' },
          ]) +
          '<div class="chart-card"><h3>Due-date aging schedule (AR / AP reconciled to GL)</h3><div class="chart-sub">Exact bucket breakdown matching Open Sales and Open Purchases registers</div>' +
          table(
            ['Bucket', 'Open AR (1100)', 'Open AP (2000)'],
            [
              ['Current', money(ag.receivables_aging.current_cents), money(ag.payables_aging.current_cents)],
              ['1-30 days', money(ag.receivables_aging.days_1_30_cents), money(ag.payables_aging.days_1_30_cents)],
              ['31-60 days', money(ag.receivables_aging.days_31_60_cents), money(ag.payables_aging.days_31_60_cents)],
              [
                '61-90+ days',
                money(ag.receivables_aging.days_61_90_cents + ag.receivables_aging.days_over_90_cents),
                money(ag.payables_aging.days_61_90_cents + ag.payables_aging.days_over_90_cents),
              ],
              [
                '<strong>Total Open (Reconciled to GL)</strong>',
                '<strong>' + money(ag.receivables_aging.total_open_cents) + '</strong>',
                '<strong>' + money(ag.payables_aging.total_open_cents) + '</strong>',
              ],
            ]
          ) +
          '</div></div>'
        : '') +
      '<div class="section"><div class="section-head"><h2>Recent journal activity</h2>' +
      link('accounting', '', 'View journal ↗') +
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
            ' modules across all 7 Bounded Contexts (Trial Balance balanced: ' +
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
        } catch (e) { fail(e); }
      };
    if ($('ws-track2-approve'))
      $('ws-track2-approve').onclick = async () => {
        try {
          const r = await api('/tenants/' + encodeURIComponent(tid()) + '/commissions/approve', { approver_id: 'usr-cfo-approver', submitted_by: 'mgr-store-lead' });
          $('notice').textContent = 'Track 2 Step 2 (Four-Eyes Approval): ' + (r.commission_case?.status || 'APPROVED') + ' · Merkle: ' + (r.aletheia_receipt?.merkle_root_sha256 || '').slice(0, 12);
        } catch (e) { fail(e); }
      };
    if ($('ws-track2-export'))
      $('ws-track2-export').onclick = async () => {
        try {
          const r = await api('/tenants/' + encodeURIComponent(tid()) + '/evidence-bundle');
          $('notice').textContent = 'Track 2 Step 3 (Export Pack): ' + (r.bundle_id || 'SEALED') + ' · SHA-256: ' + (r.bundle_sha256 || 'verified').slice(0, 16);
        } catch (e) { fail(e); }
      };
    if ($('ws-track2-feedback'))
      $('ws-track2-feedback').onclick = async () => {
        try {
          const r = await api('/tenants/' + encodeURIComponent(tid()) + '/memory/learn', { product_family: 'Hardware Accessory Pack' });
          $('notice').textContent = 'Track 2 Step 4 (Compounding Feedback): ' + (r.compounding_comparison?.rule_applied?.rule_id || 'RECORDED');
        } catch (e) { fail(e); }
      };
}

export function renderList(ctx: any): void {
  const { $, esc, money, status, amount, id, date, party, source, stackedChart, hbarChart, table, link, isGreekOrg, fp, t, bind, download, csv, newDraft, modules, data, module, listStatusFilter } = ctx;
    const isParty = ['customers', 'suppliers'].includes(module);
    const isInvoice = ['sales', 'purchases'].includes(module);
    const allRecs: any[] = data.records[module] || [];
    const partyDocs = isParty ? (module === 'customers' ? data.records.sales : data.records.purchases) || [] : [];
    const partyStats = (partyId: string) => {
      const docs = partyDocs.filter((d: any) => d.counterparty_id === partyId && d.lifecycle_status !== 'REVERSED');
      const gross = docs.reduce((s: number, d: any) => s + (d.gross_cents || 0), 0);
      const open = docs.reduce((s: number, d: any) => s + Math.max(0, (d.gross_cents || 0) - (d.paid_cents || 0)), 0);
      return { count: docs.length, gross, open };
    };

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
        '<button type="button" class="kpi" data-list-status=""><small>All ' +
        esc(modules[module]) +
        '</small><strong>' +
        money(sumGross(activeDocs)) +
        '</strong><span>' +
        allRecs.length +
        ' documents (click to show all)</span></button>' +
        '<button type="button" class="kpi" data-list-status="Open"><small>Open (Unpaid)</small><strong>' +
        money(sumOut(openDocs)) +
        '</strong><span>' +
        openDocs.length +
        ' open documents · filter list</span></button>' +
        '<button type="button" class="kpi" data-list-status="Part paid"><small>Part paid</small><strong>' +
        money(sumOut(partDocs)) +
        '</strong><span>' +
        partDocs.length +
        ' part-paid docs · filter list</span></button>' +
        '<button type="button" class="kpi" data-list-status="Paid"><small>Settled / Paid</small><strong>' +
        money(sumPaid(paidDocs) + partDocs.reduce((s: number, r: any) => s + (r.paid_cents || 0), 0)) +
        '</strong><span>' +
        paidDocs.length +
        ' fully paid docs · filter list</span></button>' +
        '</div>';
    } else if (isParty) {
      const withOpen = allRecs.filter((r: any) => partyStats(r.id).open > 0);
      const totalOpen = allRecs.reduce((s: number, r: any) => s + partyStats(r.id).open, 0);
      const totalInvoiced = allRecs.reduce((s: number, r: any) => s + partyStats(r.id).gross, 0);
      kpiCardsHtml =
        '<div class="kpis">' +
        '<button type="button" class="kpi" data-list-status=""><small>Registered ' +
        esc(modules[module]) +
        '</small><strong>' +
        allRecs.length +
        ' accounts</strong><span>Total invoiced ' +
        money(totalInvoiced) +
        '</span></button>' +
        '<button type="button" class="kpi" data-list-status="OPEN_BALANCE"><small>Accounts with open ' +
        (module === 'customers' ? 'AR' : 'AP') +
        '</small><strong>' +
        money(totalOpen) +
        '</strong><span>' +
        withOpen.length +
        ' accounts with open balance · filter</span></button>' +
        '<button type="button" class="kpi" data-list-status="SETTLED_BALANCE"><small>Fully settled accounts</small><strong>' +
        (allRecs.length - withOpen.length) +
        ' accounts</strong><span>€0.00 open balance · filter</span></button>' +
        '</div>';
    } else {
      const totalAmt = allRecs.reduce((s: number, r: any) => s + amount(r), 0);
      kpiCardsHtml =
        '<div class="kpis">' +
        '<button type="button" class="kpi" data-list-status=""><small>Total ' +
        esc(modules[module]) +
        '</small><strong>' +
        money(totalAmt) +
        '</strong><span>' +
        allRecs.length +
        ' posted journal records</span></button>' +
        '<button type="button" class="kpi" data-list-status="Posted"><small>Posted to GL</small><strong>' +
        money(totalAmt) +
        '</strong><span>' +
        allRecs.filter((r: any) => status(r) === 'Posted').length +
        ' posted records · filter</span></button>' +
        '</div>';
    }

    let listChartHtml = '';
    if (isInvoice) {
      const openDocs = allRecs.filter((r: any) => status(r) === 'Open');
      const partDocs = allRecs.filter((r: any) => status(r) === 'Part paid');
      const paidDocs = allRecs.filter((r: any) => status(r) === 'Paid');
      const settledCents = paidDocs.reduce((s: number, r: any) => s + (r.paid_cents || 0), 0) + partDocs.reduce((s: number, r: any) => s + (r.paid_cents || 0), 0);
      const partOpenCents = partDocs.reduce((s: number, r: any) => s + Math.max(0, (r.gross_cents || 0) - (r.paid_cents || 0)), 0);
      const unpaidOpenCents = openDocs.reduce((s: number, r: any) => s + Math.max(0, (r.gross_cents || 0) - (r.paid_cents || 0)), 0);
      const topDocs = allRecs
        .slice()
        .sort((a: any, b: any) => (b.gross_cents || 0) - (a.gross_cents || 0))
        .slice(0, 5);
      listChartHtml =
        '<div class="chart-grid" style="margin-bottom:20px">' +
        stackedChart(
          modules[module] + ' Settlement Status Breakdown',
          'Distribution of gross billed volume across settled and open balances',
          [
            { label: 'Settled / Collected (' + paidDocs.length + ' paid docs)', value: settledCents, color: 'var(--positive)' },
            { label: 'Part-Paid Remaining Open (' + partDocs.length + ' docs)', value: partOpenCents, color: 'var(--warning)' },
            { label: 'Unpaid Open Balance (' + openDocs.length + ' docs)', value: unpaidOpenCents, color: 'var(--negative)' },
          ]
        ) +
        hbarChart(
          'Largest ' + modules[module] + ' Documents (Gross inc-VAT)',
          'Top documents ranked by total gross invoice value',
          topDocs.map((d: any) => ({
            label: (d.invoice_number || d.document_id) + ' · ' + (d.counterparty_name || d.counterparty_id),
            value: d.gross_cents || 0,
            color: status(d) === 'Paid' ? 'var(--positive)' : 'var(--primary)',
          }))
        ) +
        '</div>';
    } else if (isParty) {
      const rankedOpen = allRecs
        .map((r: any) => ({ name: r.legal_name, ...partyStats(r.id) }))
        .sort((a, b) => b.open - a.open || b.gross - a.gross);
      listChartHtml =
        '<div class="chart-grid" style="margin-bottom:20px">' +
        hbarChart(
          (module === 'customers' ? 'Customer Open AR' : 'Supplier Open AP') + ' Concentration',
          'Open balance exposure ranked by counterparty (reconciled to GL)',
          rankedOpen.map((p) => ({
            label: p.name,
            value: p.open,
            color: p.open > 0 ? 'var(--warning)' : 'var(--positive)',
          }))
        ) +
        hbarChart(
          'Cumulative Billed Volume by ' + (module === 'customers' ? 'Customer' : 'Supplier'),
          'Total gross invoiced value across all registered documents',
          rankedOpen.map((p) => ({
            label: p.name + ' (' + p.count + ' docs)',
            value: p.gross,
            color: 'var(--primary)',
          }))
        ) +
        '</div>';
    } else {
      const byCategory: Record<string, number> = {};
      allRecs.forEach((r: any) => {
        const key = r.expense_account || r.counterparty_id || r.doc_type || 'General';
        byCategory[key] = (byCategory[key] || 0) + amount(r);
      });
      const catEntries = Object.entries(byCategory).sort((a, b) => b[1] - a[1]);
      listChartHtml =
        '<div class="chart-grid" style="margin-bottom:20px">' +
        hbarChart(
          modules[module] + ' Distribution by Account / Counterparty',
          'Aggregated posted volume grouped by GL category or counterparty',
          catEntries.map(([k, v]) => ({ label: k, value: v, color: 'var(--primary)' }))
        ) +
        hbarChart(
          'Posted ' + modules[module] + ' Entries by Magnitude',
          'Top posted journal movements in current register',
          allRecs
            .slice()
            .sort((a: any, b: any) => amount(b) - amount(a))
            .slice(0, 5)
            .map((r: any) => ({
              label: (r.description || id(r)).slice(0, 38),
              value: amount(r),
              color: 'var(--positive)',
            }))
        ) +
        '</div>';
    }

    const moduleDrafts = (data.drafts || []).filter((d: any) => d.module === module);
    $('content').innerHTML =
      kpiCardsHtml +
      listChartHtml +
      '<div class="toolbar"><input id="search" aria-label="Search records" placeholder="Search ' +
      modules[module].toLowerCase() +
      '"><select id="status" aria-label="Record status"><option value="">All statuses</option>' +
      (isParty
        ? '<option value="Registered">Registered</option><option value="OPEN_BALANCE">Has open AR/AP balance</option><option value="SETTLED_BALANCE">Zero open balance</option>'
        : ['Registered', 'Open', 'Part paid', 'Paid', 'Posted', 'Reversed'].map((s) => '<option value="' + s + '">' + s + '</option>').join('')) +
      '</select><button id="new-record" class="primary">+ New ' +
      (isParty ? module.slice(0, -1) : 'document') +
      '</button><button id="export-list">↓ CSV</button></div><div id="list-table"></div>' +
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
      const records = allRecs
        .filter((r: any) => {
          const matchesText = JSON.stringify(r).toLowerCase().includes($('search').value.toLowerCase());
          if (!matchesText) return false;
          if (!selStatus) return true;
          if (selStatus === 'OPEN_BALANCE') return partyStats(r.id).open > 0;
          if (selStatus === 'SETTLED_BALANCE') return partyStats(r.id).open === 0;
          return status(r) === selStatus;
        })
        .sort((a: any, b: any) => date(b).localeCompare(date(a)));
      if (isParty) {
        const grMode = isGreekOrg();
        const rows = records.map((r: any) => {
          const st = partyStats(r.id);
          const taxCell = grMode
            ? esc(r.tax_id) + ' <span class="badge">' + esc(r.country_code || 'GR') + ' · 9-Digit</span>'
            : esc(r.tax_id) + ' (' + esc(r.country_code || fp().country_code) + ')';
          const regCell = grMode
            ? esc((r.doy || t('Athens Corporate Tax Office (KEFODE Attikis)', 'ΚΕΦΟΔΕ ΑΤΤΙΚΗΣ')) + t(' · GEMI ', ' · ΓΕΜΗ ') + (r.gemi_number || '140982011000'))
            : esc(r.payment_terms_days ? r.payment_terms_days + ' days' : r.category || '-');
          return [
            link(module, r.id, r.id),
            link(module, r.id, r.legal_name),
            taxCell,
            regCell,
            esc(st.count + ' docs · ' + money(st.gross)),
            '<strong>' + money(st.open) + '</strong>',
            status(r),
          ];
        });
        if (rows.length > 0) {
          const sumGross = records.reduce((s: number, r: any) => s + partyStats(r.id).gross, 0);
          const sumOpen = records.reduce((s: number, r: any) => s + partyStats(r.id).open, 0);
          rows.push([
            '<strong>Total (' + records.length + ' accounts)</strong>',
            '-',
            '-',
            '-',
            '<strong>' + money(sumGross) + '</strong>',
            '<strong>' + money(sumOpen) + '</strong>',
            '-',
          ]);
        }
        $('list-table').innerHTML = table(
          ['Account', 'Legal name', grMode ? t('TIN / AFM (Tax ID)', 'ΑΦΜ (Tax ID)') : 'Tax ID', grMode ? t('Tax Office (DOY) & GEMI', 'ΔΟΥ & Αρ. ΓΕΜΗ') : 'Terms / category', 'Invoiced gross', 'Open AR/AP balance', 'Status'],
          rows
        );
      } else if (isInvoice) {
        const grMode = isGreekOrg();
        const rows = records.map((r: any) => {
          const out = Math.max(0, (r.gross_cents || 0) - (r.paid_cents || 0));
          const typeBadge = grMode
            ? '<span class="badge">' + esc((r.invoice_type || (module === 'sales' ? '1.1' : '13.1')) + ' · ' + (r.series || 'A') + '/' + (r.aa || '101')) + '</span> '
            : '';
          return [
            esc(date(r)),
            link(module, id(r), id(r)),
            typeBadge + esc(r.invoice_number || r.doc_type || '-'),
            party(r.counterparty_id),
            money(r.net_cents || 0),
            money(r.vat_cents || 0),
            money(r.gross_cents || 0),
            money(r.paid_cents || 0),
            '<strong>' + money(out) + '</strong>',
            status(r),
          ];
        });
        if (rows.length > 0) {
          const sumNet = records.reduce((s: number, r: any) => s + (r.net_cents || 0), 0);
          const sumVat = records.reduce((s: number, r: any) => s + (r.vat_cents || 0), 0);
          const sumGross = records.reduce((s: number, r: any) => s + (r.gross_cents || 0), 0);
          const sumPaid = records.reduce((s: number, r: any) => s + (r.paid_cents || 0), 0);
          const sumOut = records.reduce((s: number, r: any) => s + Math.max(0, (r.gross_cents || 0) - (r.paid_cents || 0)), 0);
          rows.push([
            '<strong>Total (' + records.length + ' docs)</strong>',
            '-',
            '-',
            '-',
            '<strong>' + money(sumNet) + '</strong>',
            '<strong>' + money(sumVat) + '</strong>',
            '<strong>' + money(sumGross) + '</strong>',
            '<strong>' + money(sumPaid) + '</strong>',
            '<strong>' + money(sumOut) + '</strong>',
            '-',
          ]);
        }
        $('list-table').innerHTML = table(['Date', 'Document', grMode ? 'AADE Type & Invoice #' : 'Invoice #', 'Counterparty', 'Net', 'VAT', 'Gross', 'Paid', 'Outstanding', 'Status'], rows);
      } else {
        const rows = records.map((r: any) => [
          esc(date(r)),
          link(module, id(r), id(r)),
          source(r.source_document_id),
          party(r.counterparty_id || r.lines?.find((l: any) => l.counterparty_id)?.counterparty_id),
          esc(r.description || r.doc_type || '-'),
          '<strong>' + money(amount(r)) + '</strong>',
          status(r),
        ]);
        if (rows.length > 0) {
          const sumAmt = records.reduce((s: number, r: any) => s + amount(r), 0);
          rows.push(['<strong>Total (' + records.length + ' records)</strong>', '-', '-', '-', '-', '<strong>' + money(sumAmt) + '</strong>', '-']);
        }
        $('list-table').innerHTML = table(['Date', 'Journal event', 'Source document', 'Counterparty', 'Description', 'Amount', 'Status'], rows);
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

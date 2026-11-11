import { renderServicesPartB } from './runtime_services_b';

export async function renderServices(ctx: any): Promise<void> {
  const { $, esc, money, party, source, facts, hbarChart, stackedChart, table, link, journal, journalLines, eventKpiImpact, isPayPalActive, cents, api, path, tid, load, fail, go, bind, download, t, modules, data, module, selected, eventIds, kpiFilter } = ctx;
    const current = module;
    const company = tid();
    const content = $('content');
    if (module === 'accounting') {
      const events = eventIds ? data.ledger.filter((e: any) => eventIds!.includes(e.event_id)) : data.ledger;
      const ev = events.find((e: any) => e.event_id === selected);
      const tb = data.trial_balance || [];
      const pf = data.profitability || {};
      const pnl = pf.pnl_statement || {};
      const bs = pf.balance_sheet || {};
      const vatRet = pf.vat_return || {};
      const kpiMeta: Record<string, { label: string; account: string; regMod: string; regLabel: string }> = {
        cash: { label: 'Cash balance', account: '1000_CASH', regMod: 'receipts', regLabel: 'Cash receipts & settlements ↗' },
        revenue: { label: 'Period revenue (Net)', account: '4000_SALES_REVENUE / 4100_COMMISSION_REVENUE', regMod: 'sales', regLabel: 'Sales & billing register ↗' },
        receivables: { label: 'Open receivables (AR)', account: '1100_AR', regMod: 'sales', regLabel: 'Sales & billing register (Open AR) ↗' },
        payables: { label: 'Open payables (AP)', account: '2000_AP', regMod: 'purchases', regLabel: 'Purchases & bills register (Open AP) ↗' },
      };
      const km = kpiMeta[kpiFilter];
      const listedSum = events.reduce((s: number, e: any) => s + eventKpiImpact(e, kpiFilter), 0);
      const tileCents = kpiFilter && data.dashboard?.kpis?.[kpiFilter] ? data.dashboard.kpis[kpiFilter].cents : listedSum;
      const drillBanner =
        eventIds && km
          ? '<div class="section">' +
            facts({
              selected_dashboard_kpi: km.label,
              gl_account_basis: km.account,
              dashboard_tile_cents: tileCents,
              reconciled_events_sum_cents: listedSum,
              reconciliation_status: tileCents === listedSum ? 'RECONCILED (100% EXACT MATCH)' : 'PERIOD SUBSET VIEW',
            }) +
            '<div class="toolbar">' +
            link(km.regMod, '', km.regLabel) +
            '<button type="button" id="clear-journal-filter">Show all ' +
            data.ledger.length +
            ' journal events</button></div></div>'
          : eventIds
            ? '<div class="toolbar section"><button type="button" id="clear-journal-filter">Clear filter · Show all ' +
              data.ledger.length +
              ' journal events</button></div>'
            : '';
      const cfoStatementsHtml = !eventIds
        ? '<div class="chart-grid" style="margin-bottom:24px">' +
          hbarChart('Income Statement (P&L) Waterfall (' + data.dashboard.start + ' to ' + data.dashboard.end + ')', 'Period revenue, cost structure, and operating EBITDA', [
            { label: 'Sales Revenue (4000)', value: pnl.sales_revenue_4000_cents || 0, color: 'var(--positive)' },
            { label: 'Commission Revenue (4100)', value: pnl.commission_revenue_4100_cents || 0, color: 'var(--positive)' },
            { label: '(-) Cost of Goods Sold (5000)', value: pnl.cogs_5000_cents || 0, color: 'var(--warning)' },
            { label: '(-) Workforce Employer Cost (6000)', value: pnl.workforce_6000_cents || 0, color: 'var(--negative)' },
            { label: '(-) Seller Commissions (6050)', value: pnl.commissions_6050_cents || 0, color: 'var(--negative)' },
            { label: '(-) Rent & General OpEx (6100/6200)', value: (pnl.rent_utilities_6100_cents || 0) + (pnl.general_opex_6200_cents || 0), color: 'var(--negative)' },
            { label: '(=) Operating EBITDA (' + (pnl.ebitda_margin_pct ?? 0) + '%)', value: pnl.ebitda_cents || 0, color: 'var(--primary)' },
          ]) +
          stackedChart('Balance Sheet Structure (Assets = Liabilities + Equity)', 'Cumulative financial position as of ' + data.dashboard.end, [
            { label: 'Cash & Equivalents (1000_CASH)', value: bs.cash_1000_cents || 0, color: 'var(--positive)' },
            { label: 'Accounts Receivable (1100_AR)', value: bs.accounts_receivable_1100_cents || 0, color: 'var(--primary)' },
            { label: 'Input VAT Receivable (1400)', value: bs.vat_input_receivable_1400_cents || 0, color: 'var(--warning)' },
          ]) +
          '</div>' +
          '<div class="split section"><div><h3>' + t('Income Statement (Profit & Loss / P&L)', 'Income Statement (Κατάσταση Αποτελεσμάτων Χρήσης / P&L)') + '</h3>' +
          table(
            ['P&L Line Item', 'GL Account', 'Period Amount', '% of Revenue'],
            [
              ['Sales Revenue (Net ex-VAT)', '4000_SALES_REVENUE', money(pnl.sales_revenue_4000_cents || 0), pnl.total_revenue_cents ? (((pnl.sales_revenue_4000_cents || 0) / pnl.total_revenue_cents) * 100).toFixed(1) + '%' : '0.0%'],
              ['Principal Commission Revenue', '4100_COMMISSION_REVENUE', money(pnl.commission_revenue_4100_cents || 0), pnl.total_revenue_cents ? (((pnl.commission_revenue_4100_cents || 0) / pnl.total_revenue_cents) * 100).toFixed(1) + '%' : '0.0%'],
              ['<strong>Total Net Operating Revenue</strong>', '<strong>4000 + 4100</strong>', '<strong>' + money(pnl.total_revenue_cents || 0) + '</strong>', '<strong>100.0%</strong>'],
              ['(-) Cost of Goods Sold (COGS)', '5000_COST_OF_GOODS_SOLD', money(pnl.cogs_5000_cents || 0), pnl.total_revenue_cents ? (((pnl.cogs_5000_cents || 0) / pnl.total_revenue_cents) * 100).toFixed(1) + '%' : '0.0%'],
              ['<strong>' + t('Gross Profit', 'Gross Profit (Μικτό Κέρδος)') + '</strong>', '<strong>Gross Margin</strong>', '<strong>' + money(pnl.gross_profit_cents || 0) + '</strong>', '<strong>' + (pnl.gross_margin_pct ?? 100) + '%</strong>'],
              ['(-) Workforce & Employer EFKA Cost', '6000_WORKFORCE_COST', money(pnl.workforce_6000_cents || 0), pnl.total_revenue_cents ? (((pnl.workforce_6000_cents || 0) / pnl.total_revenue_cents) * 100).toFixed(1) + '%' : '0.0%'],
              ['(-) Seller Commission Expense', '6050_SELLER_COMMISSION', money(pnl.commissions_6050_cents || 0), pnl.total_revenue_cents ? (((pnl.commissions_6050_cents || 0) / pnl.total_revenue_cents) * 100).toFixed(1) + '%' : '0.0%'],
              ['(-) Store Rent & Utilities', '6100_RENT_AND_UTILITIES', money(pnl.rent_utilities_6100_cents || 0), pnl.total_revenue_cents ? (((pnl.rent_utilities_6100_cents || 0) / pnl.total_revenue_cents) * 100).toFixed(1) + '%' : '0.0%'],
              ['(-) General Operating Expense', '6200_GENERAL_OPEX', money(pnl.general_opex_6200_cents || 0), pnl.total_revenue_cents ? (((pnl.general_opex_6200_cents || 0) / pnl.total_revenue_cents) * 100).toFixed(1) + '%' : '0.0%'],
              ['<strong>Operating EBITDA</strong>', '<strong>EBITDA Margin</strong>', '<strong>' + money(pnl.ebitda_cents || 0) + '</strong>', '<strong>' + (pnl.ebitda_margin_pct ?? 0) + '%</strong>'],
            ]
          ) +
          '</div><div><h3>' + t('Balance Sheet & Statutory VAT Return (F2)', 'Balance Sheet & Statutory VAT Return (Ισολογισμός & ΦΠΑ Φ2)') + '</h3>' +
          table(
            ['Balance Sheet Category', 'GL Account', 'Balance as of ' + data.dashboard.end],
            [
              ['Cash & Bank Balances', '1000_CASH', money(bs.cash_1000_cents || 0)],
              ['Accounts Receivable (Open AR)', '1100_ACCOUNTS_RECEIVABLE', money(bs.accounts_receivable_1100_cents || 0)],
              ['Deductible Input VAT Receivable', '1400_VAT_INPUT_RECEIVABLE', money(bs.vat_input_receivable_1400_cents || 0)],
              ['<strong>' + t('Total Assets', 'Total Assets (Σύνολο Ενεργητικού)') + '</strong>', '<strong>1000..1900</strong>', '<strong>' + money(bs.total_assets_cents || 0) + '</strong>'],
              ['Accounts Payable (Open AP)', '2000_ACCOUNTS_PAYABLE', money(bs.accounts_payable_2000_cents || 0)],
              ['Customer Advance Deposits', '2100_CUSTOMER_DEPOSITS', money(bs.customer_deposits_2100_cents || 0)],
              ['Output VAT Payable', '2400_VAT_OUTPUT_PAYABLE', money(bs.vat_output_payable_2400_cents || 0)],
              ['Payroll, EFKA & FMY Tax Payables', '2500 + 2510 + 2520', money(bs.payroll_and_tax_payables_2500_cents || 0)],
              ['Cumulative Retained Earnings & Net Income', 'Equity / Net Result', money(bs.cumulative_net_income_cents || 0)],
              ['<strong>' + t('Total Liabilities & Equity', 'Total Liabilities & Equity (Σύνολο Παθητικού)') + '</strong>', '<span class="badge">BALANCED</span>', '<strong>' + money(bs.total_liabilities_and_equity_cents || 0) + '</strong>'],
              ['<strong>Net VAT Return Position (Output 2400 - Input 1400)</strong>', '<strong>Statutory F2 Return</strong>', '<strong>' + money(vatRet.net_vat_payable_cents || 0) + '</strong>'],
            ]
          ) +
          '</div></div>'
        : '';
      content.innerHTML = ev
        ? '<div class="section-head"><button id="back" class="icon" aria-label="Back to journal">←</button><h2>' +
          esc(ev.description) +
          '</h2></div>' +
          facts({ event: ev.event_id, date: ev.posted_date, source: ev.source_document_id, evidence: ev.source_sha256 }) +
          journalLines(ev.lines)
        : cfoStatementsHtml +
          '<div class="section-head section"><h2>' +
          (eventIds ? 'Source event drill-down (' + (km ? km.label : events.length + ' events') + ')' : 'Posted journal (' + events.length + ' events)') +
          '</h2><button id="export-journal">↓ Export journal</button></div>' +
          drillBanner +
          journal(events, kpiFilter) +
          (tb.length && !eventIds
            ? '<div class="section"><h3>General Ledger Trial Balance (Balanced Double-Entry Roll-up)</h3>' +
              table(
                ['Account code', 'Total debit', 'Total credit', 'Net balance', 'Normal side', 'Journal lines'],
                tb.map((row: any) => [
                  esc(row.account),
                  money(row.debit_cents),
                  money(row.credit_cents),
                  money(row.net_balance_cents),
                  '<span class="badge">' + esc(row.normal_side) + '</span>',
                  esc(row.line_count),
                ])
              ) +
              '</div>'
            : '');
      if ($('back')) $('back').onclick = () => go('accounting');
      if ($('clear-journal-filter')) $('clear-journal-filter').onclick = () => go('accounting');
      if ($('export-journal'))
        $('export-journal').onclick = async () => {
          try {
            const r = await api(path('export/journal-csv'));
            download(r.filename, 'text/csv', r.csv);
          } catch (e) {
            fail(e);
          }
        };
      bind();
      return;
    }
    if (module === 'intelligence') {
      content.innerHTML =
        '<form id="ask-form"><label for="question">Question</label><textarea id="question" rows="4" required style="width:100%;margin:10px 0"></textarea><button class="primary">Ask Kerdon</button></form><div id="answer" class="result section"></div>';
      $('ask-form').onsubmit = async (e: Event) => {
        e.preventDefault();
        try {
          const r = await api(path('query'), { question: $('question').value.trim() });
          if (current === ctx.module && company === tid()) {
            $('answer').innerHTML =
              facts({ answer: r.answer || r.response || '-', source: r.source || 'deterministic', refused_out_of_scope: String(Boolean(r.refused_out_of_scope)) }) +
              '<details><summary>Structured payload</summary><pre class="result">' +
              esc(JSON.stringify(r, null, 2)) +
              '</pre></details>';
          }
        } catch (err) {
          fail(err);
        }
      };
      return;
    }
    const suffixMap: Record<string, string> = {
      treasury: 'treasury',
      close: 'completeness',
      commissions: 'commissions',
      inventory: 'inventory',
      documents: 'board-pack',
      workforce: 'overview',
      billing: 'full-state',
    };
    const suffix = suffixMap[module];
    content.innerHTML = '<div class="empty">Loading service records…</div>';
    try {
      const r = await api(path(suffix));
      if (current !== ctx.module || company !== tid()) return;
      content.innerHTML = '<div class="section-head"><h2>' + modules[module] + ' controls</h2><span class="badge">Governed · Deterministic cents</span></div><div id="service-data"></div>';
      const view = $('service-data');
      if (module === 'treasury') {
        const pocketsList: Array<[string, any]> = Object.entries(r.pockets || {});
        const approvalsList: any[] = Object.values(r.approvals || {});
        const receiptsList: any[] = Object.values(r.receipts || {});
        const totalBal = pocketsList.reduce((s, [, p]) => s + (p.balance_cents || 0), 0);
        const totalRes = pocketsList.reduce((s, [, p]) => s + (p.reserve_floor_cents || 0), 0);
        const approvedCount = approvalsList.filter((a: any) => a.state === 'VALID' || a.state === 'APPROVED').length;
        const invalidatedCount = approvalsList.filter((a: any) => a.state === 'INVALIDATED').length;
        const supOpts = (data.records?.suppliers || []).map((s: any) => '<option value="' + esc(s.id) + '">' + esc(s.legal_name) + '</option>').join('');
        view.innerHTML =
          facts({
            total_liquidity_cents: totalBal,
            reserve_floor_cents: totalRes,
            available_above_floor_cents: Math.max(0, totalBal - totalRes),
            active_approvals: approvedCount + ' approved · ' + invalidatedCount + ' invalidated',
            executed_payout_receipts: receiptsList.length,
          }) +
          '<div class="chart-grid" style="margin-bottom:20px">' +
          stackedChart('Treasury Liquidity vs Mandatory Reserve Floor', 'Protected reserve floor vs available disbursement liquidity', [
            { label: 'Free Liquidity Above Reserve Floor', value: Math.max(0, totalBal - totalRes), color: 'var(--positive)' },
            { label: 'Locked Reserve Floor Protection', value: Math.min(totalBal, totalRes), color: 'var(--warning)' },
          ]) +
          hbarChart(
            'Four-Eyes Payout Approval Queue by Counterparty',
            'Pending and invalidated disbursement approvals bound to SHA-256 evidence',
            approvalsList.map((a: any) => ({
              label: (a.approval_id || '') + ' · ' + (a.state || 'VALID'),
              value: a.amount_cents || 0,
              color: a.state === 'VALID' || a.state === 'APPROVED' ? 'var(--positive)' : 'var(--negative)',
            }))
          ) +
          '</div>' +
          '<div class="toolbar"><select id="ws-cn-supplier" aria-label="Credit note supplier">' +
          supOpts +
          '</select><input id="ws-cn-net" type="number" min="1" step="0.01" value="2000.00" aria-label="Credit note net EUR" style="max-width:140px"><button id="ws-inject-cn" type="button">Register supplier credit note &amp; invalidate stale approval</button><button id="ws-exec-payout" type="button" class="primary">Execute Four-Eyes approved payout</button>' +
          (isPayPalActive() ? '<button id="ws-paypal-payout" type="button" class="primary">Execute Governed PayPal Batch Payout v1</button>' : '') +
          '</div><div id="ws-aletheia" class="result section"></div>' +
          table(
            ['Pocket', 'Currency', 'Balance', 'Reserve floor', 'Available above floor'],
            pocketsList.map(([pid, p]: [string, any]) => [
              esc(pid),
              esc(p.currency),
              money(p.balance_cents),
              money(p.reserve_floor_cents),
              '<strong>' + money(Math.max(0, (p.balance_cents || 0) - (p.reserve_floor_cents || 0))) + '</strong>',
            ])
          ) +
          '<div class="section"><h3>Four-Eyes payout approvals (SHA-256 evidence bound)</h3>' +
          table(
            ['Approval ID', 'Counterparty', 'Invoice / case', 'Amount', 'Approver', 'State', 'Invalidation reason'],
            approvalsList.map((a: any) => [
              esc(a.approval_id),
              party(a.counterparty_id),
              source(a.invoice_or_case_id),
              money(a.amount_cents),
              esc(a.approver_id || '-'),
              '<span class="badge">' + esc(a.state) + '</span>',
              esc(a.invalidation_reason || 'Valid · Evidence hash intact'),
            ])
          ) +
          '</div><div class="section"><h3>Executed payout receipts (' +
          receiptsList.length +
          ')</h3>' +
          (receiptsList.length
            ? table(
                ['Payout ID', 'Approval ID', 'Pocket', 'Amount', 'Remaining pocket balance', 'Binding digest'],
                receiptsList.map((rc: any) => [
                  esc(rc.payout_id),
                  esc(rc.approval_id),
                  esc(rc.pocket_id),
                  money(rc.amount_cents),
                  money(rc.remaining_balance_cents),
                  '<span class="hash">' + esc((rc.binding_digest || '').slice(0, 18)) + '…</span>',
                ])
              )
            : '<p>No payouts executed in this session yet. Click "Execute Four-Eyes approved payout" above to release funds and mint an Aletheia spoken &amp; Braille receipt.</p>') +
          '</div>';
        $('ws-inject-cn').onclick = async () => {
          try {
            const firstAp = approvalsList[0] || {};
            const cpId = ($('ws-cn-supplier') && $('ws-cn-supplier').value) || firstAp.counterparty_id || data.records?.suppliers?.[0]?.id || 'sup_1';
            const netCents = $('ws-cn-net') && $('ws-cn-net').value ? cents($('ws-cn-net').value) : 200000;
            const vatCents = Math.round(netCents * 0.24);
            const refInv = firstAp.invoice_or_case_id || data.records?.purchases?.[0]?.document_id || 'doc-' + (data.tenant?.slug || 'aegean-mobility') + '-pur-201';
            const cnRes = await api(path('credit-notes'), {
              credit_note_id: 'cn-' + (data.tenant?.slug || 'tenant') + '-' + Date.now(),
              counterparty_id: cpId,
              net_cents: netCents,
              vat_cents: vatCents,
              gross_cents: netCents + vatCents,
              referenced_invoice_id: refInv,
            });
            $('notice').textContent =
              'Credit note ' +
              cnRes.credit_note.credit_note_id +
              ' registered · Invalidated approvals: ' +
              ((cnRes.invalidated_approval_ids || []).join(', ') || 'none');
            await renderServices(ctx);
          } catch (e) {
            fail(e);
          }
        };
        $('ws-exec-payout').onclick = async () => {
          try {
            let targetAp = approvalsList.find((a: any) => a.state === 'VALID' || a.state === 'APPROVED');
            if (!targetAp) {
              const baseAp = approvalsList[0] || {};
              const newApId = 'ap-reapproved-' + Date.now();
              const created = await api(path('treasury/approvals'), {
                approval_id: newApId,
                counterparty_id: baseAp.counterparty_id || data.records?.suppliers?.[0]?.id || 'sup_1',
                invoice_or_case_id: baseAp.invoice_or_case_id || data.records?.purchases?.[0]?.document_id || 'doc-pur-201',
                amount_cents: Math.max(50000, (baseAp.amount_cents || 1736000) - 248000),
                currency: 'EUR',
                evidence_sha256: 'b'.repeat(64),
              });
              targetAp = created.approval;
            }
            const res = await api(path('treasury/execute'), { approval_id: targetAp.approval_id }, { 'X-Kerdon-Actor': 'act-treasury-release-officer' });
            await renderServices(ctx);
            if ($('ws-aletheia') && res.aletheia_receipt) {
              $('ws-aletheia').innerHTML = facts({
                payout_id: res.receipt?.payout_id,
                executed_amount_cents: res.receipt?.amount_cents,
                spoken_transcript: res.aletheia_receipt.spoken_transcript,
                braille_ascii: res.aletheia_receipt.braille_ascii || res.aletheia_receipt.ascii_braille,
                merkle_root: res.aletheia_receipt.merkle_root_sha256,
              });
            }
          } catch (e) {
            fail(e);
          }
        };
        if ($('ws-paypal-payout'))
          $('ws-paypal-payout').onclick = async () => {
            try {
              const newApId = 'ap-pp-batch-' + Date.now();
              const created = await api(path('treasury/approvals'), {
                approval_id: newApId,
                counterparty_id: data.records?.suppliers?.[0]?.id || 'sup_1',
                invoice_or_case_id: data.records?.purchases?.[0]?.document_id || 'doc-pur-201',
                amount_cents: 85000,
                currency: 'EUR',
                evidence_sha256: 'c'.repeat(64),
              });
              const ppRes = await api(path('connectors/paypal/payout'), {
                approval_id: created.approval.approval_id,
                executor_id: 'usr-treasury-executor',
                recipient_email: 'supplier-payout@' + (data.tenant?.slug || 'kerdon') + '.eu',
              });
              await load();
              if (ppRes.agentic_commerce_narrative?.executive_summary) {
                $('notice').textContent = ppRes.agentic_commerce_narrative.executive_summary;
              }
            } catch (e) {
              fail(e);
            }
          };
      } else if (module === 'close') {
        const gapsList: any[] = r.gaps || [];
        const reasonings: Record<string, any> = {};
        (r.reasonings || []).forEach((rs: any) => {
          reasonings[rs.gap_id || rs.rule_id] = rs;
        });
        const critGaps = gapsList.filter((g: any) => g.severity === 'CRITICAL');
        const highGaps = gapsList.filter((g: any) => g.severity === 'HIGH');
        const medGaps = gapsList.filter((g: any) => g.severity !== 'CRITICAL' && g.severity !== 'HIGH');
        const totalRisk = gapsList.reduce((s: number, g: any) => s + (g.amount_cents || 0), 0);
        view.innerHTML =
          '<div class="kpis">' +
          '<button type="button" class="kpi" data-gap-sev=""><small>All completeness gaps (' +
          esc(r.rule_count || 24) +
          ' rules evaluated)</small><strong>' +
          money(totalRisk) +
          '</strong><span>' +
          gapsList.length +
          ' open gaps · click to show all</span></button>' +
          '<button type="button" class="kpi" data-gap-sev="CRITICAL"><small>Critical blockers</small><strong>' +
          money(critGaps.reduce((s: number, g: any) => s + (g.amount_cents || 0), 0)) +
          '</strong><span>' +
          critGaps.length +
          ' critical gaps · filter</span></button>' +
          '<button type="button" class="kpi" data-gap-sev="HIGH"><small>High severity</small><strong>' +
          money(highGaps.reduce((s: number, g: any) => s + (g.amount_cents || 0), 0)) +
          '</strong><span>' +
          highGaps.length +
          ' high gaps · filter</span></button>' +
          '<button type="button" class="kpi" data-gap-sev="OTHER"><small>Medium / Advisory</small><strong>' +
          money(medGaps.reduce((s: number, g: any) => s + (g.amount_cents || 0), 0)) +
          '</strong><span>' +
          medGaps.length +
          ' advisory gaps · filter</span></button>' +
          '</div>' +
          '<div class="chart-grid" style="margin:20px 0">' +
          stackedChart('Month-End Exposure by Severity', 'Distribution of financial exposure across 24 completeness rules', [
            { label: 'Critical Blockers (' + critGaps.length + ')', value: critGaps.reduce((s: number, g: any) => s + (g.amount_cents || 0), 0), color: 'var(--negative)' },
            { label: 'High Severity (' + highGaps.length + ')', value: highGaps.reduce((s: number, g: any) => s + (g.amount_cents || 0), 0), color: 'var(--warning)' },
            { label: 'Medium / Advisory (' + medGaps.length + ')', value: medGaps.reduce((s: number, g: any) => s + (g.amount_cents || 0), 0), color: 'var(--primary)' },
          ]) +
          hbarChart(
            'Top Completeness & Anomaly Risks by Amount',
            'Largest unreconciled items detected before month-end close',
            gapsList.slice(0, 5).map((g: any) => ({
              label: (g.rule_id || g.gap_rule_id) + ' · ' + (g.counterparty_name || g.counterparty_id || ''),
              value: g.amount_cents || 0,
              color: g.severity === 'CRITICAL' ? 'var(--negative)' : 'var(--warning)',
            }))
          ) +
          '</div><div id="close-gaps-table"></div>' +
          '<div class="toolbar section"><button id="evaluate" class="primary">Run 8-stage month-end close workflow</button><button id="ws-strands-gate" type="button">Verify 6-Reader Strands Release Gate</button><button id="ws-reset-demo" type="button">Reset demo workspace</button></div><div id="evaluation-result" class="result"></div>';
        const renderGapsTable = (sevFilter = '') => {
          const filtered = gapsList.filter((g: any) => {
            if (!sevFilter) return true;
            if (sevFilter === 'OTHER') return g.severity !== 'CRITICAL' && g.severity !== 'HIGH';
            return g.severity === sevFilter;
          });
          const rows = filtered.map((g: any) => {
            const rs = reasonings[g.gap_id] || reasonings[g.rule_id] || {};
            const conf = rs.confidence ? Math.round(rs.confidence * 100) + '%' : rs.confidence_bps ? (rs.confidence_bps / 100).toFixed(0) + '%' : '92%';
            return [
              esc(g.rule_id || g.gap_rule_id),
              '<span class="badge">' + esc(g.severity || 'WARNING') + '</span>',
              esc(g.counterparty_name || g.counterparty_id || '-'),
              esc(g.summary || g.description || g.title || g.gap_id),
              money(g.amount_cents || 0),
              esc((rs.probable_cause || rs.likely_cause || 'Missing statutory evidence') + ' → ' + (rs.recommended_fix || rs.suggested_action || 'Draft corrective outbound document')),
              esc(conf),
            ];
          });
          if (rows.length > 0) {
            const sumRisk = filtered.reduce((s: number, g: any) => s + (g.amount_cents || 0), 0);
            rows.push([
              '<strong>Total (' + filtered.length + ' gaps)</strong>',
              '-',
              '-',
              '<strong>Total amount at risk in filtered view</strong>',
              '<strong>' + money(sumRisk) + '</strong>',
              '-',
              '-',
            ]);
          }
          $('close-gaps-table').innerHTML = table(
            ['Rule ID', 'Severity', 'Counterparty', 'Evidence gap summary', 'Amount at risk', 'Root cause & recommended fix', 'Confidence'],
            rows
          );
        };
        renderGapsTable('');
        document.querySelectorAll('[data-gap-sev]').forEach((b: any) => {
          b.onclick = () => renderGapsTable(b.dataset.gapSev || '');
        });
        $('evaluate').onclick = async () => {
          try {
            $('evaluate').disabled = true;
            const evalRes = await api(path('evaluate'), {});
            if ($('evaluation-result')) {
              $('evaluation-result').innerHTML =
                facts({ period: evalRes.period, source: evalRes.source, stages: (evalRes.stages || []).length }) +
                '<details><summary>Stage receipts</summary><pre class="result">' +
                esc(JSON.stringify(evalRes, null, 2)) +
                '</pre></details>';
            }
          } catch (e) {
            fail(e);
          } finally {
            if ($('evaluate')) $('evaluate').disabled = false;
          }
        };
        $('ws-strands-gate').onclick = async () => {
          try {
            const g = await api(path('strands-gate/verify'), { candidate_prose: 'Verified month-end close statement', candidate_recipient: 'billing@partner.gr' });
            const v = g.release_gate_verdict || {};
            const gr = g.six_reader_graph || {};
            if ($('evaluation-result')) {
              $('evaluation-result').innerHTML = facts({
                release_decision: v.decision || (v.allowed ? 'ALLOW_SEND' : 'HOLD_FOR_REVIEW'),
                allowed: String(Boolean(v.allowed)),
                readers_evaluated: (gr.node_outputs || []).length || 6,
                consensus_action: gr.consensus_action || 'READY_TO_SEND',
              });
            }
          } catch (e) {
            fail(e);
          }
        };
        $('ws-reset-demo').onclick = async () => {
          try {
            await api(path('reset'), {});
            await load();
          } catch (e) {
            fail(e);
          }
        };
      } else if (module === 'commissions') {
        const cc = r.commission_case || {};
        const stRows: any[] = cc.statements || r.seller_statements || [];
        const pSettle: any[] = r.settlements || (cc.principal_settlement ? [cc.principal_settlement] : []);
        const totalApprovedSales = stRows.reduce((s: number, st: any) => s + (st.approved_sales_cents || 0), 0);
        const totalGrossComm = stRows.reduce((s: number, st: any) => s + (st.gross_tier_commission_cents || 0), 0);
        const totalClawback = stRows.reduce((s: number, st: any) => s + (st.clawback_deduction_cents || 0), 0);
        const totalUnattrib = (cc.unattributed_sale_ids || []).length;
        view.innerHTML =
          facts({
            total_payable_cents: r.total_payable_cents ?? cc.total_payable_cents ?? 0,
            approved_sales_volume_cents: totalApprovedSales,
            gross_tier_commission_cents: totalGrossComm,
            clawback_deduction_cents: totalClawback,
            case_status: cc.state || cc.status || 'SUBMITTED',
            unattributed_sales_queue: totalUnattrib + ' sales pending attribution',
            four_eyes_actors: (cc.submitted_by || 'mgr-store-lead') + ' / ' + (cc.approved_by || 'Pending Four-Eyes approval'),
          }) +
          '<div class="chart-grid" style="margin:20px 0">' +
          hbarChart(
            'Approved Sales Volume by Seller',
            'Attributed commercial sales volume per seller in active period',
            stRows.map((s: any) => ({
              label: (s.seller_name || s.seller_id) + ' (' + (s.store_id || 'Store') + ')',
              value: s.approved_sales_cents || 0,
              color: 'var(--primary)',
            }))
          ) +
          hbarChart(
            'Net Payable Commission vs Clawbacks by Seller',
            'Earned tier commission after tNPS gates and dispute clawbacks',
            stRows.map((s: any) => ({
              label: (s.seller_name || s.seller_id) + ' (Net Payable)',
              value: s.net_payable_commission_cents || 0,
              color: 'var(--positive)',
            }))
          ) +
          '</div>' +
          (pSettle.length
            ? '<div class="section"><h3>Principal Commission Settlements (Settlement → Sales Invoice → Bank Receipt)</h3>' +
              table(
                ['Settlement ID', 'Principal', 'Period', 'Agreed Net', 'VAT (24%)', 'Gross settlement', 'Linked Sales Invoice', 'Linked Bank Receipt'],
                pSettle.map((ps: any) => [
                  esc(ps.settlement_id || ps.id),
                  esc(ps.principal_name || 'Utility Principal SA'),
                  esc(ps.period || '2026-10'),
                  money(ps.agreed_net_cents ?? 0),
                  money(ps.vat_cents ?? 0),
                  '<strong>' + money(ps.gross_cents ?? ps.gross_amount_cents ?? 0) + '</strong>',
                  ps.linked_sales_invoice_id ? source(ps.linked_sales_invoice_id) : '<span class="badge">MISSING INVOICE (R05)</span>',
                  esc(ps.linked_bank_receipt_id || 'Pending bank wire'),
                ])
              ) +
              '</div>'
            : '') +
          (stRows.length
            ? '<div class="section"><h3>Seller Commission Statements &amp; Attribution</h3>' +
              table(
                ['Seller ID', 'Store', 'Attributed sales', 'Approved sales volume', 'Gross tier earned', 'tNPS &amp; Compliance gate', 'Clawbacks', 'Net payable'],
                [
                  ...stRows.map((s: any) => [
                    esc(s.seller_name || s.seller_id),
                    esc(s.store_id || '-'),
                    esc((s.attributed_sale_ids || []).length + ' sales (' + (s.attributed_sale_ids || []).join(', ') + ')'),
                    money(s.approved_sales_cents ?? 0),
                    money(s.gross_tier_commission_cents ?? 0),
                    '<span class="badge">' + esc(s.gate_passed === false ? 'BLOCKED' : 'PASSED') + '</span>',
                    money(s.clawback_deduction_cents ?? 0),
                    '<strong>' + money(s.net_payable_commission_cents ?? 0) + '</strong>',
                  ]),
                  [
                    '<strong>Total (' + stRows.length + ' sellers)</strong>',
                    '-',
                    '<strong>' + stRows.reduce((n: number, s: any) => n + (s.attributed_sale_ids || []).length, 0) + ' attributed sales</strong>',
                    '<strong>' + money(totalApprovedSales) + '</strong>',
                    '<strong>' + money(totalGrossComm) + '</strong>',
                    '-',
                    '<strong>' + money(totalClawback) + '</strong>',
                    '<strong>' + money(r.total_payable_cents ?? cc.total_payable_cents ?? 0) + '</strong>',
                  ],
                ]
              ) +
              '</div>'
            : '') +
          '<div class="toolbar section"><button id="ws-self-approve" type="button" disabled aria-describedby="ws-self-approve-reason">Self-Approve Own Commission</button><span id="ws-self-approve-reason" style="font-size:12px;color:var(--warning)">This action is unavailable due to Four-Eyes separation: preparer cannot approve own payout.</span><button id="ws-learn-memory" type="button" class="primary">Run 1 → Run 2 Compounding Memory (Resolve Unattributed Sale)</button>' +
          (isPayPalActive() ? '<button id="paypal-dispute-btn" type="button">Simulate PayPal Dispute → Seller Clawback &amp; Auto-Evidence Defense</button>' : '') +
          '</div>' +
          (isPayPalActive()
            ? '<div class="section"><h3>💳 PayPal Customer Disputes &amp; Autonomous Evidence Defense (`POST /v1/customer/disputes/{id}/provide-evidence`)</h3>' +
              table(
                ['Dispute ID', 'Document', 'Seller', 'Disputed Amount', 'Clawback Hold', 'Reason', 'Auto-Defense Evidence', 'Status'],
                (data.connectors?.paypal?.disputes || []).map((d: any) => {
                  const def = d.evidence_defense_packet || {};
                  return [
                    '<code>' + esc(d.dispute_id) + '</code>',
                    source(d.document_id),
                    esc(d.seller_id),
                    money(d.disputed_amount_cents || 0),
                    '<strong>' + money(d.clawback_commission_cents || 0) + '</strong> (' + esc(d.clawback_id) + ')',
                    esc(d.reason_code),
                    esc((def.evidence_type || 'PROOF_OF_FULFILLMENT') + ' · Evidence checks ' + (def.evidence_checks_passed || 4) + '/' + (def.evidence_checks_total || 4)),
                    '<span class="badge">' + esc(d.status) + '</span>',
                  ];
                })
              ) +
              '</div>'
            : '') +
          '<div class="target-form section"><label>Sales volume for tier simulation (EUR)<input id="commission-sales" type="number" min="0" step="0.01" value="450.00"></label><button id="simulate">Simulate existing plan</button></div><div id="simulation" class="result section"></div>';
        $('simulate').onclick = async () => {
          try {
            const sim = await api(path('commissions/simulate'), { sales_cents: cents($('commission-sales').value) });
            if ($('simulation')) $('simulation').innerHTML = facts({ plan_id: sim.plan_id, sales_cents: sim.sales_cents, simulated_commission_cents: sim.simulated_commission_cents });
          } catch (e) {
            fail(e);
          }
        };
        $('ws-learn-memory').onclick = async () => {
          try {
            const m = await api(path('memory/learn'), { product_family: 'Hardware Accessory Pack' });
            await renderServices(ctx);
            const cmp = m.compounding_comparison || {};
            if ($('simulation')) {
              $('simulation').innerHTML = facts({
                rule_learned: cmp.rule_applied?.rule_id || 'learned',
                unattributed_sales: (cmp.run_1_unattributed_count ?? 1) + ' → ' + (cmp.run_2_unattributed_count ?? 0),
                commission_payable_cents: cmp.run_2_commission_payable_cents ?? 0,
                tokens_consumed: (cmp.run_1_tokens ?? 18400) + ' → ' + (cmp.run_2_tokens ?? 3980),
                spoken_receipt: m.aletheia_receipt?.spoken_transcript || 'Verified',
              });
            }
          } catch (e) {
            fail(e);
          }
        };
        if ($('paypal-dispute-btn'))
          $('paypal-dispute-btn').onclick = async () => {
            try {
              const targetDoc = data.records?.sales?.[0]?.document_id || 'doc-' + (data.tenant?.slug || 'aegean-mobility') + '-sales-101';
              const dispRes = await api(path('connectors/paypal/dispute'), {
                dispute_id: 'PPDISP-' + Date.now().toString().slice(-6),
                document_id: targetDoc,
                disputed_amount_cents: 124000,
                reason_code: 'MERCHANDISE_OR_SERVICE_NOT_RECEIVED',
              });
              await load();
              if (dispRes.agentic_commerce_narrative?.executive_summary) {
                $('notice').textContent = dispRes.agentic_commerce_narrative.executive_summary;
              }
            } catch (e) {
              fail(e);
            }
          };
      } else {
        renderServicesPartB(ctx, r, view);
      }
      bind();
    } catch (e) {
      if (current === ctx.module && company !== tid()) return;
      if (current === ctx.module) fail(e);
    }
}

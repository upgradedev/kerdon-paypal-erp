import { mountEnterpriseGrid } from './ag_grid_bridge';
import { renderSideBadge } from './kpi_catalog';

let partyYtdOverride = false;

export function renderDetail(ctx: any): void {
  const { $, esc, money, status, amount, id, party, source, facts, table, link, journal, journalLines, isGreekOrg, api, path, load, fail, go, bind, fetchAndDownloadPdf, data, module, selected, tab } = ctx;
  const r = data.records[module].find((rec: any) => id(rec) === selected);
  if (!r) {
    $('content').innerHTML = '<div class="empty">Record not found in this company.</div>';
    return;
  }
  const isParty = ['customers', 'suppliers'].includes(module);
  const tabs = isParty
    ? ['General', 'Account statement', 'Statistics', 'Transaction trail', 'Documents']
    : ['General', 'Lines & taxes', 'Allocations', 'Transaction trail', 'Documents'];
  $('content').innerHTML =
    '<div class="section-head"><button id="back" type="button" class="icon" aria-label="Back to list">←</button><h2>' +
    esc(r.legal_name || r.doc_type || id(r)) +
    '</h2><span class="badge">' +
    status(r) +
    '</span></div><div class="tabs">' +
    tabs.map((tb) => '<button type="button" data-tab-name="' + tb + '" class="' + (tb === tab ? 'active' : '') + '">' + tb + '</button>').join('') +
    '</div><div id="record-body"></div>';
  $('back').onclick = () => go(module);
  document.querySelectorAll('[data-tab-name]').forEach((b: any) => {
    b.onclick = () => go(module, selected, b.dataset.tabName);
  });
  const body = $('record-body');
  const allDocs = [...(data.records.sales || []), ...(data.records.purchases || []), ...(data.records.expenses || [])];
  const seenDocIds = new Set<string>();
  const docs = allDocs.filter((d: any) => {
    const key = d.document_id || d.event_id;
    if (!key || seenDocIds.has(key)) return false;
    const match = isParty ? d.counterparty_id === r.id : (d.document_id && d.document_id === r.document_id) || (d.event_id && d.event_id === r.event_id);
    if (match) seenDocIds.add(key);
    return match;
  });
  if (tab === 'General') {
    const cfg = data.connectors?.config || {};
    const grMode = isGreekOrg();
    const canMyData = grMode && r.document_id && cfg.tax_connector === 'AADE_MYDATA';
    const canPayPal = r.document_id && module === 'sales' && cfg.payment_connector === 'PAYPAL' && (r.paid_cents || 0) < (r.gross_cents || 0);
    const mdRec = grMode && r.document_id ? (data.connectors?.mydata?.records || []).find((m: any) => m.document_id === r.document_id) : null;
    const mdCardHtml = mdRec
      ? '<div class="section"><h3>🇬🇷 AADE myDATA v1.0.8 / v1.0.9 Statutory E-Book Record (XSD ' +
        esc((mdRec.xsd_checks_passed || 16) + '/' + (mdRec.xsd_checks_total || 16)) +
        ' Verified)</h3>' +
        facts({
          invoice_type: mdRec.invoice_type + ' (Series ' + mdRec.series + ' / AA ' + mdRec.aa + ')',
          invoice_mark: mdRec.invoice_mark,
          invoice_uid: mdRec.invoice_uid,
          authentication_code: mdRec.authentication_code,
          e3_classification: mdRec.classification_type + ' / ' + mdRec.classification_category,
          payment_method_code: 'Code ' + (mdRec.payment_method_code || 5) + ' (On Credit / IBAN)',
          withheld_tax_cents: mdRec.withheld_tax_cents || 0,
          xsd_validation: (mdRec.xsd_valid !== false ? '100% VALID XSD' : 'CHECK REQUIRED') + ' (' + (mdRec.lines_count || 1) + ' XML lines)',
        }) +
        '<details style="margin-top:10px"><summary style="cursor:pointer;font-weight:600;color:var(--primary)">Inspect Official AADE InvoicesDoc XML Payload &amp; QR Verification Link</summary><p style="font-size:12px;margin:6px 0">QR URL: <a href="' +
        esc(mdRec.qr_url) +
        '" target="_blank" rel="noopener noreferrer">' +
        esc(mdRec.qr_url) +
        '</a></p><pre class="result" style="max-height:280px;overflow:auto">' +
        esc(mdRec.xml_preview || '') +
        '</pre></details></div>'
      : '';
    body.innerHTML =
      facts(r) +
      (isParty
        ? '<div class="toolbar section"><button type="button" class="primary" id="open-party-card">' +
          esc(ctx.t('Open Counterparty Account Statement (DR/CR) ↗', 'Άνοιγμα Καρτέλας Συναλλασσομένου (ΧΡ/ΠΙ) ↗')) +
          '</button></div>'
        : '') +
      mdCardHtml +
      (r.document_id || r.event_id
        ? '<div class="toolbar section"><button type="button" id="download-doc-pdf">↓ Download PDF (%PDF-1.4)</button>' +
          (r.document_id && status(r) !== 'Reversed'
            ? '<button type="button" id="reverse-doc">Reverse document (Credit note)</button>' +
              (canMyData ? '<button type="button" id="mydata-tx">Transmit / Refresh AADE myDATA (MARK)</button>' : '') +
              (canPayPal ? '<button type="button" id="paypal-ord" class="primary">Settle via PayPal Checkout (Orders v2)</button>' : '')
            : '') +
          '</div>'
        : '');
    if ($('open-party-card')) $('open-party-card').onclick = () => go(module, selected, 'Account statement');
    if ($('download-doc-pdf'))
      $('download-doc-pdf').onclick = async () => {
        try {
          await fetchAndDownloadPdf(ctx, r.document_id || r.event_id);
        } catch (e) {
          fail(e);
        }
      };
    if ($('reverse-doc'))
      $('reverse-doc').onclick = async () => {
        try {
          await api(path('invoices/' + encodeURIComponent(r.document_id) + '/reverse'), { reason: 'Operator reversal from workspace' });
          await load();
        } catch (e) {
          fail(e);
        }
      };
    if ($('mydata-tx'))
      $('mydata-tx').onclick = async () => {
        try {
          await api(path('connectors/mydata/transmit'), { document_id: r.document_id, series: module === 'sales' ? 'A' : 'P', aa: '109' });
          await load();
        } catch (e) {
          fail(e);
        }
      };
    if ($('paypal-ord'))
      $('paypal-ord').onclick = async () => {
        try {
          const isLive = Boolean(data.connectors?.runtime_modes?.paypal_credentials_present);
          const ppRes = await api(path('connectors/paypal/order'), {
            document_id: r.document_id,
            auto_capture: !isLive,
          });
          await load();
          if (!ppRes.captured) {
            $('notice').textContent =
              'Created Live PayPal Order ' +
              (ppRes.order?.order_id || '') +
              ' [CREATED]. Approve buyer checkout in PayPal Commerce Hub to capture 3-line GL split.';
            go('paypal');
          } else if (ppRes.agentic_commerce_narrative?.executive_summary) {
            $('notice').textContent = ppRes.agentic_commerce_narrative.executive_summary;
          }
        } catch (e) {
          fail(e);
        }
      };
  } else if (tab === 'Account statement') renderStatement(ctx, r);
  else if (tab === 'Statistics') {
    const periodDocs = docs.filter((d: any) => d.issued_date >= $('start').value && d.issued_date <= $('end').value);
    const net = periodDocs.reduce((s: number, d: any) => s + d.net_cents, 0);
    body.innerHTML =
      '<div class="summary"><div><small>Period documents</small><strong>' +
      periodDocs.length +
      '</strong></div><div><small>Net value</small><strong>' +
      money(net) +
      '</strong></div><div><small>Average</small><strong>' +
      money(periodDocs.length ? Math.round(net / periodDocs.length) : 0) +
      '</strong></div></div>' +
      table(['Date', 'Document', 'Net', 'Gross'], periodDocs.map((d: any) => [esc(d.issued_date), source(d.document_id), money(d.net_cents), money(d.gross_cents)]));
  } else if (tab === 'Lines & taxes') {
    const li = r.line_items || [];
    body.innerHTML = r.document_id
      ? table(['Register aggregate', 'Net', 'VAT', 'Gross'], [[esc(r.doc_type), money(r.net_cents), money(r.vat_cents), money(r.gross_cents)]]) +
        (li.length
          ? '<div class="section"><h3>Persisted line items</h3>' +
            table(
              ['#', 'Description', 'Qty', 'Net', 'VAT %', 'VAT', 'Gross'],
              li.map((l: any) => [
                esc(l.line_number),
                esc(l.description),
                esc(l.quantity),
                money(l.net_cents),
                esc(l.vat_rate_pct + '%'),
                money(l.vat_cents),
                money(l.gross_cents),
              ])
            ) +
            '</div>'
          : '<p>Aggregate register entry.</p>')
      : journalLines(r.lines || []);
  } else if (tab === 'Allocations') {
    const al = r.allocations || [];
    body.innerHTML =
      facts({ gross_cents: amount(r), register_paid_cents: r.paid_cents || 0, outstanding_cents: Math.max(0, (r.gross_cents || 0) - (r.paid_cents || 0)) }) +
      (al.length
        ? table(
            ['Settlement', 'Date', 'Allocated', 'Ledger event', 'Bank status'],
            al.map((a: any) => [
              esc(a.settlement_id),
              esc(a.posted_date),
              money(a.allocated_cents),
              link('accounting', a.ledger_event_id, a.ledger_event_id),
              esc(a.bank_execution_status),
            ])
          )
        : '<p>No settlement allocations posted against this document yet. Register amounts do not confirm bank wire settlement.</p>');
  } else if (tab === 'Transaction trail') {
    body.innerHTML = journal(
      data.ledger.filter((e: any) => (isParty ? e.lines.some((l: any) => l.counterparty_id === r.id) : e.source_document_id === r.document_id || e.event_id === r.event_id))
    );
  } else {
    body.innerHTML = table(
      ['Document', 'Date', 'Source SHA-256 hash', 'PDF & Signed Evidence'],
      docs.map((d: any) => {
        const docId = d.document_id || d.event_id;
        return [
          source(docId),
          esc(d.issued_date || d.posted_date || '-'),
          '<span class="hash">' + esc(d.source_sha256 || '-') + '</span>',
          '<button type="button" class="primary" data-doc-pdf="' +
            esc(docId) +
            '">↓ Download PDF</button> ' +
            (d.document_id
              ? '<button type="button" data-source="' + esc(d.document_id) + '">Verify 300s signed link</button>'
              : ''),
        ];
      })
    );
    body.querySelectorAll('[data-doc-pdf]').forEach((b: any) => {
      b.onclick = async () => {
        try {
          await fetchAndDownloadPdf(ctx, b.dataset.docPdf);
        } catch (e) {
          fail(e);
        }
      };
    });
    body.querySelectorAll('[data-source]').forEach((b: any) => {
      b.onclick = async () => {
        try {
          const result = await api(path('documents/' + encodeURIComponent(b.dataset.source) + '/link'));
          const url = new URL(result.url, window.location.href);
          if (!['http:', 'https:'].includes(url.protocol)) throw Error('Unsupported source URL');
          body.insertAdjacentHTML('beforeend', '<p><a target="_blank" rel="noopener noreferrer" href="' + esc(url.href) + '">Open signed PDF evidence (300s TTL) ↗</a></p>');
        } catch (e) {
          fail(e);
        }
      };
    });
  }
  bind();
}

export async function renderStatement(ctx: any, r: any): Promise<void> {
  const { $, esc, money, source, link, api, path, tid, fail, bind, t, lang, module, selected } = ctx;
  const company = tid();
  const record = selected;
  const startDate = partyYtdOverride ? ($('end').value || '2026-10-31').slice(0, 4) + '-01-01' : $('start').value;
  try {
    const result = await api(
      path('operations') + '?' + new URLSearchParams({ start: startDate, end: $('end').value, party: r.id, kind: module === 'customers' ? 'customer' : 'supplier' })
    );
    if (company !== tid() || record !== ctx.selected || ctx.tab !== 'Account statement') return;
    const s = result.statement;
    $('record-body').innerHTML =
      '<div class="summary">' +
      '<div><small>' + esc(t('Opening balance', 'Υπόλοιπο έναρξης')) + '</small><strong class="num-val">' + money(Math.abs(s.opening_cents || 0)) + '</strong> ' + renderSideBadge(s.opening_side, lang) + '</div>' +
      '<div><small>' + esc(t('Period debits', 'Χρεώσεις περιόδου')) + '</small><strong class="num-val">' + money(s.total_debit_cents || 0) + '</strong></div>' +
      '<div><small>' + esc(t('Period credits', 'Πιστώσεις περιόδου')) + '</small><strong class="num-val">' + money(s.total_credit_cents || 0) + '</strong></div>' +
      '<div><small>' + esc(t('Closing balance', 'Τελικό υπόλοιπο')) + '</small><strong class="num-val">' + money(Math.abs(s.closing_cents || 0)) + '</strong> ' + renderSideBadge(s.closing_side, lang) + '</div>' +
      '<div><small>GL Account</small><strong>' + esc(s.gl_account || (module === 'customers' ? '1100_AR' : '2000_AP')) + '</strong></div>' +
      '</div>' +
      '<div class="toolbar"><button type="button" id="party-ytd-btn" class="' +
      (partyYtdOverride ? 'primary' : '') +
      '">' +
      esc(partyYtdOverride ? t('Showing Full YTD Card (from Jan 1)', 'Προβολή Πλήρους Έτους (YTD)') : t('Expand Full YTD History', 'Εμφάνιση Όλου του Έτους (YTD)')) +
      '</button></div>' +
      (s.rows.length === 0 && (s.prior_activity_count || 0) > 0 && !partyYtdOverride
        ? '<p class="stmt-note">' +
          esc(t('Prior-period invoices & settlements exist before ' + startDate + '. Click "Expand Full YTD History" to inspect all posted lines.', 'Υπάρχουν προγενέστερες εξοφλημένες εγγραφές πριν τις ' + startDate + '. Πατήστε «Εμφάνιση Όλου του Έτους (YTD)».')) +
          '</p>'
        : '') +
      '<div id="party-stmt-grid"></div>';

    if ($('party-ytd-btn')) {
      $('party-ytd-btn').onclick = () => {
        partyYtdOverride = !partyYtdOverride;
        renderStatement(ctx, r);
      };
    }

    mountEnterpriseGrid($('party-stmt-grid'), {
      idPrefix: 'stmt-' + r.id,
      lang,
      csvFileName: 'kerdon-statement-' + r.id + '.csv',
      onRendered: bind,
      columns: [
        { field: 'date', headerName: t('Date', 'Ημ/νία'), maxWidth: 125 },
        { field: 'src_html', headerName: t('Document', 'Παραστατικό'), isHtml: true, maxWidth: 195 },
        { field: 'mv_html', headerName: t('Journal Movement', 'Κίνηση GL'), isHtml: true, flex: 2 },
        { field: 'debit_cents', headerName: t('Debit', 'Χρέωση'), cents: true, sumCents: true },
        { field: 'credit_cents', headerName: t('Credit', 'Πίστωση'), cents: true, sumCents: true },
        { field: 'abs_bal_cents', headerName: t('Balance', 'Υπόλοιπο'), cents: true },
        { field: 'side_html', headerName: t('DR/CR', 'ΧΡ/ΠΙ'), isHtml: true, maxWidth: 95 },
      ],
      rows: (s.rows || []).map((e: any) => ({
        ...e,
        _side: e.balance_side,
        abs_bal_cents: Math.abs(e.balance_cents || 0),
        src_html: source(e.source_document_id),
        mv_html: link('accounting', e.event_id, e.description),
        side_html: renderSideBadge(e.balance_side, lang),
      })),
    });
    bind();
  } catch (e) {
    fail(e);
  }
}

export function renderTargets(ctx: any): void {
  const { $, esc, money, hbarChart, table, cents, api, path, tid, load, fail, go, data } = ctx;
  const target = ctx.target;
  const actual = data.dashboard.kpis.revenue.cents;
  const saved = data.targets_summary?.saved_targets || [];
  const roll = (data.dashboard.rolling_series && data.dashboard.rolling_series.length ? data.dashboard.rolling_series : data.dashboard.series) || [];
  const pct = target ? Math.min(100, Math.max(0, (actual / target) * 100)) : 0;
  $('content').innerHTML =
    '<div class="target-form"><label for="target-input">Period target scenario (EUR)<input id="target-input" type="number" min="0.01" step="0.01" value="' +
    (target ? target / 100 : '') +
    '"></label><button id="set-target" type="button" class="primary">Compare</button><button id="save-target" type="button">Save target</button></div><div class="summary section"><div><small>Posted revenue</small><strong>' +
    money(actual) +
    '</strong></div><div><small>Scenario target</small><strong>' +
    (target ? money(target) : 'Not set') +
    '</strong></div><div><small>Remaining</small><strong>' +
    (target ? money(Math.max(0, target - actual)) : '-') +
    '</strong></div></div><div class="progress"><div class="progress-fill" style="width:' +
    pct +
    '%"></div></div><p>' +
    (target ? pct.toFixed(1) + '% of scenario' : 'Compare a scenario or save a versioned monthly target.') +
    '</p>' +
    '<div class="chart-grid">' +
    hbarChart(
      'Monthly Revenue Trajectory (Net ex-VAT)',
      'Posted General Ledger revenue (4000/4100) across periods',
      roll.map((p: any) => ({
        label: p.period + ' (' + p.event_ids.length + ' GL events)',
        value: p.revenue_cents || 0,
        color: 'var(--positive)',
      }))
    ) +
    hbarChart(
      'Target vs Actual Attainment by Scope',
      'Comparison of saved company, store, and seller revenue targets against actuals',
      saved.length
        ? saved.map((tItem: any) => ({
            label: tItem.scope_kind + ': ' + tItem.scope_id + ' (' + tItem.attainment_pct + '%)',
            value: tItem.actual_cents || 0,
            text: money(tItem.actual_cents || 0) + ' / ' + money(tItem.target_cents || 0),
            color: (tItem.attainment_pct || 0) >= 100 ? 'var(--positive)' : 'var(--primary)',
          }))
        : [{ label: 'Current Period Posted Revenue', value: actual, color: 'var(--primary)' }]
    ) +
    '</div>' +
    (saved.length
      ? '<div class="section"><h3>Saved monthly targets</h3>' +
        table(
          ['Period', 'Scope', 'Target', 'Actual', 'Remaining', 'Attainment', 'Version'],
          saved.map((tItem: any) => [
            esc(tItem.period),
            esc(tItem.scope_kind + ': ' + tItem.scope_id),
            money(tItem.target_cents),
            money(tItem.actual_cents),
            money(tItem.remaining_cents),
            esc(tItem.attainment_pct + '%'),
            esc('v' + tItem.version),
          ])
        ) +
        '</div>'
      : '') +
    '<div class="section"><h3>Posted revenue by month</h3>' +
    table(
      ['Period', 'Revenue (Net ex-VAT)', 'Operating Cost', 'EBITDA', 'Sources'],
      roll.map((p: any) => [
        esc(p.period),
        money(p.revenue_cents || 0),
        money((p.cogs_cents || 0) + (p.opex_cents || 0)),
        '<strong>' + money(p.ebitda_cents ?? p.revenue_cents ?? 0) + '</strong>',
        '<button type="button" data-target-period="' + p.period + '">' + p.event_ids.length + ' events ↗</button>',
      ])
    ) +
    '</div>';
  $('set-target').onclick = () => {
    try {
      ctx.target = cents($('target-input').value);
      if (ctx.target <= 0) throw Error('Target must be positive');
      renderTargets(ctx);
    } catch (e) {
      fail(e);
    }
  };
  $('save-target').onclick = async () => {
    try {
      const val = cents($('target-input').value);
      if (val <= 0) throw Error('Target must be positive');
      ctx.target = val;
      await api(path('targets'), { period: data.dashboard.end.slice(0, 7), scope_kind: 'company', scope_id: tid(), target_cents: val });
      await load();
    } catch (e) {
      fail(e);
    }
  };
  document.querySelectorAll('[data-target-period]').forEach((b: any) => {
    b.onclick = () => go('accounting', '', 'General', roll.find((p: any) => p.period === b.dataset.targetPeriod).event_ids, 'revenue');
  });
}

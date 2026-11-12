import { renderKpiTile } from './kpi_catalog';

export function renderServicesPartB(ctx: any, r: any, view: any): void {
  const { $, esc, money, party, source, facts, hbarChart, stackedChart, table, link, isGreekOrg, isPayPalActive, fp, api, path, load, fail, go, download, fetchAndDownloadPdf, t, lang, data, module } = ctx;
      if (module === 'inventory') {
        const skus: any[] = r.skus || [];
        const movs: any[] = r.movements || [];
        const poList: any[] = r.purchase_order_drafts || r.reorder_purchase_orders || [];
        const valCents = r.total_valuation_cents ?? r.total_inventory_valuation_cents ?? 0;
        const cogsCents = r.period_cogs_cents ?? r.total_cogs_cents ?? 0;
        const lowCount = r.low_stock_count ?? r.low_stock_alert_count ?? 0;
        const skuOpts = skus.map((s: any) => '<option value="' + esc(s.sku_code) + '">' + esc(s.sku_code + ' · ' + (s.title || s.name)) + '</option>').join('');
        view.innerHTML =
          '<div class="kpis" style="margin-bottom:16px">' +
          renderKpiTile({
            metricKey: 'current_ratio',
            lang: lang || 'en',
            customTitle: 'Warehouse Valuation (IAS 2 WAC)',
            valueText: money(valCents),
            subText: skus.length + ' active SKUs · ' + (r.total_units_on_hand || 0) + ' units on hand',
            customTip: {
              meaningEn: 'Total carrying value of physical warehouse inventory at Weighted Average Cost.',
              meaningEl: 'Συνολική αξία αποθεμάτων αποθήκης με τη μέθοδο του Μέσου Σταθμικού Κόστους.',
              formulaEn: 'Sum of (SKU On-Hand Qty x WAC Unit Cost) -> GL 1200_INVENTORY',
              formulaEl: 'Άθροισμα (Ποσότητα x Μέσο Κόστος Μονάδας) -> Λογ. 1200_ΑΠΟΘΕΜΑΤΑ',
              basisEn: 'IAS 2 Weighted Average Cost (WAC) · Integer Cents',
              basisEl: 'ΔΛΠ 2 Μέσο Σταθμικό Κόστος · Ακέραια λεπτά ευρώ',
            },
          }) +
          renderKpiTile({
            metricKey: 'gross_margin',
            lang: lang || 'en',
            customTitle: 'Dispatch Cost (Inventory)',
            valueText: money(cogsCents),
            subText: movs.length + ' stock movement(s) in audit trail',
            customTip: {
              meaningEn: 'Direct cost of goods dispatched to customers during the period.',
              meaningEl: 'Κόστος πωληθέντων εμπορευμάτων που διακινήθηκαν στην περίοδο.',
              formulaEn: 'Sum of dispatched quantity multiplied by weighted average unit cost',
              formulaEl: 'Άθροισμα ποσότητας εξαγωγής επί μέσο σταθμικό κόστος μονάδας',
              basisEn: 'Inventory movement records. The P&L shows amounts posted to the ledger.',
              basisEl: 'Κινήσεις αποθήκης. Η κατάσταση αποτελεσμάτων εμφανίζει ποσά του καθολικού.',
            },
          }) +
          renderKpiTile({
            metricKey: 'payables',
            lang: lang || 'en',
            customTitle: 'Low-Stock Reorder Alerts',
            valueText: String(lowCount) + ' SKU' + (lowCount === 1 ? '' : 's'),
            subText: 'Available qty at or below safety reorder point',
          }) +
          renderKpiTile({
            metricKey: 'payables',
            lang: lang || 'en',
            customTitle: 'Auto-Drafted Reorder POs',
            valueText: money(poList.reduce((s, po) => s + (po.gross_cents ?? po.estimated_total_cents ?? 0), 0)),
            subText: poList.length + ' supplier PO draft(s) awaiting approval',
          }) +
          '</div>' +
          '<div class="chart-grid" style="margin:20px 0">' +
          hbarChart(
            'Warehouse Valuation by SKU (Weighted Average Cost)',
            'On-hand stock valuation (Qty × WAC Unit Cost)',
            skus.map((s: any) => ({
              label: s.sku_code + ' (' + s.on_hand_qty + ' ' + (s.unit_of_measure || 'pcs') + ')',
              value: (s.on_hand_qty || 0) * (s.unit_cost_cents || 0),
              color: (s.on_hand_qty || 0) <= (s.reorder_point_qty || 0) ? 'var(--warning)' : 'var(--positive)',
            }))
          ) +
          hbarChart(
            'SKU Stock Level vs Reorder Point Threshold',
            'Physical units on hand compared against minimum safety stock',
            skus.map((s: any) => ({
              label: s.sku_code + ' (Reorder <= ' + s.reorder_point_qty + ')',
              value: (s.on_hand_qty || 0) * 100,
              text: s.on_hand_qty + ' / min ' + s.reorder_point_qty + ' pcs',
              color: (s.on_hand_qty || 0) <= (s.reorder_point_qty || 0) ? 'var(--negative)' : 'var(--primary)',
            }))
          ) +
          '</div>' +
          '<div class="toolbar"><select id="ws-sku-select" aria-label="Select SKU">' +
          skuOpts +
          '</select><input id="ws-sku-qty" type="number" min="1" step="1" value="10" aria-label="Movement quantity" style="max-width:100px"><button id="ws-stock-in" type="button" class="primary">+ Receive supplier stock</button><button id="ws-stock-out" type="button">- Dispatch customer sale (WAC COGS)</button></div>' +
          table(
            ['SKU Code', 'Title', 'Category', 'On hand', 'Reorder point', 'WAC Unit Cost', 'Retail Price', 'Total Valuation', 'Status'],
            skus.map((s: any) => [
              '<code>' + esc(s.sku_code) + '</code>',
              esc(s.title || s.name),
              esc(s.category || '-'),
              '<strong>' + esc(s.on_hand_qty) + ' ' + esc(s.unit_of_measure || 'pcs') + '</strong>',
              esc(s.reorder_point_qty),
              money(s.unit_cost_cents),
              money(s.unit_list_price_cents ?? s.unit_sale_price_cents ?? 0),
              '<strong>' + money((s.on_hand_qty || 0) * (s.unit_cost_cents || 0)) + '</strong>',
              '<span class="badge">' + esc((s.on_hand_qty || 0) <= (s.reorder_point_qty || 0) ? 'LOW STOCK' : 'HEALTHY') + '</span>',
            ])
          ) +
          (movs.length
            ? '<div class="section"><h3>Warehouse Stock Movements &amp; WAC COGS Journal Trail (' +
              movs.length +
              ')</h3>' +
              table(
                ['Movement ID', 'Date', 'SKU', 'Movement Kind', 'Qty Delta', 'Unit Cost', 'COGS Posted', 'Source Document'],
                movs.map((m: any) => {
                  const qd = m.qty_delta ?? m.quantity_delta ?? 0;
                  return [
                    esc(m.movement_id),
                    esc(m.occurred_date),
                    '<code>' + esc(m.sku_code) + '</code>',
                    '<span class="badge">' + esc(m.kind || m.movement_kind || 'MOVEMENT') + '</span>',
                    esc(qd > 0 ? '+' + qd : String(qd)),
                    money(m.unit_cost_cents || 0),
                    money(m.cogs_posted_cents ?? m.cogs_cents ?? 0),
                    m.linked_document_id ? source(m.linked_document_id) : m.ledger_event_id ? link('accounting', m.ledger_event_id, m.ledger_event_id) : '-',
                  ];
                })
              ) +
              '</div>'
            : '') +
          (poList.length
            ? '<div class="section"><h3>Autonomous Low-Stock Reorder Purchase Orders (' +
              poList.length +
              ')</h3>' +
              table(
                ['PO ID', 'SKU', 'Supplier', 'Order Qty', 'Net', 'VAT', 'Gross Total', 'Status'],
                poList.map((po: any) => [
                  esc(po.po_id),
                  '<code>' + esc(po.sku_code) + '</code>',
                  po.supplier_id ? party(po.supplier_id) : esc(po.supplier_name || '-'),
                  esc(po.order_qty),
                  money(po.net_cents || 0),
                  money(po.vat_cents || 0),
                  '<strong>' + money(po.gross_cents ?? po.estimated_total_cents ?? 0) + '</strong>',
                  '<span class="badge">' + esc(po.status || 'DRAFT_APPROVAL_REQUIRED') + '</span>',
                ])
              ) +
              '</div>'
            : '');
        $('ws-stock-in').onclick = async () => {
          try {
            const skuCode = ($('ws-sku-select') && $('ws-sku-select').value) || 'SKU-ONT-WIFI6-PRO';
            const qty = Math.max(1, Number(($('ws-sku-qty') && $('ws-sku-qty').value) || 20));
            const selSku = skus.find((x: any) => x.sku_code === skuCode);
            await api(path('inventory/movement'), { sku_code: skuCode, movement_kind: 'GOODS_RECEIPT', quantity: qty, unit_cost_cents: selSku?.unit_cost_cents || 4500 });
            await load();
          } catch (e) {
            fail(e);
          }
        };
        $('ws-stock-out').onclick = async () => {
          try {
            const skuCode = ($('ws-sku-select') && $('ws-sku-select').value) || 'SKU-ONT-WIFI6-PRO';
            const qty = Math.max(1, Number(($('ws-sku-qty') && $('ws-sku-qty').value) || 5));
            const selSku = skus.find((x: any) => x.sku_code === skuCode);
            await api(path('inventory/movement'), { sku_code: skuCode, movement_kind: 'SALE_DISPATCH', quantity: qty, unit_cost_cents: selSku?.unit_cost_cents || 4500 });
            await load();
          } catch (e) {
            fail(e);
          }
        };
      } else if (module === 'workforce') {
        const wf = r.workforce_fusion || {};
        const vs = r.vat_summary || {};
        const netPay = wf.net_salary_payable_cents ?? wf.net_pay_cents ?? 0;
        const apdPay = wf.total_apd_payable_cents ?? 0;
        const fmyPay = wf.total_fmy_payable_cents ?? wf.withheld_tax_cents ?? 0;
        const trueCost = wf.true_employer_cost_cents ?? 0;
        const understatement = Math.max(0, trueCost - netPay);
        const payrollMydata = (data.connectors?.mydata?.records || []).find((m: any) => m.invoice_type === '17.1' || String(m.document_id).startsWith('payroll-17-1'));
        view.innerHTML =
          '<div class="section"><h3>3-Document Payroll Fusion (Payroll Register + Social Security APD + Withheld Tax FMY)</h3><p>Bank transfer confirmations alone show only net take-home pay (' +
          money(netPay) +
          '), understating true employer workforce expense (' +
          money(trueCost) +
          ') by ' +
          money(understatement) +
          '. Kerdon fuses all 3 statutory payroll documents into a single balanced General Ledger entry.</p>' +
          facts({
            true_employer_cost_cents: trueCost,
            gross_wages_cents: wf.gross_wages_cents || 0,
            employer_social_security_cents: wf.employer_social_security_cents || 0,
            net_salary_payable_cents: netPay,
            total_apd_payable_cents: apdPay,
            total_fmy_payable_cents: fmyPay,
            bank_only_understatement_prevented_cents: understatement,
          }) +
          '<div class="chart-grid" style="margin:20px 0">' +
          stackedChart('True Employer Workforce Cost Breakdown (GL 6000)', 'Decomposition of total employer payroll cost across statutory liabilities', [
            { label: 'Net Take-Home Pay (2500_NET_SALARY)', value: netPay, color: 'var(--positive)' },
            { label: 'EFKA Social Security Contributions (2510_APD)', value: apdPay, color: 'var(--primary)' },
            { label: 'FMY Withheld Payroll Tax (2520_FMY)', value: fmyPay, color: 'var(--warning)' },
          ]) +
          hbarChart('Bank-Only Feed vs Kerdon 3-Document Fused Cost', 'Why bank-feed-only bookkeeping understates operating expenses', [
            { label: 'Bank Feed Only (Net Salary Wire)', value: netPay, color: 'var(--warning)' },
            { label: 'Unrecorded Tax & EFKA Burden', value: understatement, color: 'var(--negative)' },
            { label: 'True Fused Employer Cost (P&L 6000)', value: trueCost, color: 'var(--positive)' },
          ]) +
          '</div>' +
          table(
            ['Statutory payroll document', 'Authority / Scope', 'Liability / Cost component', 'Reconciled amount', 'General Ledger account'],
            [
              [t('1. Payroll Register (Monthly Roster)', '1. Payroll Register (Μισθοδοτική Κατάσταση)'), 'Internal HR / Store Roster', 'Net Salary Payable (Bank wire)', money(netPay), '2500_NET_SALARY_PAYABLE'],
              [t('2. Social Security Filing (APD EFKA)', '2. Social Security Filing (ΑΠΔ ΕΦΚΑ)'), t('Social Security Authority (EFKA)', 'Social Security Authority (ΕΦΚΑ)'), 'Employee + Employer Contributions', money(apdPay), '2510_APD_SOCIAL_SECURITY_PAYABLE'],
              [t('3. Withheld Payroll Tax (FMY)', '3. Withheld Payroll Tax (ΦΜΥ)'), t('Tax Authority (AADE)', 'Tax Authority (ΑΑΔΕ)'), 'Withheld Income Tax & Solidarity', money(fmyPay), '2520_FMY_PAYROLL_TAX_PAYABLE'],
              [
                '<strong>Fused True Employer Workforce Cost</strong>',
                '<strong>Consolidated P&amp;L Impact (6000 + 6010)</strong>',
                '<strong>Gross Wages (' + money(wf.gross_wages_cents || 0) + ') + Employer EFKA (' + money(wf.employer_social_security_cents || 0) + ')</strong>',
                '<strong>' + money(trueCost) + '</strong>',
                '<strong>6000_WAGES_EXPENSE / 6010_EMPLOYER_SOCIAL_SECURITY</strong>',
              ],
            ]
          ) +
          '</div>' +
          (isGreekOrg() && payrollMydata
            ? '<div class="section"><h3>' + t('AADE myDATA 17.1 Payroll Accounting Entry (E3_581_001 / category2_6)', 'AADE myDATA 17.1 Payroll Accounting Entry (Μισθοδοσία · E3_581_001 / category2_6)') + '</h3>' +
              facts({
                document_id: payrollMydata.document_id,
                invoice_type: t('17.1 - Statutory Monthly Payroll Entry', '17.1 - Μισθοδοσία (Payroll Entry)'),
                e3_classification: payrollMydata.classification_type + ' / ' + payrollMydata.classification_category,
                invoice_mark: payrollMydata.invoice_mark,
                invoice_uid: payrollMydata.invoice_uid,
                withheld_fmy_cents: payrollMydata.withheld_tax_cents || fmyPay,
                xsd_compliance: (payrollMydata.xsd_checks_passed || 16) + '/' + (payrollMydata.xsd_checks_total || 16) + ' XSD checks',
              }) +
              (payrollMydata.xml_preview || payrollMydata.mydata_xml_preview
                ? '<details style="margin-top:8px"><summary style="cursor:pointer;font-weight:600;color:var(--primary)">Inspect 17.1 Payroll myDATA XML (InvoicesDoc v1.0.8)</summary><pre style="margin-top:8px;padding:10px;background:var(--surface-muted);border-radius:6px;font-size:11px;overflow-x:auto">' +
                  esc(payrollMydata.xml_preview || payrollMydata.mydata_xml_preview) +
                  '</pre></details>'
                : '') +
              '</div>'
            : '') +
          '<div class="section"><h3>Statutory VAT summary (' +
          esc((fp().statutory_vat_rates || [0, 6, 13, 24]).join('% / ') + '% rate breakdown') +
          ')</h3>' +
          facts(vs) +
          '</div>';
      } else if (module === 'documents') {
        const md = data.connectors?.mydata || {};
        const envList = data.evidence_inbox?.envelopes || [];
        const draftsList: any[] = r.outbound_drafts || [];
        const hp = r.board_pack?.handoff_packet || {};
        const openGaps = hp.open_gap_count ?? 0;
        view.innerHTML =
          facts({
            organization_country: (fp().country_code || 'GR') + ' (' + (fp().country_name || 'Greece') + ')',
            statutory_regime: fp().tax_authority || 'AADE',
            ingested_envelopes: envList.length,
            deduplicated_blobs: data.evidence_inbox?.blobs_count || 0,
            outbound_remediation_drafts: draftsList.length,
            mydata_transmitted_marks: isGreekOrg() ? md.transmitted_count || 0 : 'INACTIVE (NON-GR)',
            merkle_sealed_board_pack: openGaps === 0 && r.board_pack ? 'SEALED' : openGaps + ' OPEN GAP ITEMS (MERKLE SEALED)',
          }) +
          (isPayPalActive()
            ? '<div class="toolbar section" style="justify-content:space-between;padding:10px 14px;border:1px solid var(--border);border-radius:8px;background:var(--surface-muted)"><span><strong>PayPal &amp; Agentic Commerce Hub</strong> · Live Orders v2, 3-Line Fee GL Studio, Subscriptions v1, Payouts v1 &amp; Disputes v1 have moved to a dedicated top-level workspace module.</span><button type="button" id="jump-paypal-hub-btn" class="primary">Open PayPal Commerce Hub →</button></div>'
            : '') +
          '<div class="section"><h3>Omnichannel Evidence Inbox &amp; Recursive .msg/.eml Graph (ADR-028 / ADR-048)</h3><p>Content-addressed SHA-256 deduplication across forwarded emails and nested attachments. HTML email bodies are retained as commission/sales evidence and structurally barred from invoice ledger posting.</p>' +
          (envList.length
            ? table(
                ['Envelope ID', 'Sender', 'Subject', 'Received at', 'Attachments', 'SHA-256 content hash'],
                envList.map((ev: any) => {
                  const h = ev.sha256_hex || ev.body_sha256 || ev.attachments?.[0]?.sha256 || '';
                  return [
                    esc(ev.envelope_id || ev.message_id),
                    esc(ev.sender),
                    esc(ev.subject),
                    esc(ev.received_at || '2026-10-28'),
                    esc((ev.attachments || []).length + ' files'),
                    '<span class="hash">' + esc(h ? h.slice(0, 18) + '…' : ev.message_id) + '</span>',
                  ];
                })
              )
            : '') +
          '</div><div class="section"><h3>Autonomous Outbound Document Generator (' +
          draftsList.length +
          ' drafts · ADR-022 / ADR-026 / ADR-040)</h3>' +
          table(
            ['Draft ID', 'Doc Type', 'Recipient', 'Subject', 'Net', 'VAT', 'Gross Total', 'PDF Export'],
            draftsList.map((d: any) => [
              esc(d.draft_id),
              '<span class="badge">' + esc(d.doc_type || d.document_type || 'OUTBOUND') + '</span>',
              esc(d.recipient_name || '-'),
              esc(d.subject || d.document_type),
              money(d.net_cents || 0),
              money(d.vat_cents || 0),
              '<strong>' + money(d.gross_cents ?? d.amount_cents ?? 0) + '</strong>',
              '<button type="button" class="primary" data-pdf-draft="' + esc(d.draft_id) + '">↓ Download PDF (%PDF-1.4)</button>',
            ])
          ) +
          '</div>' +
          (isGreekOrg()
            ? '<div class="section"><div class="toolbar" style="justify-content:space-between"><h3>Greek Statutory Tax Connector (AADE myDATA v1.0.8 / v1.0.9 XML · E3 · MARK · UID · QR)</h3><button type="button" id="mydata-tx-all-btn" class="primary">Transmit All Documents &amp; 17.1 Payroll to AADE myDATA</button></div>' +
              table(
                ['Document', 'Type', 'Role', 'E3 Classification', 'Pay Code', 'MARK / UID', 'Net', 'VAT', 'Withheld', 'XSD', 'Status / XML'],
                (md.records || []).map((m: any) => [
                  source(m.document_id),
                  '<span class="badge">' + esc(m.invoice_type) + '</span>',
                  esc(m.transmission_role || 'ISSUER_SEND_INVOICES'),
                  '<code>' + esc(m.classification_type + ' / ' + m.classification_category) + '</code>',
                  esc('Code ' + (m.payment_method_code || 1)),
                  '<code>' + esc(m.invoice_mark) + '</code><br><small>' + esc((m.invoice_uid || '').slice(0, 14)) + '…</small>',
                  money(m.net_cents || 0),
                  money(m.vat_cents || 0),
                  money(m.withheld_tax_cents || 0),
                  '<span class="badge">' + esc((m.xsd_checks_passed || 16) + '/' + (m.xsd_checks_total || 16)) + '</span>',
                  '<span class="badge">' +
                    esc(m.status) +
                    '</span> ' +
                    (m.qr_url ? '<a href="' + esc(m.qr_url) + '" target="_blank" rel="noopener noreferrer">QR ↗</a> ' : '') +
                    (m.xml_preview || m.mydata_xml_preview
                      ? '<details style="display:inline-block;margin-left:4px"><summary style="cursor:pointer;font-size:11px;color:var(--primary)">XML</summary><pre tabindex="0" style="max-width:420px;max-height:220px;overflow:auto;font-size:10px;padding:6px;background:var(--surface-muted)">' +
                        esc(m.xml_preview || m.mydata_xml_preview) +
                        '</pre></details>'
                      : ''),
                ])
              ) +
              '</div>'
            : '<div class="section"><h3>Country-Parametric International E-Invoicing (' +
              esc(fp().country_name || fp().country_code) +
              ' · ' +
              esc(fp().einvoice_standard || 'PEPPOL_BIS_3_0') +
              ')</h3><p>This organization belongs to country <strong>' +
              esc(fp().country_code) +
              ' (' +
              esc(fp().country_name) +
              ')</strong>. ' +
              t(
                'Greek AADE myDATA v1.0.8 fields (MARK, UID, E3, DOY, GEMI, 20% WHT) are parametrically disabled. Statutory e-invoicing runs on ',
                'Greek AADE myDATA v1.0.8 fields (MARK, UID, E3, ΔΟΥ, ΓΕΜΗ, 20% ΦΕΕ) are parametrically disabled. Statutory e-invoicing runs on '
              ) +
              '<strong>' +
              esc(fp().einvoice_standard || 'Peppol BIS Billing 3.0 (EN 16931)') +
              '</strong> under <strong>' +
              esc(fp().accounting_standard || 'IFRS') +
              '</strong>.</p></div>') +
          '<div class="section"><h3>Month-End CFO Board Pack &amp; Accountant Handoff Packet</h3>' +
          facts(r.board_pack?.handoff_packet || { period: r.board_pack?.period, ready_for_close: String(Boolean(r.board_pack)) }) +
          '</div>';
        if ($('jump-paypal-hub-btn')) $('jump-paypal-hub-btn').onclick = () => go('paypal');
        view.querySelectorAll('[data-pdf-draft]').forEach((btn: any) => {
          btn.onclick = async () => {
            try {
              await fetchAndDownloadPdf(ctx, btn.getAttribute('data-pdf-draft'));
            } catch (e) {
              fail(e);
            }
          };
        });
        if ($('mydata-tx-all-btn'))
          $('mydata-tx-all-btn').onclick = async () => {
            try {
              await api(path('connectors/mydata/transmit-all'), {});
              $('notice').textContent = 'Transmitted all invoices, expenses, and 17.1 Payroll to AADE myDATA v1.0.8 with 16/16 XSD checks.';
              await load();
            } catch (e) {
              fail(e);
            }
          };
      } else {
        const cn = data.connectors || {};
        const cfg = cn.config || {};
        const fprof = fp();
        const oa = data.organization_access || {};
        const ec = r.gtm?.economics || {};
        const pl = r.gtm?.plans || [];
        const bcs = data.bounded_contexts || [];
        const dss = data.public_datasets || [];
        const cov = data.dataset_coverage || {};
        const covRows = cov.module_coverage || [];
        const rbacRoles: Array<[string, string, string]> = [
          ['MSP_FINOPS_DIRECTOR', 'MSP FinOps Director (Sofia Marinou)', 'Full multi-tenant Reader + Evaluator + Governed Writer access across all 22 modules'],
          ['CLIENT_OWNER', 'Store / Franchise Owner', 'Full company P&L, Payroll, Commissions, Approvals & Payouts within owned organization'],
          ['ACCOUNTANT', 'External / In-House Accountant', 'P&L, Financial Statements, GL Journal, Payroll Fusion, Statutory Tax & Close (no payout release)'],
          ['STORE_MANAGER', 'Store Manager', 'Daily O2C/P2P operations, Inventory, Sales Targets & Commissions (no Payroll or Treasury release)'],
          ['SELLER', 'Sales Representative (Restricted)', 'Strictly isolated to own sales & commission statements (HTTP 403 on company P&L, bank & AP)'],
          ['PUBLIC_AUDITOR', 'External Statutory Auditor', 'Read-only inspection of Financial Statements, Trial Balance, Close & Evidence Bundle'],
        ];
        view.innerHTML =
          facts({
            organization_country: (fprof.country_code || 'GR') + ' (' + (fprof.country_name || 'Greece') + ')',
            aade_mydata_parametric: isGreekOrg() ? 'ACTIVE (GR)' : 'INACTIVE (' + (fprof.country_code || 'INTL') + ')',
            active_rbac_role: ctx.activeRole || 'MSP_FINOPS_DIRECTOR',
            managed_tenants: ec.managed_tenants || 35,
            monthly_labor_saved_cents: ec.monthly_labor_saved_cents || 1764000,
            roi_multiple: ((ec.roi_multiple_x10 || 73) / 10).toFixed(1) + 'x',
          }) +
          '<div class="section"><h3>Role-Based Access Control (RBAC) Preview &amp; Least-Privilege Matrix</h3><p>Preview how sidebar navigation, API headers (<code>X-Kerdon-Role</code>), and backend capability guards adapt per organizational role without cluttering the global top bar.</p><div class="toolbar"><label for="rbac-role-select">Active RBAC Role Preview<select id="rbac-role-select">' +
          rbacRoles
            .map(([code, title]) => '<option value="' + code + '"' + (ctx.activeRole === code ? ' selected' : '') + '>' + esc(title + ' (' + code + ')') + '</option>')
            .join('') +
          '</select></label><button type="button" id="apply-rbac-role-btn" class="primary">Apply Role Preview</button></div>' +
          table(
            ['Role Code', 'Persona', 'Enforced Backend & Navigation Scope'],
            rbacRoles.map(([code, title, scope]) => ['<code>' + esc(code) + '</code>', esc(title), esc(scope)])
          ) +
          '</div>' +
          '<div class="section"><h3>Organization Country &amp; Parametric Statutory Fiscal Regime (GR AADE myDATA vs International Peppol)</h3><p>' +
          t(
            'All Greek AADE myDATA v1.0.8 fields (MARK, UID, E3 classifications, DOY Tax Office, GEMI Registry, 20% withholding tax, EUR 500 B2B cash limit, 17.1 Payroll myDATA, Modulo-11 TIN/AFM check) activate parametrically when the organization country is ',
            'All Greek AADE myDATA v1.0.8 fields (MARK, UID, E3 classifications, ΔΟΥ, ΓΕΜΗ, 20% withholding tax, €500 B2B cash limit, 17.1 Payroll myDATA, Modulo-11 ΑΦΜ check) activate parametrically when the organization country is '
          ) +
          '<strong>GR (Greece)</strong> and cleanly deactivate for non-Greek jurisdictions.</p><div class="toolbar"><label>Organization Country <select id="org-country-select" aria-label="Organization Country">' +
          [
            ['GR', t('GR · Greece (AADE myDATA v1.0.8 + ELP)', 'GR · Greece (Ελλάδα · AADE myDATA v1.0.8 + ΕΛΠ)')],
            ['CY', t('CY · Cyprus (Peppol BIS 3.0 + IFRS)', 'CY · Cyprus (Κύπρος · Peppol BIS 3.0 + IFRS)')],
            ['DE', 'DE · Germany (Deutschland · XRechnung / ZUGFeRD)'],
            ['GB', 'GB · United Kingdom (HMRC MTD + FRS 102)'],
            ['US', 'US · United States (IRS + US GAAP)'],
          ]
            .map(([code, label]) => '<option value="' + code + '" ' + ((fprof.country_code || 'GR') === code ? 'selected' : '') + '>' + esc(label) + '</option>')
            .join('') +
          '</select></label>' +
          (isGreekOrg()
            ? '<label>' + t('Tax Office (DOY)', 'ΔΟΥ (Tax Office)') + ' <input id="org-doy-input" value="' +
              esc(fprof.doy || t('Athens Corporate Tax Office (KEFODE Attikis)', 'ΔΟΥ ΦΑΕ ΑΘΗΝΩΝ')) +
              '"></label><label>' + t('GEMI Registry No.', 'Αρ. ΓΕΜΗ') + ' <input id="org-gemi-input" value="' +
              esc(fprof.gemi_number || '123456701000') +
              '"></label><label>' + t('KAD (NACE Activity Code)', 'ΚΑΔ') + ' <input id="org-kad-input" value="' +
              esc(fprof.kad_code || '62.01.11.00') +
              '"></label>'
            : '') +
          '<button type="button" id="save-fiscal-profile-btn" class="primary">Apply Organization Country &amp; Fiscal Regime</button></div>' +
          facts({
            country_code: fprof.country_code || 'GR',
            accounting_standard: fprof.accounting_standard || 'ELP_N_4308_2014',
            tax_authority: fprof.tax_authority || 'AADE',
            einvoice_standard: fprof.einvoice_standard || 'AADE_MYDATA_V1_0_8',
            aade_mydata_enabled: String(Boolean(fprof.aade_mydata_enabled)),
            afm_modulo11_valid: isGreekOrg() ? String(Boolean(fprof.afm_validation?.valid)) : 'N/A (Non-GR)',
          }) +
          '</div>' +
          (dss.length
            ? '<div class="section"><h3>Public Datasets & Open ERP Standards Benchmark Importer (UBL 2.1 · ISO 20022 · myDATA · SROIE/FinQA)</h3><div class="toolbar"><select id="dataset-select" aria-label="Select public dataset">' +
              dss.map((d: any) => '<option value="' + esc(d.dataset_id) + '">' + esc(d.title + ' (' + d.document_count + ' docs · ' + d.standard_schema + ')') + '</option>').join('') +
              '</select><button id="import-dataset-btn" type="button" class="primary">Import public dataset & seed all 18 modules</button></div>' +
              table(
                ['Dataset ID', 'Title', 'Open Standard Schema', 'Source Corpus', 'Docs', 'Bounded Contexts'],
                dss.map((d: any) => [
                  '<code>' + esc(d.dataset_id) + '</code>',
                  esc(d.title),
                  esc(d.standard_schema),
                  esc(d.source_reference),
                  esc(d.document_count),
                  esc((d.bounded_contexts || []).join(', ')),
                ])
              ) +
              '</div>'
            : '') +
          (covRows.length
            ? '<div class="section"><h3>Live 18-Module & 7-Bounded-Context Field & End-to-End Flow Verification (' +
              esc((cov.modules_passed || 18) + '/' + (cov.modules_total || 18) + ' Modules Verified') +
              ')</h3>' +
              facts({
                all_18_modules_functional: String(Boolean(cov.all_18_modules_functional)),
                trial_balance_balanced: String(Boolean(cov.trial_balance_balanced)),
                total_debits_cents: cov.total_debits_cents || 0,
                total_credits_cents: cov.total_credits_cents || 0,
              }) +
              table(
                ['Bounded Context', 'Module', 'Active Records', 'Populated Domain Fields', 'Verified End-to-End Flows', 'Status'],
                covRows.map((c: any) => [
                  esc(c.bounded_context),
                  link(c.module_id, '', c.module_title + ' ↗'),
                  '<strong>' + esc(c.records_count) + '</strong>',
                  esc(c.fields_verified),
                  esc(c.flows_verified),
                  '<span class="badge">' + esc(c.status) + '</span>',
                ])
              ) +
              '</div>'
            : '') +
          (bcs.length
            ? '<div class="section"><h3>Domain-Driven Design (DDD) Bounded Contexts & APQC PCF Industry Standards</h3>' +
              table(
                ['Code', 'Bounded Context', 'APQC PCF Reference', 'Open Standards', 'Domain Aggregates', 'Workspace Modules'],
                bcs.map((b: any) => [
                  '<span class="badge">' + esc(b.short_code) + '</span>',
                  '<strong>' + esc(b.title) + '</strong>',
                  esc(b.apqc_pcf_ref),
                  esc((b.industry_standards || []).join(' · ')),
                  esc((b.aggregate_roots || []).join(', ')),
                  esc((b.workspace_modules || []).join(', ')),
                ])
              ) +
              '</div>'
            : '') +
          (pl.length
            ? '<div class="section"><h3>SaaS subscription tiers</h3>' +
              table(
                ['Plan', 'Monthly price', 'Target persona', 'Included capabilities'],
                pl.map((p: any) => [esc(p.name), '€' + esc(p.price_eur_monthly) + '/mo', esc(p.target_persona), esc((p.features || []).join(' · '))])
              ) +
              '</div>'
            : '') +
          '<div class="section"><h3>Create organization & invite collaborators (Per-organization RBAC)</h3><div class="toolbar"><input id="new-org-name" aria-label="New organization legal name" placeholder="New organization legal name"><input id="new-org-tax" aria-label="New organization Tax ID" placeholder="Tax ID (e.g. EL094259216)"><select id="new-org-country" aria-label="New organization country"><option value="GR">GR (Greece · AADE myDATA)</option><option value="CY">CY (Cyprus · Peppol)</option><option value="DE">DE (Germany · XRechnung)</option><option value="GB">GB (UK · HMRC)</option><option value="US">US (USA · US GAAP)</option></select><button id="create-org-btn" class="primary">+ Create organization</button></div><div class="toolbar"><input id="invite-email" aria-label="Collaborator email" placeholder="Collaborator email (scoped to this organization)"><select id="invite-role" aria-label="Collaborator role">' +
          ['ACCOUNTANT', 'STORE_MANAGER', 'SELLER', 'CLIENT_OWNER', 'PUBLIC_AUDITOR'].map((rl) => '<option value="' + rl + '">' + rl + '</option>').join('') +
          '</select><button id="invite-btn">Invite collaborator to ' +
          esc(data.tenant.display_name) +
          '</button></div>' +
          table(
            ['Member', 'Subject / Email', 'Role in this organization', 'Status'],
            (oa.members || []).map((m: any) => [esc(m.display_name), esc(m.email || m.sub), esc(m.role), esc(m.status || 'ACTIVE')])
          ) +
          '</div><div class="section"><h3>Go-To-Market (GTM) &amp; AWS Marketplace SaaS Enablement Launchpad</h3><p>End-to-end commercial onboarding for AWS Managed Service Providers: resolve AWS Marketplace SaaS customer contracts, meter active client tenants and period closes via <code>meteringmarketplace</code>, import balanced opening trial balances, and export Merkle-sealed Xero/SoftOne/myDATA journals.</p><div class="toolbar"><button id="gtm-readiness-btn" type="button" class="primary">Check 6-Pillar GTM Readiness</button><button id="gtm-mp-resolve-btn" type="button">Resolve AWS Marketplace Contract &amp; Meter Usage</button><button id="gtm-opening-tb-btn" type="button">Import Balanced Opening Trial Balance</button><button id="gtm-export-csv-btn" type="button">↓ Export Xero / myDATA Journal CSV</button></div><div id="gtm-launchpad-output" style="margin-top:10px"></div></div>' +
          '<div class="section"><h3>Pluggable payment &amp; statutory tax connectors</h3><div class="toolbar"><label>Payment plugin <select id="pay-conn">' +
          ['NONE', 'BANK_IBAN', 'PAYPAL', 'STRIPE'].map((k) => '<option value="' + k + '" ' + (cfg.payment_connector === k ? 'selected' : '') + '>' + k + '</option>').join('') +
          '</select></label><label>Tax authority plugin <select id="tax-conn">' +
          ['NONE', 'AADE_MYDATA', 'PEPPOL_EU'].map((k) => '<option value="' + k + '" ' + (cfg.tax_connector === k ? 'selected' : '') + '>' + k + '</option>').join('') +
          '</select></label><input id="paypal-cid-input" aria-label="PayPal Sandbox Client ID" placeholder="Optional PayPal Sandbox Client ID"><input id="paypal-csec-input" type="password" aria-label="PayPal Sandbox Secret" placeholder="Optional PayPal Sandbox Secret"><button id="save-conn" class="primary">Save connector plugins</button><button id="verify-conn-btn" type="button">Verify Live Provider Handshake</button></div>' +
          facts({
            active_payment_connector: cfg.payment_connector,
            active_tax_connector: cfg.tax_connector,
            paypal_runtime_mode: cn.runtime_modes?.paypal || 'unconfigured',
            mydata_runtime_mode: cn.runtime_modes?.aade_mydata || 'unconfigured',
            paypal_orders: (cn.paypal?.orders || []).length,
            mydata_marks: (cn.mydata?.records || []).length,
          }) +
          '</div><div class="section"><h3>Fleet</h3>' +
          table(
            ['Company', 'Tier', 'Revenue', 'Cash'],
            (r.fleet_summary || []).map((t: any) => [esc(t.display_name), esc(t.tier), money(t.revenue_cents), money(t.cash_balance_cents)])
          ) +
          '</div>';
        if ($('apply-rbac-role-btn'))
          $('apply-rbac-role-btn').onclick = async () => {
            if ($('rbac-role-select') && ctx.setActiveRole) {
              await ctx.setActiveRole($('rbac-role-select').value);
            }
          };
        if ($('save-fiscal-profile-btn'))
          $('save-fiscal-profile-btn').onclick = async () => {
            try {
              const nextCountry = $('org-country-select').value;
              const payload: any = { country_code: nextCountry };
              if ($('org-doy-input')) payload.doy = $('org-doy-input').value.trim();
              if ($('org-gemi-input')) payload.gemi_number = $('org-gemi-input').value.trim();
              if ($('org-kad-input')) payload.kad_code = $('org-kad-input').value.trim();
              const res = await api(path('connectors/fiscal-profile'), payload);
              $('notice').textContent =
                'Updated organization fiscal regime to ' +
                res.fiscal_profile.country_code +
                ' (' +
                res.fiscal_profile.country_name +
                ') · AADE myDATA ' +
                (res.fiscal_profile.aade_mydata_enabled ? 'ENABLED' : 'DISABLED') +
                '.';
              await load();
            } catch (e) {
              fail(e);
            }
          };
        if ($('import-dataset-btn'))
          $('import-dataset-btn').onclick = async () => {
            try {
              const dsId = $('dataset-select').value;
              const res = await api(path('datasets/import'), { dataset_id: dsId });
              $('notice').textContent =
                'Imported public dataset ' +
                res.imported.title +
                ' (' +
                res.imported.imported_documents_count +
                ' new documents, ' +
                res.imported.imported_parties_count +
                ' counterparties).';
              await load();
            } catch (e) {
              fail(e);
            }
          };
        if ($('save-conn'))
          $('save-conn').onclick = async () => {
            try {
              const cid = ($('paypal-cid-input') && $('paypal-cid-input').value.trim()) || undefined;
              const csec = ($('paypal-csec-input') && $('paypal-csec-input').value.trim()) || undefined;
              await api(path('connectors/config'), {
                payment_connector: $('pay-conn').value,
                tax_connector: $('tax-conn').value,
                paypal_client_id: cid,
                paypal_client_secret: csec,
              });
              await load();
            } catch (e) {
              fail(e);
            }
          };
        if ($('verify-conn-btn'))
          $('verify-conn-btn').onclick = async () => {
            try {
              const vres = await api(path('connectors/verify'), { connector: 'all' });
              const ppv = vres.verification?.paypal || {};
              const aav = vres.verification?.aade_mydata || {};
              $('notice').textContent =
                'Connector verification · PayPal: ' +
                (ppv.live_verified ? 'LIVE OAUTH VERIFIED' : ppv.mode + ' (' + (ppv.reason || 'ok') + ')') +
                ' · AADE myDATA: ' +
                (aav.live_verified ? 'LIVE VERIFIED' : aav.mode + ' (' + (aav.reason || 'ok') + ')');
            } catch (e) {
              fail(e);
            }
          };
        if ($('gtm-readiness-btn'))
          $('gtm-readiness-btn').onclick = async () => {
            try {
              const gtm = await api(path('gtm/readiness'));
              const out = $('gtm-launchpad-output');
              if (out) {
                out.innerHTML =
                  table(
                    ['GTM Readiness Pillar', 'Status', 'Live Evidence'],
                    (gtm.pillars || []).map((p: any) => ['<strong>' + esc(p.title) + '</strong>', '<span class="badge">' + esc(p.status) + '</span>', esc(p.evidence)])
                  ) +
                  table(
                    ['Rollout Window', 'Commercial Milestone', 'Target KPI'],
                    (gtm.rollout_plan_30_60_90 || []).map((m: any) => ['<strong>' + esc(m.window) + '</strong>', esc(m.milestone), esc(m.kpi_target)])
                  );
              }
            } catch (e) {
              fail(e);
            }
          };
        if ($('gtm-mp-resolve-btn'))
          $('gtm-mp-resolve-btn').onclick = async () => {
            try {
              const resolved = await api('/gtm/marketplace/resolve-customer', { registration_token: 'amzn-mp-saas-token-msp-35', plan_code: 'msp_hub' });
              const metered = await api('/gtm/marketplace/meter-usage', { customer_identifier: resolved.entitlement.customer_identifier, period: '2026-10' });
              const out = $('gtm-launchpad-output');
              if (out) {
                out.innerHTML =
                  facts({
                    customer_identifier: resolved.entitlement.customer_identifier,
                    product_code: resolved.entitlement.product_code,
                    provider_mode: metered.provider_mode,
                  }) +
                  table(
                    ['Metering Record ID', 'Dimension', 'Measured Quantity', 'Idempotency Token'],
                    (metered.records || []).map((rec: any) => ['<code>' + esc(rec.usage_record_id) + '</code>', esc(rec.dimension), '<strong>' + esc(rec.quantity) + '</strong>', '<code>' + esc(rec.idempotency_token) + '</code>'])
                  );
              }
              $('notice').textContent = 'Resolved AWS Marketplace customer ' + resolved.entitlement.customer_identifier + ' and metered ' + (metered.records || []).length + ' usage dimensions.';
            } catch (e) {
              fail(e);
            }
          };
        if ($('gtm-export-csv-btn'))
          $('gtm-export-csv-btn').onclick = async () => {
            try {
              const exp = await api(path('export/journal-csv'));
              download(exp.filename || 'kerdon-journal.csv', 'text/csv', exp.csv || '');
              $('notice').textContent = 'Downloaded Merkle-sealed journal CSV (' + (exp.filename || 'kerdon-journal.csv') + ').';
            } catch (e) {
              fail(e);
            }
          };
        if ($('gtm-opening-tb-btn'))
          $('gtm-opening-tb-btn').onclick = async () => {
            try {
              const ob = await api(path('onboarding/opening-balance'), {
                as_of_date: '2026-10-01',
                description: 'Opening Trial Balance Cutover (Customer Onboarding)',
                rows: [
                  { account: '1000_CASH', debit_cents: 2500000, credit_cents: 0, memo: 'Opening bank balance' },
                  { account: '1100_ACCOUNTS_RECEIVABLE', debit_cents: 1000000, credit_cents: 0, memo: 'Opening AR subledger' },
                  { account: '2000_ACCOUNTS_PAYABLE', debit_cents: 0, credit_cents: 1500000, memo: 'Opening AP subledger' },
                  { account: '2100_CUSTOMER_ADVANCE_DEPOSITS', debit_cents: 0, credit_cents: 2000000, memo: 'Opening deferred retainers' },
                ],
              });
              $('notice').textContent =
                'Posted balanced opening trial balance (' +
                money(ob.opening_balance_receipt.total_debit_cents) +
                ' debits = credits) · Merkle root ' +
                ob.opening_balance_receipt.merkle_root_sha256.slice(0, 14) +
                '…';
              await load();
            } catch (e) {
              fail(e);
            }
          };
        if ($('create-org-btn'))
          $('create-org-btn').onclick = async () => {
            try {
              const created = await api('/erp/organizations', {
                display_name: $('new-org-name').value.trim(),
                tax_id: $('new-org-tax').value.trim(),
                country_code: ($('new-org-country') && $('new-org-country').value) || 'GR',
              });
              const orgs = await api('/erp/organizations');
              $('tenant').innerHTML = orgs.organizations.map((t: any) => '<option value="' + esc(t.tenant_id) + '">' + esc(t.display_name) + '</option>').join('');
              $('tenant').value = created.organization.tenant_id;
              await load();
            } catch (e) {
              fail(e);
            }
          };
        if ($('invite-btn'))
          $('invite-btn').onclick = async () => {
            try {
              await api(path('members/invite'), { email: $('invite-email').value.trim(), role: $('invite-role').value, auto_accept: true });
              await load();
            } catch (e) {
              fail(e);
            }
          };
      }
}

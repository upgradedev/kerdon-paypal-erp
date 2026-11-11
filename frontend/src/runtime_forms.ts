export function cents(raw: unknown) {
    const s = String(raw).trim();
    if (!/^\d+(\.\d{1,2})?$/.test(s)) throw Error('Enter a non-negative amount with at most two decimal places');
    const [whole, fraction = ''] = s.split('.');
    const value = Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
    if (!Number.isSafeInteger(value)) throw Error('Amount too large');
    return value;
  }

export function download(name: string, type: string, text: string) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

export function csv(records: any[]) {
    const keys = [...new Set(records.flatMap((r) => Object.keys(r)))].filter((k) => !['lines', 'line_items', 'allocations', 'historical_invoice_cents'].includes(k));
    const cell = (v: unknown) => '"' + String(v ?? '').replace(/^([=+@-])/, '\t$1').replaceAll('"', '""') + '"';
    return [
      keys.map(cell).join(','),
      ...records.map((r) => keys.map((k) => cell(typeof r[k] === 'object' ? JSON.stringify(r[k]) : r[k])).join(',')),
    ].join('\r\n');
  }

export function createFormHandlers(ctx: any) {
  let draft: any = null;
  let formTab = 'General';

  function newDraft() {
    const { $, fp, isGreekOrg, t, tid, modules, module } = ctx;
    const defaultVat = String((fp().statutory_vat_rates || [0, 6, 13, 24]).slice(-1)[0] || 24);
    draft = {
      module,
      company: tid(),
      document_id: 'doc-' + crypto.randomUUID(),
      counterparty_id: '',
      invoice_number: '',
      issued_date: new Date().toISOString().slice(0, 10),
      due_date: new Date().toISOString().slice(0, 10),
      description: '',
      lines: [{ description: '', net: '', vat: defaultVat, measurement_unit: '1' }],
      fields: {
        country_code: fp().country_code || 'GR',
        doy: isGreekOrg() ? t('Athens Corporate Tax Office (KEFODE Attikis)', 'ΔΟΥ ΦΑΕ ΑΘΗΝΩΝ') : '',
        gemi_number: '',
        city: isGreekOrg() ? t('Athens', 'Αθήνα') : '',
        postal_code: isGreekOrg() ? '11526' : '',
        invoice_type: module === 'sales' ? '2.1' : '1.1',
        series: module === 'sales' ? 'A' : 'PUR',
        aa: '101',
        payment_method_code: '1',
        withheld_tax_pct: '0',
        vat_exemption_category: '',
      },
      confirmed: false,
    };
    formTab = 'General';
    $('draft-title').textContent = 'New ' + modules[module].toLowerCase() + ' · Draft';
    $('draft-error').textContent = '';
    renderForm();
    $('draft-dialog').showModal();
  }

  function capture() {
    const { $ } = ctx;
    document.querySelectorAll('[data-field]').forEach((e: any) => {
      if (e.dataset.field in draft) draft[e.dataset.field] = e.value;
      else draft.fields[e.dataset.field] = e.value;
    });
    document.querySelectorAll('[data-line]').forEach((e: any) => {
      draft.lines[Number(e.dataset.line)][e.dataset.key] = e.value;
    });
    if ($('confirm-post')) draft.confirmed = $('confirm-post').checked;
  }

  function totals() {
    if (!draft.lines.length) throw Error('Add a line');
    const parsed = draft.lines.map((l: any) => {
      const n = cents(l.net);
      const r = Number(l.vat);
      const v = Math.floor((n * r) / 100);
      return {
        description: l.description || 'Line item',
        quantity: 1,
        measurement_unit: Number(l.measurement_unit || 1),
        net_cents: n,
        vat_rate_pct: r,
        vat_cents: v,
        gross_cents: n + v,
      };
    });
    const net = parsed.reduce((s: number, l: any) => s + l.net_cents, 0);
    const vat = parsed.reduce((s: number, l: any) => s + l.vat_cents, 0);
    if (net <= 0) throw Error('Net amount must be positive');
    return { net, rate: Number(draft.lines[0].vat), vat, lines: parsed };
  }

  function renderForm() {
    const { $, esc, facts, fp, isGreekOrg, t, api, path, data } = ctx;
    const invoice = ['sales', 'purchases'].includes(draft.module);
    const isParty = ['customers', 'suppliers'].includes(draft.module);
    const canAi = ['sales', 'purchases', 'expenses'].includes(draft.module);
    const tabs = ['General', invoice ? 'Lines & taxes' : isParty ? 'Commercial' : 'Allocations', 'Review'];
    $('draft-tabs').innerHTML = tabs.map((t) => '<button type="button" data-form-tab="' + t + '" class="' + (formTab === t ? 'active' : '') + '">' + t + '</button>').join('');
    document.querySelectorAll('[data-form-tab]').forEach((b: any) => {
      b.onclick = () => {
        capture();
        formTab = b.dataset.formTab;
        renderForm();
      };
    });
    const field = (k: string, label: string, type = 'text') =>
      '<label>' + label + '<input data-field="' + k + '" type="' + type + '" value="' + esc(draft[k] || draft.fields[k] || '') + '"></label>';
    const body = $('draft-body');
    if (formTab === 'General') {
      if (isParty) {
        body.innerHTML =
          '<div class="form-grid">' +
          field('legal_name', 'Legal name') +
          field('tax_id', isGreekOrg() ? t('Tax ID (AFM · 9 digits Modulo-11)', 'Tax ID (ΑΦΜ · 9 digits Modulo-11)') : 'Tax ID / VAT Number') +
          field('country_code', 'Country Code (ISO-2, e.g. GR, CY, DE)') +
          (isGreekOrg() ? field('doy', t('Tax Office (DOY)', 'ΔΟΥ (Greek Tax Office)')) + field('gemi_number', t('GEMI Number (Commercial Registry)', 'Αρ. ΓΕΜΗ (Commercial Registry)')) : '') +
          field('email', 'Email', 'email') +
          field('phone', 'Phone') +
          field('address', 'Street Address') +
          field('city', 'City') +
          field('postal_code', 'Postal Code') +
          '</div>';
      } else {
        const options = data.records[draft.module === 'sales' || draft.module === 'receipts' ? 'customers' : 'suppliers'];
        body.innerHTML =
          (canAi
            ? '<div class="toolbar" style="margin-bottom:10px"><input id="ai-raw-text" aria-label="AI document text" placeholder="Paste email/PDF text or click AI Auto-Fill for sample extraction"><button type="button" id="ai-autofill-btn">✨ AI Auto-Fill</button></div>'
            : '') +
          '<div class="form-grid"><label>Counterparty<select data-field="counterparty_id"><option value="">Select an account</option>' +
          options.map((r: any) => '<option value="' + esc(r.id) + '" ' + (r.id === draft.counterparty_id ? 'selected' : '') + '>' + esc(r.legal_name) + '</option>').join('') +
          '</select></label>' +
          field('invoice_number', 'Document number') +
          field('issued_date', 'Document date', 'date') +
          field('due_date', 'Due date', 'date') +
          field('description', 'Description') +
          (invoice ? '' : field('amount', 'Amount (EUR)', 'number')) +
          (isGreekOrg() && (invoice || draft.module === 'expenses')
            ? '<label>' + t('AADE Invoice Type', 'AADE Invoice Type (Είδος Παραστατικού)') + '<select data-field="invoice_type">' +
              [
                ['1.1', t('1.1 · Sales / Purchase Goods Invoice', '1.1 · Τιμολόγιο Πώλησης (Sales / Purchase Goods)')],
                ['2.1', t('2.1 · Service Rendered Invoice (B2B)', '2.1 · Τιμολόγιο Παροχής Υπηρεσιών (Services Invoice)')],
                ['1.2', t('1.2 · Intra-EU Sales Invoice', '1.2 · Τιμολόγιο Πώλησης Ενδοκοινοτικές (Intra-EU)')],
                ['1.3', t('1.3 · Third-Country Export Invoice', '1.3 · Τιμολόγιο Πώλησης Τρίτες Χώρες (Third Country)')],
                ['5.1', t('5.1 · Correlated Credit Note', '5.1 · Πιστωτικό Τιμολόγιο Συσχετιζόμενο (Correlated Credit Note)')],
                ['5.2', t('5.2 · Non-Correlated Credit Note', '5.2 · Πιστωτικό Τιμολόγιο Μη Συσχετιζόμενο')],
                ['11.1', t('11.1 · Retail Sales Receipt (ALP)', '11.1 · ΑΛΠ (Retail Sales Receipt)')],
                ['11.2', t('11.2 · Retail Services Receipt (APY)', '11.2 · ΑΠΥ (Retail Services Receipt)')],
                ['13.1', t('13.1 · Retail Purchase / Expense Receipt', '13.1 · Έξοδα - Αγορές Λιανικών Συναλλαγών')],
                ['14.1', t('14.1 · Intra-EU Acquisition Invoice', '14.1 · Τιμολόγιο Ενδοκοινοτικών Αποκτήσεων')],
              ]
                .map(([k, lbl]) => '<option value="' + k + '" ' + (draft.fields.invoice_type === k ? 'selected' : '') + '>' + esc(lbl) + '</option>')
                .join('') +
              '</select></label>' +
              field('series', t('AADE Series', 'AADE Series (Σειρά)')) +
              field('aa', t('AADE Sequential Number (AA)', 'AADE Sequential Number (ΑΑ)')) +
              '<label>' + t('AADE Payment Method', 'AADE Payment Method (Τρόπος Πληρωμής)') + '<select data-field="payment_method_code">' +
              [
                ['1', t('1 · Domestic Business Bank Account (IBAN)', '1 · Επαγγελματικός Λογαριασμός Πληρωμών Ημεδαπής (IBAN)')],
                ['5', t('5 · On Credit / Open Account', '5 · Επί Πιστώσει (On Credit)')],
                ['6', '6 · Web Banking'],
                ['7', '7 · POS / e-POS'],
                ['8', '8 · IRIS Instant Payments'],
                ['2', t('2 · Foreign Business Bank Account', '2 · Επαγγελματικός Λογαριασμός Αλλοδαπής')],
                ['3', t('3 · Cash (<= EUR 500 B2B Limit)', '3 · Μετρητά (Cash <= EUR 500 B2B Limit)')],
              ]
                .map(([k, lbl]) => '<option value="' + k + '" ' + (draft.fields.payment_method_code === k ? 'selected' : '') + '>' + esc(lbl) + '</option>')
                .join('') +
              '</select></label>' +
              '<label>' + t('Withheld Tax (20% WHT)', 'Withheld Tax (Παρακράτηση ΦΕΕ 20%)') + '<select data-field="withheld_tax_pct">' +
              [
                ['0', '0% · No Withholding Tax'],
                ['20', t('20% · Consulting / Freelance Withholding Tax (> EUR 300)', '20% · Παρακράτηση ΦΕΕ (Ελεύθεροι Επαγγελματίες / Συμβουλευτικές)')],
              ]
                .map(([k, lbl]) => '<option value="' + k + '" ' + (draft.fields.withheld_tax_pct === k ? 'selected' : '') + '>' + esc(lbl) + '</option>')
                .join('') +
              '</select></label>'
            : '') +
          '</div>';
        if ($('ai-autofill-btn'))
          $('ai-autofill-btn').onclick = async () => {
            capture();
            const targetDraft = draft;
            const btn = $('ai-autofill-btn') as HTMLButtonElement | null;
            if (btn) btn.disabled = true;
            try {
              const sample =
                targetDraft.module === 'sales'
                  ? 'Invoice INV-AI-2026-901\nDate: 2026-10-29 Due: 2026-11-29\nManaged Cloud Services: EUR 1500.00 (24% VAT)\nTechnical Training Workshop: EUR 400.00 (13% VAT)'
                  : 'Invoice BILL-AI-2026-404\nDate: 2026-10-28 Due: 2026-11-28\nFiber Optic Backhaul Lease: EUR 850.00 (24% VAT)\nUPS Battery Pack: EUR 250.00 (13% VAT)';
              const raw = $('ai-raw-text').value.trim() || sample;
              const res = await api(path('ai/extract-document'), { raw_text: raw, module: targetDraft.module });
              if (draft !== targetDraft || !$('draft-dialog')?.open) return;
              const ex = res.extracted_draft;
              targetDraft.counterparty_id = ex.counterparty_id || targetDraft.counterparty_id;
              targetDraft.invoice_number = ex.invoice_number || targetDraft.invoice_number;
              targetDraft.issued_date = ex.issued_date || targetDraft.issued_date;
              targetDraft.due_date = ex.due_date || targetDraft.due_date;
              targetDraft.description = ex.description || targetDraft.description;
              if (ex.lines && ex.lines.length) {
                targetDraft.lines = ex.lines.map((l: any) => ({ description: l.description, net: (l.net_cents / 100).toFixed(2), vat: String(l.vat_rate_pct), measurement_unit: '1' }));
                targetDraft.fields.amount = (ex.total_net_cents / 100).toFixed(2);
              }
              renderForm();
            } catch (e: any) {
              if (draft === targetDraft && $('draft-error')) $('draft-error').textContent = e.message;
            } finally {
              if (btn) btn.disabled = false;
            }
          };
      }
    } else if (formTab === 'Lines & taxes') {
      const vatRates = fp().statutory_vat_rates || [0, 6, 13, 24];
      body.innerHTML =
        draft.lines
          .map(
            (l: any, i: number) =>
              '<div class="line-grid"><input aria-label="Line ' +
              (i + 1) +
              ' description" data-line="' +
              i +
              '" data-key="description" value="' +
              esc(l.description) +
              '" placeholder="Description"><input aria-label="Line ' +
              (i + 1) +
              ' net amount" type="number" step="0.01" min="0" data-line="' +
              i +
              '" data-key="net" value="' +
              esc(l.net) +
              '" placeholder="Net EUR"><select aria-label="Line ' +
              (i + 1) +
              ' VAT" data-line="' +
              i +
              '" data-key="vat">' +
              vatRates.map((v: number) => '<option value="' + v + '" ' + (Number(l.vat) === v ? 'selected' : '') + '>' + v + '% VAT</option>').join('') +
              '</select><button type="button" data-remove="' +
              i +
              '" aria-label="Remove line ' +
              (i + 1) +
              '">×</button></div>'
          )
          .join('') + '<button type="button" id="add-line">+ Add line</button>';
      $('add-line').onclick = () => {
        capture();
        draft.lines.push({ description: '', net: '', vat: String(vatRates.slice(-1)[0] || 24), measurement_unit: '1' });
        renderForm();
      };
      document.querySelectorAll('[data-remove]').forEach((b: any) => {
        b.onclick = () => {
          capture();
          if (draft.lines.length > 1) draft.lines.splice(Number(b.dataset.remove), 1);
          renderForm();
        };
      });
    } else if (formTab === 'Commercial') {
      body.innerHTML =
        '<div class="form-grid">' +
        field('payment_terms_days', 'Payment terms (days)', 'number') +
        field('credit_limit', 'Credit limit (EUR)', 'number') +
        field('iban', 'IBAN') +
        field('category', 'Category') +
        '</div><p>Commercial terms are validated and versioned on submit.</p>';
    } else if (formTab === 'Allocations') {
      body.innerHTML =
        '<div class="form-grid">' +
        field('reference', 'Invoice reference') +
        field('bank_reference', 'Bank reference') +
        field('notes', 'Notes') +
        '</div><p>Allocations update register paid amounts and post balanced GL entries. Journal entries do not execute bank wire transfers.</p>';
    } else {
      let t: any = null;
      try {
        t = invoice ? totals() : null;
      } catch {}
      body.innerHTML =
        facts({
          company: draft.company,
          organization_country: fp().country_code || 'GR',
          document: draft.document_id,
          counterparty: draft.counterparty_id || draft.fields.legal_name || 'Not selected',
          aade_invoice_type: isGreekOrg() && invoice ? draft.fields.invoice_type : 'N/A',
          net_cents: t?.net,
          vat_cents: t?.vat,
          gross_cents: t ? t.net + t.vat : 0,
          status: 'Draft - not posted',
        }) +
        '<p>' +
        (invoice
          ? 'Line items and per-line VAT rates are validated and persisted to the register and ledger.'
          : 'Check confirmation below to enable governed backend submission, or download a non-posted draft.') +
        '</p><label class="check"><input id="confirm-post" type="checkbox" ' +
        (draft.confirmed ? 'checked' : '') +
        '><span>I reviewed this record and explicitly approve submitting it to the backend. This does not execute a bank payment.</span></label>';
      if ($('confirm-post'))
        $('confirm-post').onchange = (e: any) => {
          draft.confirmed = e.target.checked;
          $('submit-document').disabled = invoice ? formTab !== 'Review' || !data.capabilities.invoice_submission : !draft.confirmed || formTab !== 'Review';
        };
    }
    $('submit-document').disabled = invoice ? formTab !== 'Review' || !data.capabilities.invoice_submission : !draft.confirmed || formTab !== 'Review';
    $('submit-document').textContent = invoice ? 'Submit to existing backend' : draft.confirmed ? 'Submit governed record' : 'Confirm review to submit';
  }

  function openCmd() {
    const { $, esc, go, modules } = ctx;
    if (!$('cmd-dialog')) return;
    const renderCmd = (q: string) => {
      const f = String(q || '').toLowerCase();
      $('cmd-list').innerHTML = Object.entries(modules as Record<string, string>)
        .filter(([k, v]) => !f || k.includes(f) || v.toLowerCase().includes(f))
        .map(([k, v]) => '<button type="button" class="cmd-item" data-cmd-go="' + k + '"><span>' + esc(v) + '</span><small class="badge">Module</small></button>')
        .join('');
      document.querySelectorAll('[data-cmd-go]').forEach((b: any) => {
        b.onclick = () => {
          $('cmd-dialog').close();
          go(b.dataset.cmdGo);
        };
      });
    };
    $('cmd-input').value = '';
    renderCmd('');
    $('cmd-input').oninput = (e: any) => renderCmd(e.target.value);
    $('cmd-dialog').showModal();
  }

  function bindFormEvents() {
    const { $, api, path, tid, fp, load, go } = ctx;
    $('draft-form').onsubmit = async (e: Event) => {
      const data = ctx.data;
    e.preventDefault();
    capture();
    try {
      if (draft.company !== tid()) throw Error('Company changed; reopen the form');
      if (!draft.confirmed) throw Error('Explicitly approve the reviewed record');
      const invoice = ['sales', 'purchases'].includes(draft.module);
      const isParty = ['customers', 'suppliers'].includes(draft.module);
      $('submit-document').disabled = true;
      if (invoice) {
        if (!draft.counterparty_id || !draft.invoice_number.trim()) throw Error('Select a counterparty and enter a document number');
        const t = totals();
        const p = data.records[draft.module === 'sales' ? 'customers' : 'suppliers'].find((r: any) => r.id === draft.counterparty_id);
        if (!p) throw Error('Counterparty not in this company');
        const result = await api(path('invoices'), {
          document_id: draft.document_id,
          direction: draft.module === 'sales' ? 'SALES_REVENUE' : 'PURCHASE_EXPENSE',
          counterparty_id: p.id,
          counterparty_name: p.legal_name,
          counterparty_tax_id: p.tax_id,
          net_cents: t.net,
          vat_rate_pct: t.rate,
          lines: t.lines,
          invoice_number: draft.invoice_number,
          issued_date: draft.issued_date,
          due_date: draft.due_date,
          description: draft.description || draft.lines.map((l: any) => l.description).join('; '),
          invoice_type: draft.fields.invoice_type || (draft.module === 'sales' ? '2.1' : '1.1'),
          series: draft.fields.series || (draft.module === 'sales' ? 'A' : 'PUR'),
          aa: draft.fields.aa || '101',
          payment_method_code: Number(draft.fields.payment_method_code || 3),
          withheld_tax_pct: Number(draft.fields.withheld_tax_pct || 0),
          vat_exemption_category: draft.fields.vat_exemption_category || '',
        });
        const dest = draft.module;
        $('draft-dialog').close();
        await load();
        go(dest, result.document.document_id);
      } else if (isParty) {
        const result = await api(path('parties'), {
          kind: draft.module === 'customers' ? 'customer' : 'supplier',
          legal_name: draft.fields.legal_name,
          tax_id: draft.fields.tax_id,
          country_code: draft.fields.country_code || fp().country_code || 'GR',
          doy: draft.fields.doy || '',
          gemi_number: draft.fields.gemi_number || '',
          city: draft.fields.city || '',
          postal_code: draft.fields.postal_code || '',
          email: draft.fields.email,
          phone: draft.fields.phone,
          address: draft.fields.address,
          payment_terms_days: Number(draft.fields.payment_terms_days || 30),
          credit_limit_cents: draft.fields.credit_limit ? cents(draft.fields.credit_limit) : 5000000,
          iban: draft.fields.iban,
          category: draft.fields.category,
        });
        const dest = draft.module;
        $('draft-dialog').close();
        await load();
        go(dest, result.party.id);
      } else if (draft.module === 'expenses') {
        const amt = cents(draft.fields.amount || '0');
        const result = await api(path('expenses'), {
          document_id: draft.document_id,
          counterparty_id: draft.counterparty_id,
          invoice_number: draft.invoice_number,
          issued_date: draft.issued_date,
          due_date: draft.due_date,
          description: draft.description,
          net_cents: amt,
          vat_rate_pct: 24,
          invoice_type: draft.fields.invoice_type || '2.1',
          series: draft.fields.series || 'EXP',
          aa: draft.fields.aa || '101',
          payment_method_code: Number(draft.fields.payment_method_code || 3),
          withheld_tax_pct: Number(draft.fields.withheld_tax_pct || 0),
        });
        $('draft-dialog').close();
        await load();
        go('expenses', result.event.event_id);
      } else {
        const amt = cents(draft.fields.amount || '0');
        const endpoint = draft.module === 'receipts' ? 'receipts' : 'payments';
        const ref = draft.fields.reference?.trim();
        const allocs = ref ? [{ document_id: ref, allocated_cents: amt }] : [];
        const result = await api(path(endpoint), {
          settlement_id: draft.document_id,
          counterparty_id: draft.counterparty_id,
          posted_date: draft.issued_date,
          gross_cash_cents: amt,
          allocations: allocs,
          description: draft.description,
        });
        $('draft-dialog').close();
        await load();
        go(draft.module, result.settlement.ledger_event_id);
      }
    } catch (err: any) {
      $('draft-error').textContent = err.message;
      $('submit-document').disabled = false;
    }
    };
    $('save-draft').onclick = async () => {
      const data = ctx.data;
    capture();
    try {
      if (data?.capabilities?.invoice_submission) {
        await api(path('drafts'), {
          draft_id: draft.document_id,
          module: draft.module,
          counterparty_id: draft.counterparty_id,
          invoice_number: draft.invoice_number,
          issued_date: draft.issued_date,
          due_date: draft.due_date,
          description: draft.description,
        });
      }
    } catch {}
    download(
      'kerdon-draft-' + draft.document_id + '.json',
      'application/json',
      JSON.stringify({ ...draft, status: 'DRAFT_NOT_POSTED', durable: Boolean(data?.capabilities?.invoice_submission) }, null, 2)
    );
    };
    $('close-dialog').onclick = () => $('draft-dialog').close();
    if ($('cmd-btn')) $('cmd-btn').onclick = openCmd;
    if ($('close-cmd')) $('close-cmd').onclick = () => $('cmd-dialog').close();
    window.addEventListener('keydown', (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        openCmd();
      }
    });
  }

  return { newDraft, openCmd, bindFormEvents };
}

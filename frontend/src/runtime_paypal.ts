let lastPayPalAgentResult: any = null;

export function renderPayPalCommerceSection(ctx: any): string {
  const { esc, money, source, table, link, data, isPayPalActive } = ctx;
  if (!isPayPalActive()) return '';
  const cn = data.connectors || {};
  const rm = cn.runtime_modes || {};
  const pp = cn.paypal || {};
  const isLive = Boolean(rm.paypal_credentials_present);
  const modeBadge = isLive ? 'LIVE SANDBOX (api-m.sandbox.paypal.com)' : 'SIMULATED FALLBACK';
  const pendingOrders: any[] = pp.pending_orders || [];
  const settledOrders: any[] = pp.orders || [];
  const subs: any[] = pp.subscriptions || [];
  const webhooks: any[] = pp.webhooks || [];
  const identities: any[] = pp.identities || [];
  const payouts: any[] = pp.payouts || [];
  const disputes: any[] = pp.disputes || [];
  const oidcUrl = pp.oidc_start?.authorize_url || '';

  const agentBox = lastPayPalAgentResult
    ? '<div id="paypal-agent-output" style="margin-top:10px;padding:12px;border-radius:8px;border:1px solid var(--border);background:var(--surface-muted)">' +
      '<div><strong>Engine:</strong> <code>' +
      esc(lastPayPalAgentResult.engine || 'strands-bedrock-tools') +
      '</code> | <strong>Mode:</strong> <span class="badge">' +
      esc(lastPayPalAgentResult.provider_mode || rm.paypal || '') +
      '</span> | <strong>Tools Executed:</strong> ' +
      esc(lastPayPalAgentResult.tools_executed_count || 0) +
      '</div><p style="margin:8px 0">' +
      esc(lastPayPalAgentResult.narrative || '') +
      '</p>' +
      table(
        ['Executed Strands @tool', 'Live PayPal Resource / Diagnostic Summary'],
        (lastPayPalAgentResult.executed_tools || []).map((it: any) => {
          const res = it.result || {};
          const summary =
            res.order_id
              ? 'Order ' + res.order_id + ' [' + (res.status || res.live_status || 'CREATED') + ']'
              : res.subscription_id
                ? 'Product ' + res.product_id + ' -> Plan ' + res.plan_id + ' -> Sub ' + res.subscription_id
                : res.webhook_id
                  ? 'Webhook ' + res.webhook_id + ' (' + (res.url || '') + ')'
                  : res.payout_batch_id
                    ? 'Payout Batch ' + res.payout_batch_id + ' [' + (res.status || '') + ']'
                    : res.issue
                      ? 'Fail-Closed [' + res.issue + '] debug_id=' + (res.debug_id || 'n/a')
                      : res.app_id
                        ? 'OAuth2 App ' + res.app_id + ' (' + (res.scopes_count || 0) + ' scopes)'
                        : JSON.stringify(res).slice(0, 140);
          return ['<code>' + esc(it.tool) + '</code>', esc(summary)];
        })
      ) +
      '</div>'
    : '<div id="paypal-agent-output"></div>';

  return (
    '<div class="section" id="paypal-commerce-console">' +
    '<div class="toolbar" style="justify-content:space-between;flex-wrap:wrap;gap:8px">' +
    '<h3>PayPal Agentic Commerce Hub (Orders v2 · Subscriptions v1 · Payouts v1 · Disputes v1 · OIDC · Strands @tool)</h3>' +
    '<span class="badge">' +
    esc(modeBadge) +
    '</span></div>' +
    '<div class="toolbar" style="flex-wrap:wrap;gap:8px;margin-bottom:12px">' +
    '<button type="button" id="paypal-verify-btn">Verify Live OAuth2 Scopes</button>' +
    '<button type="button" id="paypal-webhook-reg-btn">Register Webhook v1</button>' +
    '<button type="button" id="paypal-sync-disputes-btn">Sync Disputes v1</button>' +
    '<button type="button" id="paypal-payout-btn">Execute Four-Eyes Payout v1</button>' +
    (oidcUrl
      ? '<a class="btn-link" id="paypal-oidc-btn" href="' +
        esc(oidcUrl) +
        '">Log in with PayPal (OIDC) ↗</a>'
      : '') +
    '</div>' +
    (identities.length
      ? '<p><strong>Verified PayPal OIDC Identities:</strong> ' +
        identities
          .map((idObj: any) => '<code>' + esc(idObj.payer_id || 'OIDC') + '</code> (' + esc(idObj.email || idObj.name || 'verified') + ')')
          .join(', ') +
        '</p>'
      : '') +
    (webhooks.length
      ? '<p><strong>Active PayPal Webhooks v1:</strong> ' +
        webhooks.map((w: any) => '<code>' + esc(w.webhook_id) + '</code> -> ' + esc(w.url)).join(' | ') +
        '</p>'
      : '') +
    '<div style="padding:12px;border:1px solid var(--border);border-radius:8px;margin-bottom:14px">' +
    '<strong>Strands Agents SDK + Amazon Bedrock PayPal Copilot (6 Executable @tool Functions)</strong>' +
    '<div class="toolbar" style="margin-top:8px;gap:8px">' +
    '<input id="paypal-agent-input" aria-label="PayPal AI Agent goal" style="flex:1;min-width:240px" value="Inspect Sandbox status, create a live Checkout Order v2 for the next unpaid invoice, provision a SaaS Subscription Plan v1, and diagnose Treasury Payouts">' +
    '<button type="button" id="paypal-agent-run-btn" class="primary">Run PayPal Strands Agent</button>' +
    '</div>' +
    agentBox +
    '</div>' +
    '<div class="toolbar" style="justify-content:space-between;flex-wrap:wrap;gap:8px">' +
    '<strong>1. Checkout Orders v2 &amp; 3-Line Fee GL Reconciliation (1000_CASH + 6200_OPEX = 1100_AR)</strong>' +
    '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
    '<button type="button" id="paypal-create-order-btn" class="primary">+ Create Live Order v2 (Buyer Approval Flow)</button>' +
    '<button type="button" id="paypal-capture-next-btn">Capture Order v2 -> 3-Line GL Split</button>' +
    '</div></div>' +
    (pendingOrders.length
      ? '<div style="margin:10px 0"><strong>Pending Buyer-Approval Orders (v2/checkout/orders):</strong>' +
        table(
          ['PayPal Order ID', 'ERP Document', 'Amount', 'Status', 'Buyer Checkout Link', 'Actions'],
          pendingOrders.map((po: any) => [
            '<code>' + esc(po.order_id) + '</code>',
            source(po.document_id),
            money(po.amount_cents || 0),
            '<span class="badge">' + esc(po.status || 'CREATED') + '</span>',
            po.approval_url
              ? '<a href="' + esc(po.approval_url) + '" target="_blank" rel="noopener noreferrer">Approve on PayPal Sandbox ↗</a>'
              : '-',
            '<button type="button" data-pp-sync-order="' +
              esc(po.order_id) +
              '">Sync Status</button> <button type="button" class="primary" data-pp-cap-order="' +
              esc(po.order_id) +
              '" data-pp-cap-doc="' +
              esc(po.document_id) +
              '">Capture -> GL</button>',
          ])
        ) +
        '</div>'
      : '') +
    table(
      ['Order ID', 'Invoice v2 ID', 'Capture ID', 'ERP Document', 'Gross Captured', 'PayPal Fee (6200)', 'Net Cash (1000)', 'GL Event', 'Status / Fulfillment'],
      settledOrders.map((o: any) => [
        '<code>' + esc(o.order_id) + '</code>',
        '<code>' + esc(o.paypal_invoice_id) + '</code>',
        '<code>' + esc(o.capture_id) + '</code>',
        source(o.document_id),
        money(o.gross_cents || 0),
        money(o.paypal_fee_cents || 0),
        '<strong>' + money(o.net_settled_cents || 0) + '</strong>',
        o.journal_event_id ? link('accounting', o.journal_event_id, o.journal_event_id) : '-',
        '<span class="badge">' +
          esc(o.status) +
          '</span> <button type="button" data-pp-track-cap="' +
          esc(o.capture_id) +
          '">+ Track DHL</button>',
      ])
    ) +
    '<div class="toolbar" style="justify-content:space-between;flex-wrap:wrap;gap:8px;margin-top:14px">' +
    '<strong>2. Recurring SaaS Subscriptions v1 (Catalog Product + Billing Plan + Subscription)</strong>' +
    '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
    '<input id="paypal-sub-tier" aria-label="Subscription plan name" value="Kerdon Autonomous Mini-ERP Pro" style="min-width:210px">' +
    '<input id="paypal-sub-price" aria-label="Monthly subscription price in EUR" type="number" min="10" step="1" value="149" style="max-width:95px">' +
    '<button type="button" id="paypal-create-sub-btn" class="primary">+ Provision Subscription v1</button>' +
    '</div></div>' +
    (subs.length
      ? table(
          ['Subscription ID', 'Plan ID', 'Product ID', 'Tier', 'Monthly Fee', 'Status', 'Subscriber Approval'],
          subs.map((s: any) => [
            '<code>' + esc(s.subscription_id) + '</code>',
            '<code>' + esc(s.plan_id) + '</code>',
            '<code>' + esc(s.product_id) + '</code>',
            esc(s.tier_name),
            money(s.monthly_price_cents || 0),
            '<span class="badge">' + esc(s.status) + '</span>',
            s.approval_url
              ? '<a href="' + esc(s.approval_url) + '" target="_blank" rel="noopener noreferrer">Approve Subscription ↗</a>'
              : '-',
          ])
        )
      : '') +
    (payouts.length || disputes.length
      ? '<div style="margin-top:14px"><strong>3. Governed Batch Payouts v1 (' +
        payouts.length +
        ') &amp; Dispute Defense Packets (' +
        disputes.length +
        ')</strong>' +
        table(
          ['Batch / Dispute ID', 'Counterparty / Seller', 'Amount', 'Status', 'Governance Proof'],
          [
            ...payouts.map((p: any) => [
              '<code>' + esc(p.payout_batch_id) + '</code>',
              esc(p.recipient_email),
              money(p.amount_cents || 0),
              '<span class="badge">' + esc(p.status) + '</span>',
              'Four-Eyes (' + esc(p.approver_id) + ' -> ' + esc(p.executor_id) + ')',
            ]),
            ...disputes.map((d: any) => [
              '<code>' + esc(d.dispute_id) + '</code>',
              esc(d.seller_id),
              money(d.disputed_amount_cents || 0),
              '<span class="badge">' + esc(d.status) + '</span>',
              'Clawback ' + money(d.clawback_commission_cents || 0) + ' · ' + esc(d.evidence_defense_packet?.evidence_type || 'PROOF_OF_FULFILLMENT'),
            ]),
          ]
        ) +
        '</div>'
      : '') +
    '</div>'
  );
}

export function bindPayPalCommerceEvents(ctx: any): void {
  const { $, api, path, load, fail, data } = ctx;
  const pickUnpaidDoc = () => {
    const unpaid = (data.records?.sales || []).find((s: any) => (s.paid_cents || 0) < (s.gross_cents || 0));
    if (!unpaid) throw Error('All sales invoices are already settled. Create a new sales invoice first.');
    return unpaid.document_id;
  };

  if ($('paypal-verify-btn')) {
    $('paypal-verify-btn').onclick = async () => {
      try {
        const res = await api(path('connectors/verify'), { connector: 'paypal' });
        const p = res.verification?.paypal || {};
        $('notice').textContent =
          'PayPal Verification: mode=' +
          (p.mode || 'unknown') +
          (p.app_id ? ' | app_id=' + p.app_id + ' | granted_scopes=' + p.scopes_count : ' | ' + (p.reason || 'ok'));
      } catch (e) {
        fail(e);
      }
    };
  }

  if ($('paypal-webhook-reg-btn')) {
    $('paypal-webhook-reg-btn').onclick = async () => {
      try {
        const res = await api(path('connectors/paypal/webhooks/register'), {});
        $('notice').textContent = 'PayPal Webhook v1 active: ' + (res.webhook?.webhook_id || '') + ' -> ' + (res.webhook?.url || '');
        await load();
      } catch (e) {
        fail(e);
      }
    };
  }

  if ($('paypal-sync-disputes-btn')) {
    $('paypal-sync-disputes-btn').onclick = async () => {
      try {
        const res = await api(path('connectors/paypal/disputes/sync'), {});
        $('notice').textContent =
          'Synced PayPal Disputes v1 (' + (res.provider_mode || '') + '): ' + (res.count ?? 0) + ' open live disputes.';
      } catch (e) {
        fail(e);
      }
    };
  }

  if ($('paypal-payout-btn')) {
    $('paypal-payout-btn').onclick = async () => {
      try {
        const slug = data.tenant?.slug || 'aegean-mobility';
        const res = await api(path('connectors/paypal/payout'), {
          approval_id: 'apr-' + slug + '-comm-oct',
          executor_id: 'act-nikos-alexiou',
          recipient_email: 'seller-payout-sb@kerdon-synth.eu',
        });
        $('notice').textContent = 'Executed Governed PayPal Payout Batch: ' + (res.payout?.payout_batch_id || '');
        await load();
      } catch (e) {
        fail(e);
      }
    };
  }

  if ($('paypal-agent-run-btn')) {
    $('paypal-agent-run-btn').onclick = async () => {
      try {
        const goal = ($('paypal-agent-input')?.value || '').trim();
        $('paypal-agent-run-btn').disabled = true;
        $('paypal-agent-run-btn').textContent = 'Running Strands @tool Agent...';
        const res = await api(path('connectors/paypal/agent'), { goal });
        lastPayPalAgentResult = res;
        $('notice').textContent = 'PayPal Strands Agent executed ' + (res.tools_executed_count || 0) + ' tool(s).';
        await load();
      } catch (e) {
        fail(e);
      } finally {
        if ($('paypal-agent-run-btn')) {
          $('paypal-agent-run-btn').disabled = false;
          $('paypal-agent-run-btn').textContent = 'Run PayPal Strands Agent';
        }
      }
    };
  }

  if ($('paypal-create-order-btn')) {
    $('paypal-create-order-btn').onclick = async () => {
      try {
        const docId = pickUnpaidDoc();
        const res = await api(path('connectors/paypal/order'), { document_id: docId, auto_capture: false });
        $('notice').textContent =
          'Created PayPal Order v2 ' +
          (res.order?.order_id || '') +
          ' [' +
          (res.order?.status || 'CREATED') +
          ']. Approve as buyer via Checkout link, then click Capture -> GL.';
        await load();
      } catch (e) {
        fail(e);
      }
    };
  }

  if ($('paypal-capture-next-btn')) {
    $('paypal-capture-next-btn').onclick = async () => {
      try {
        const pending = data.connectors?.paypal?.pending_orders || [];
        if (pending.length && data.connectors?.runtime_modes?.paypal_credentials_present) {
          const first = pending[0];
          const ppRes = await api(path('connectors/paypal/capture'), {
            order_id: first.order_id,
            document_id: first.document_id,
          });
          await load();
          if (ppRes.agentic_commerce_narrative?.executive_summary) {
            $('notice').textContent = ppRes.agentic_commerce_narrative.executive_summary;
          }
          return;
        }
        const docId = pickUnpaidDoc();
        const isLive = Boolean(data.connectors?.runtime_modes?.paypal_credentials_present);
        const ppRes = await api(path('connectors/paypal/order'), {
          document_id: docId,
          auto_capture: !isLive,
        });
        await load();
        if (!ppRes.captured) {
          $('notice').textContent =
            'Live Sandbox Order ' +
            (ppRes.order?.order_id || '') +
            ' created! Open "Approve on PayPal Sandbox" to authorize buyer funds, then click "Capture -> GL".';
        } else if (ppRes.agentic_commerce_narrative?.executive_summary) {
          $('notice').textContent = ppRes.agentic_commerce_narrative.executive_summary;
        }
      } catch (e) {
        fail(e);
      }
    };
  }

  if ($('paypal-create-sub-btn')) {
    $('paypal-create-sub-btn').onclick = async () => {
      try {
        const tierName = ($('paypal-sub-tier')?.value || 'Kerdon Autonomous Mini-ERP Pro').trim();
        const eur = Math.max(10, Number($('paypal-sub-price')?.value || 149));
        const res = await api(path('connectors/paypal/subscription'), {
          tier_name: tierName,
          monthly_price_cents: Math.round(eur * 100),
          currency: 'EUR',
        });
        $('notice').textContent =
          'Provisioned PayPal Subscription ' +
          (res.subscription?.subscription_id || '') +
          ' (Plan ' +
          (res.subscription?.plan_id || '') +
          ').';
        await load();
      } catch (e) {
        fail(e);
      }
    };
  }

  document.querySelectorAll('[data-pp-sync-order]').forEach((btn: any) => {
    btn.onclick = async () => {
      try {
        const oid = btn.getAttribute('data-pp-sync-order');
        const res = await api(path('connectors/paypal/order-status'), { order_id: oid });
        $('notice').textContent = 'Order ' + oid + ' live status: ' + (res.order_status?.status || 'UNKNOWN');
        await load();
      } catch (e) {
        fail(e);
      }
    };
  });

  document.querySelectorAll('[data-pp-cap-order]').forEach((btn: any) => {
    btn.onclick = async () => {
      try {
        const oid = btn.getAttribute('data-pp-cap-order');
        const docId = btn.getAttribute('data-pp-cap-doc');
        const res = await api(path('connectors/paypal/capture'), { order_id: oid, document_id: docId });
        $('notice').textContent =
          res.agentic_commerce_narrative?.executive_summary || 'Captured Order ' + oid + ' into 3-line GL journal.';
        await load();
      } catch (e) {
        fail(e);
      }
    };
  });

  document.querySelectorAll('[data-pp-track-cap]').forEach((btn: any) => {
    btn.onclick = async () => {
      try {
        const capId = btn.getAttribute('data-pp-track-cap');
        const trk = 'DHL-GR-' + String(capId).slice(-6).toUpperCase();
        await api(path('connectors/paypal/tracker'), { capture_id: capId, tracking_number: trk, carrier: 'DHL' });
        $('notice').textContent = 'Submitted PayPal Shipment Tracker ' + trk + ' for capture ' + capId + '.';
        await load();
      } catch (e) {
        fail(e);
      }
    };
  });
}

export async function consumePayPalOidcCallbackIfPresent(ctx: any): Promise<void> {
  const { api, path, $, fail } = ctx;
  const qs = new URLSearchParams(window.location.search);
  const code = qs.get('paypal_oidc_code') || (qs.get('state')?.startsWith('ppoidc:') ? qs.get('code') : null);
  if (!code) return;
  try {
    const cleanUrl = window.location.pathname + (window.location.hash || '#module=documents');
    window.history.replaceState({}, '', cleanUrl);
    const res = await api(path('connectors/paypal/oauth/callback'), { code });
    if ($('notice')) {
      $('notice').textContent =
        'Linked PayPal Identity (OIDC): ' + (res.identity?.email || res.identity?.payer_id || 'verified');
    }
  } catch (e) {
    fail(e);
  }
}

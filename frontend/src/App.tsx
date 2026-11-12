import { useEffect } from 'react';
import { mountWorkspaceRuntime } from './runtime';

export function App() {
  useEffect(() => {
    mountWorkspaceRuntime();
  }, []);

  const initialTenants = window.__KERDON_INITIAL_TENANTS__ || [];

  return (
    <>
      <aside id="sidebar">
        <div className="brand">
          <b>K</b>
          <span>
            Kerdon<small>OPERATIONS</small>
          </span>
        </div>
        <label htmlFor="tenant">
          Company
          <select id="tenant" aria-label="Company" defaultValue={initialTenants[0]?.tenant_id}>
            {initialTenants.map((t) => (
              <option key={t.tenant_id} value={t.tenant_id}>
                {t.display_name}
              </option>
            ))}
          </select>
        </label>
        <div id="sidebar-org-pill" className="org-pill"></div>
        <nav id="nav" aria-label="ERP modules"></nav>
        <div id="legacy" className="legacy">
          Sofia Marinou · Double-Entry GL · PayPal &amp; ISO 20022
        </div>
      </aside>

      <div id="main">
        <header>
          <button id="menu" className="icon" aria-label="Toggle navigation" type="button">
            ☰
          </button>
          <span id="crumb">Kerdon / Dashboard</span>
          <div className="header-actions">
            <button id="role-preview-badge" type="button" className="badge" hidden>
              Role Preview · Reset
            </button>
            <button id="cmd-btn" type="button" aria-label="Open command palette">
              🔍 Search Ctrl+K
            </button>
            <label htmlFor="lang-select" className="sr-only">
              Interface language
            </label>
            <select id="lang-select" aria-label="Interface language" defaultValue="en" style={{ fontSize: '12px', padding: '6px 10px' }}>
              <option value="en">EN · English</option>
              <option value="el">EL · Greek</option>
            </select>
            <span id="connection" className="badge">
              Connecting
            </span>
            <button id="theme-toggle" type="button" aria-label="Toggle theme">
              ☀ Theme
            </button>
            <button id="refresh" className="icon" aria-label="Refresh records" type="button">
              ↻
            </button>
          </div>
        </header>
        <main>
          <div className="page-head">
            <div>
              <div id="page-eyebrow" className="eyebrow">
                EXECUTIVE FINANCIAL OPERATIONS &amp; REAL-TIME DOUBLE-ENTRY LEDGER
              </div>
              <h1 id="title">Dashboard</h1>
              <p id="company-name" hidden></p>
              <p id="j5-tagline" style={{ fontSize: '12px', margin: '4px 0 0' }}>
                Kerdon turns PayPal checkouts, subscriptions, disputes, and bills into a balanced double-entry ledger, seller commissions, and Four-Eyes governed payouts.
              </p>
              <button id="shell-self-approve-guard" type="button" disabled aria-describedby="four-eyes-policy" hidden>
                Self-Approve Own Payout
              </button>
              <span id="four-eyes-policy" hidden>
                This action is unavailable due to Four-Eyes separation: preparer cannot approve own payout.
              </span>
            </div>
            <div id="period-bar" className="period">
              <label htmlFor="start">
                From
                <input id="start" type="date" />
              </label>
              <label htmlFor="end">
                Through
                <input id="end" type="date" />
              </label>
              <button id="apply" type="button">
                Apply
              </button>
            </div>
          </div>
          <p id="notice" className="notice" role="status"></p>
          <div id="error" role="alert" hidden></div>
          <section id="content" aria-live="polite">
            Loading records…
          </section>
        </main>
      </div>

      <dialog id="draft-dialog">
        <div className="section-head">
          <h2 id="draft-title">Draft</h2>
          <button id="close-dialog" className="icon" aria-label="Close form" type="button">
            ×
          </button>
        </div>
        <form id="draft-form">
          <div id="draft-tabs" className="tabs"></div>
          <div id="draft-body"></div>
          <div id="draft-error" role="alert"></div>
          <div className="dialog-foot">
            <button type="button" id="save-draft">
              Download draft
            </button>
            <button type="submit" id="submit-document" className="primary">
              Submit to existing backend
            </button>
          </div>
        </form>
      </dialog>

      <dialog id="cmd-dialog">
        <div className="section-head">
          <h2>Global Command &amp; Module Search (Ctrl+K)</h2>
          <button id="close-cmd" type="button" className="icon" aria-label="Close command palette">
            ×
          </button>
        </div>
        <label htmlFor="cmd-input" className="sr-only">
          Search modules and actions
        </label>
        <input id="cmd-input" aria-label="Search modules and actions" placeholder="Type a module or command (e.g. Statements, Sales, Treasury, PayPal, Inventory)..." style={{ width: '100%' }} />
        <div id="cmd-list" className="cmd-list"></div>
      </dialog>
    </>
  );
}

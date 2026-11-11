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
        <nav id="nav" aria-label="ERP modules"></nav>
        <div id="legacy" className="legacy">
          Double-Entry GL · myDATA · ISO 20022
        </div>
      </aside>

      <div id="main">
        <header>
          <button id="menu" className="icon" aria-label="Toggle navigation" type="button">
            ☰
          </button>
          <span id="crumb">Kerdon / Dashboard</span>
          <div className="header-actions">
            <button id="cmd-btn" type="button" aria-label="Open command palette">
              🔍 Search Ctrl+K
            </button>
            <label htmlFor="role-select" className="sr-only">
              Active RBAC Role
            </label>
            <select id="role-select" aria-label="Active RBAC Role" defaultValue="MSP_FINOPS_DIRECTOR" style={{ fontSize: '12px', padding: '6px 10px' }}>
              <option value="MSP_FINOPS_DIRECTOR">MSP Director: Sofia Marinou</option>
              <option value="CLIENT_OWNER">Role: Store Owner</option>
              <option value="ACCOUNTANT">Role: Accountant</option>
              <option value="STORE_MANAGER">Role: Store Manager</option>
              <option value="SELLER">Role: Seller (Restricted)</option>
            </select>
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
              <div className="eyebrow">EXECUTIVE FINANCIAL OPERATIONS &amp; REAL-TIME DOUBLE-ENTRY LEDGER</div>
              <h1 id="title">Dashboard</h1>
              <p id="company-name"></p>
              <p id="j5-tagline" style={{ fontSize: '12px', margin: '2px 0 0' }}>
                Kerdon MSP turns client emails and bills into a balanced double-entry ledger, seller commissions, auto-drafted fixes, and invalidated stale payouts on AWS.
              </p>
              <button id="shell-self-approve-guard" type="button" disabled aria-describedby="four-eyes-policy" hidden>
                Self-Approve Own Payout
              </button>
              <span id="four-eyes-policy" hidden>
                This action is unavailable due to Four-Eyes separation: preparer cannot approve own payout.
              </span>
            </div>
            <div className="period">
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
        <input id="cmd-input" aria-label="Search modules and actions" placeholder="Type a module or command (e.g. Sales, Treasury, PayPal, myDATA, Inventory)..." style={{ width: '100%' }} />
        <div id="cmd-list" className="cmd-list"></div>
      </dialog>
    </>
  );
}

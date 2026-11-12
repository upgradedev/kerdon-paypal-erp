import {
  AllCommunityModule,
  ModuleRegistry,
  colorSchemeDark,
  createGrid,
  themeQuartz,
  type ColDef,
  type GridApi,
  type GridOptions,
} from 'ag-grid-community';
import { AgCharts } from 'ag-charts-community';
import { formatMoney } from './api/client';

ModuleRegistry.registerModules([AllCommunityModule]);

const kerdonDarkTheme = themeQuartz.withPart(colorSchemeDark).withParams({
  backgroundColor: '#141a2e',
  foregroundColor: '#f1f5f9',
  headerBackgroundColor: '#0e1324',
  headerTextColor: '#e2e8f0',
  oddRowBackgroundColor: '#101628',
  borderColor: '#29324d',
  accentColor: '#818cf8',
  fontFamily: "'Segoe UI', system-ui, -apple-system, sans-serif",
  fontSize: 12.5,
  headerFontSize: 11.5,
  rowVerticalPaddingScale: 0.92,
});

const kerdonLightTheme = themeQuartz.withParams({
  backgroundColor: '#ffffff',
  foregroundColor: '#0f172a',
  headerBackgroundColor: '#f1f5f9',
  headerTextColor: '#1e293b',
  oddRowBackgroundColor: '#f8fafc',
  borderColor: '#cbd5e1',
  accentColor: '#4338ca',
  fontFamily: "'Segoe UI', system-ui, -apple-system, sans-serif",
  fontSize: 12.5,
  headerFontSize: 11.5,
  rowVerticalPaddingScale: 0.92,
});

const activeGrids = new Set<{ el: HTMLElement; api: GridApi }>();
const activeCharts = new Set<{ el: HTMLElement; chart: any; baseOpts: Record<string, any> }>();
let studioCounter = 0;

function isLightMode(): boolean {
  return document.body.classList.contains('theme-light');
}

function pruneDetached(): void {
  activeGrids.forEach((entry) => {
    if (!document.body.contains(entry.el)) {
      try {
        entry.api.destroy();
      } catch {
        // ignore destroyed grid
      }
      activeGrids.delete(entry);
    }
  });
  activeCharts.forEach((entry) => {
    if (!document.body.contains(entry.el)) {
      try {
        entry.chart.destroy();
      } catch {
        // ignore destroyed chart
      }
      activeCharts.delete(entry);
    }
  });
}

export function syncAgTheme(): void {
  pruneDetached();
  const theme = (isLightMode() ? kerdonLightTheme : kerdonDarkTheme) as any;
  activeGrids.forEach(({ api }) => {
    try {
      api.setGridOption('theme', theme);
    } catch {
      // ignore
    }
  });
  activeCharts.forEach((entry) => {
    try {
      entry.chart.destroy();
      entry.el.innerHTML = '';
      entry.chart = AgCharts.create(buildChartThemeOptions({ ...entry.baseOpts, container: entry.el }) as any);
    } catch {
      // ignore
    }
  });
}

export interface StudioColumn {
  field: string;
  headerName: string;
  numeric?: boolean;
  cents?: boolean;
  isHtml?: boolean;
  sumCents?: boolean;
  minWidth?: number;
  maxWidth?: number;
  flex?: number;
  pinned?: 'left' | 'right';
  mobileHide?: boolean;
}

export interface StudioPreset {
  id: string;
  label: string;
  predicate?: (row: Record<string, any>) => boolean;
  sortField?: string;
  sortDir?: 'asc' | 'desc';
}

export interface EnterpriseGridConfig {
  idPrefix?: string;
  title?: string;
  lang?: 'en' | 'el';
  columns: StudioColumn[];
  rows: Record<string, any>[];
  presets?: StudioPreset[];
  enableStudioBar?: boolean;
  totalLabel?: string;
  csvFileName?: string;
  primaryAmountField?: string;
  onRendered?: () => void;
}

function escHtml(v: unknown): string {
  return String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] || c));
}

export function mountEnterpriseGrid(container: HTMLElement | null, cfg: EnterpriseGridConfig): GridApi | null {
  if (!container) return null;
  pruneDetached();
  const uid = (cfg.idPrefix || 'ag') + '-' + (++studioCounter);
  const lang = cfg.lang || 'en';
  const isEl = lang === 'el';
  const isMobile = window.innerWidth < 768;
  const showStudio = cfg.enableStudioBar !== false;
  const amountKey = cfg.primaryAmountField || cfg.columns.find((c) => c.cents)?.field || '';

  const presets: StudioPreset[] = cfg.presets || [];
  let activePresetId = presets[0]?.id || 'all';
  let nlQuery = '';

  const studioHtml = showStudio
    ? '<div class="ag-studio-bar">' +
      '<div class="ag-studio-top">' +
      '<span class="ag-studio-badge">AG Grid Studio</span>' +
      '<label for="' +
      uid +
      '-nl" class="sr-only">' +
      (isEl ? 'Έξυπνο φίλτρο πίνακα AG Grid' : 'AI smart filter for AG Grid') +
      '</label>' +
      '<input id="' +
      uid +
      '-nl" class="ag-nl-input" placeholder="' +
      escHtml(
        isEl
          ? 'Έξυπνη αναζήτηση / εντολή (π.χ. > 1000, open, DR, PayPal)...'
          : 'AI Grid filter & query (e.g. > 1000, open, DR, PayPal, top)...'
      ) +
      '">' +
      '<span id="' +
      uid +
      '-count" class="ag-row-pill"></span>' +
      '<button type="button" id="' +
      uid +
      '-csv" class="ag-csv-btn">' +
      (isEl ? '↓ Εξαγωγή CSV' : '↓ Export CSV') +
      '</button>' +
      '</div>' +
      (presets.length
        ? '<div class="ag-preset-row">' +
          presets
            .map(
              (p, i) =>
                '<button type="button" class="ag-chip' +
                (i === 0 ? ' active' : '') +
                '" data-ag-preset="' +
                escHtml(p.id) +
                '">' +
                escHtml(p.label) +
                '</button>'
            )
            .join('') +
          '</div>'
        : '') +
      '</div>'
    : '';

  const visibleColCount = cfg.columns.filter((c) => !(isMobile && c.mobileHide)).length;
  const wideMobileClass = visibleColCount >= 4 ? ' ag-wide-mobile' : '';
  const regionLabel = escHtml(cfg.title || (isEl ? 'Πίνακας οικονομικών δεδομένων' : 'Financial data grid'));
  const emptyText = escHtml(isEl ? 'Δεν βρέθηκαν εγγραφές για αυτό το φίλτρο.' : 'No records match the current filter.');

  container.innerHTML =
    studioHtml +
    '<div id="' +
    uid +
    '-shell" class="ag-scroll-shell" tabindex="0" role="region" aria-label="' +
    regionLabel +
    '"><div id="' +
    uid +
    '-host" class="ag-grid-host' +
    wideMobileClass +
    '"></div></div>' +
    '<div id="' +
    uid +
    '-empty" class="ag-empty-box" role="status" hidden>' +
    emptyText +
    '</div>';
  const shell = document.getElementById(uid + '-shell') as HTMLElement | null;
  const emptyBox = document.getElementById(uid + '-empty') as HTMLElement | null;
  const host = document.getElementById(uid + '-host') as HTMLElement | null;
  if (!host || !shell || !emptyBox) return null;

  const hasSums = cfg.columns.some((c) => c.sumCents);
  const firstColField = cfg.columns[0]?.field || 'col0';

  const computePinnedTotals = (visibleRows: Record<string, any>[]): Record<string, any>[] => {
    if (!hasSums || !visibleRows.length) return [];
    const totalRow: Record<string, any> = { __isPinnedTotal: true };
    cfg.columns.forEach((col, idx) => {
      if (idx === 0) {
        const lbl = cfg.totalLabel || (isEl ? 'Γενικό Σύνολο' : 'Grand Total');
        totalRow[col.field] = lbl + ' (' + visibleRows.length + ')';
      } else if (col.sumCents) {
        totalRow[col.field] = visibleRows.reduce((sum, r) => sum + Number(r[col.field] || 0), 0);
      } else {
        totalRow[col.field] = '';
      }
    });
    return [totalRow];
  };

  const colDefs: ColDef[] = cfg.columns
    .filter((c) => !(isMobile && c.mobileHide))
    .map((c) => {
      const isRight = Boolean(c.numeric || c.cents);
      const def: ColDef = {
        field: c.field,
        headerName: c.headerName,
        sortable: true,
        resizable: !isMobile,
        suppressHeaderFilterButton: true,
        minWidth: isMobile ? Math.min(c.minWidth || 88, 92) : c.minWidth || (isRight ? 115 : 120),
        maxWidth: c.maxWidth,
        flex: c.flex ?? 1,
        pinned: isMobile ? undefined : c.pinned,
        headerClass: isRight ? 'ag-right-aligned-header' : undefined,
        cellClass: (params: any) => {
          const classes: string[] = [];
          if (isRight) classes.push('ag-right-aligned-cell', 'ag-tabular-num');
          if (params.node?.rowPinned === 'bottom') classes.push('ag-pinned-total-cell');
          return classes.join(' ');
        },
      };
      if (c.cents) {
        def.valueFormatter = (params: any) => {
          if (params.value === '' || params.value === null || params.value === undefined) return '';
          return formatMoney(Number(params.value));
        };
      } else if (c.isHtml) {
        def.cellRenderer = (params: any) => {
          const span = document.createElement('span');
          span.className = 'ag-html-cell';
          if (params.node?.rowPinned === 'bottom') {
            span.textContent = String(params.value ?? '');
            span.style.fontWeight = '700';
          } else {
            span.innerHTML = String(params.value ?? '');
          }
          return span;
        };
      } else if (c.field === firstColField) {
        def.cellRenderer = (params: any) => {
          const span = document.createElement('span');
          span.textContent = String(params.value ?? '');
          if (params.node?.rowPinned === 'bottom') span.style.fontWeight = '700';
          return span;
        };
      }
      return def;
    });

  const filterRows = (): { filtered: Record<string, any>[]; sortField?: string; sortDir?: 'asc' | 'desc' } => {
    const preset = presets.find((p) => p.id === activePresetId);
    let working = preset?.predicate ? cfg.rows.filter(preset.predicate) : cfg.rows.slice();
    let sortField = preset?.sortField;
    let sortDir = preset?.sortDir;

    const q = nlQuery.trim().toLowerCase();
    if (q) {
      const gtMatch = q.match(/^>\s*€?\s*(\d+(?:\.\d+)?)$/);
      const ltMatch = q.match(/^<\s*€?\s*(\d+(?:\.\d+)?)$/);
      if (gtMatch && amountKey) {
        const thresholdCents = Math.round( parseFloat(gtMatch[1]) * 100 );
        working = working.filter((r) => Math.abs(Number(r[amountKey] || 0)) > thresholdCents);
      } else if (ltMatch && amountKey) {
        const thresholdCents = Math.round( parseFloat(ltMatch[1]) * 100 );
        working = working.filter((r) => Math.abs(Number(r[amountKey] || 0)) < thresholdCents);
      } else if ((q === 'top' || q === 'largest' || q === 'max') && amountKey) {
        sortField = amountKey;
        sortDir = 'desc';
      } else if (q === 'dr' || q === 'debit' || q === 'χρ') {
        working = working.filter((r) => String(r._side || r.side || r.normal_side || '').toUpperCase() === 'DR' || Number(r.debit_cents || 0) > 0);
      } else if (q === 'cr' || q === 'credit' || q === 'πι') {
        working = working.filter((r) => String(r._side || r.side || r.normal_side || '').toUpperCase() === 'CR' || Number(r.credit_cents || 0) > 0);
      } else {
        working = working.filter((r) => JSON.stringify(r).toLowerCase().includes(q));
      }
    }
    return { filtered: working, sortField, sortDir };
  };

  const patchAgAccessibility = (shownCount: number) => {
    shell.hidden = shownCount === 0;
    emptyBox.hidden = shownCount > 0;
    if (shownCount === 0) return;

    host.querySelectorAll('.ag-tab-guard, .ag-overlay, .ag-body-horizontal-scroll, .ag-body-vertical-scroll, .ag-sticky-top, .ag-sticky-bottom, .ag-aria-description-container').forEach((el: any) => {
      el.setAttribute('aria-hidden', 'true');
      el.removeAttribute('tabindex');
      el.style.display = 'none';
    });

    const root = host.querySelector('.ag-root') as HTMLElement | null;
    if (!root) return;
    root.setAttribute('role', 'grid');

    root.querySelectorAll('[role="rowgroup"], [data-ag-orig-role="rowgroup"]').forEach((rg: any) => {
      if (rg.querySelector('[role="row"]')) {
        rg.setAttribute('role', 'rowgroup');
        rg.removeAttribute('aria-hidden');
        if (rg.style.display === 'none') rg.style.display = '';
      } else {
        rg.setAttribute('data-ag-orig-role', 'rowgroup');
        rg.setAttribute('role', 'none');
        rg.setAttribute('aria-hidden', 'true');
        rg.style.display = 'none';
      }
    });

    root.querySelectorAll('*').forEach((el: any) => {
      if (el.closest('[aria-hidden="true"]') || el.style?.display === 'none') return;
      const role = el.getAttribute('role');
      if (!el.closest('[role="row"]') && role !== 'rowgroup') {
        el.removeAttribute('tabindex');
        Array.from(el.attributes).forEach((attr: any) => {
          if (attr.name.startsWith('aria-')) el.removeAttribute(attr.name);
        });
        el.setAttribute('role', 'presentation');
      } else if (el.closest('[role="row"]') && !el.closest('[role="columnheader"], [role="gridcell"]') && role !== 'row') {
        el.removeAttribute('tabindex');
        Array.from(el.attributes).forEach((attr: any) => {
          if (attr.name.startsWith('aria-')) el.removeAttribute(attr.name);
        });
        el.setAttribute('role', 'presentation');
      }
    });
  };

  const initial = filterRows();
  let currentShownCount = initial.filtered.length;
  const gridOptions: GridOptions = {
    theme: (isLightMode() ? kerdonLightTheme : kerdonDarkTheme) as any,
    columnDefs: colDefs,
    rowData: initial.filtered,
    pinnedBottomRowData: computePinnedTotals(initial.filtered),
    domLayout: 'autoHeight',
    suppressColumnVirtualisation: true,
    suppressRowVirtualisation: true,
    suppressHorizontalScroll: true,
    suppressNoRowsOverlay: true,
    suppressCellFocus: true,
    animateRows: false,
    onModelUpdated: () => {
      patchAgAccessibility(currentShownCount);
      cfg.onRendered?.();
    },
    onGridSizeChanged: () => {
      patchAgAccessibility(currentShownCount);
    },
  };

  const api = createGrid(host, gridOptions);
  activeGrids.add({ el: host, api });
  patchAgAccessibility(currentShownCount);

  const updateCountBadge = (shown: number) => {
    const badge = document.getElementById(uid + '-count');
    if (badge) {
      badge.textContent = isEl
        ? shown + ' / ' + cfg.rows.length + ' εγγραφές'
        : shown + ' of ' + cfg.rows.length + ' rows';
    }
  };
  updateCountBadge(initial.filtered.length);

  const refreshGridState = () => {
    const res = filterRows();
    currentShownCount = res.filtered.length;
    shell.hidden = false;
    api.setGridOption('rowData', res.filtered);
    api.setGridOption('pinnedBottomRowData', computePinnedTotals(res.filtered));
    if (res.sortField) {
      api.applyColumnState({
        state: [{ colId: res.sortField, sort: res.sortDir || 'desc' }],
        defaultState: { sort: null },
      });
    }
    patchAgAccessibility(currentShownCount);
    updateCountBadge(res.filtered.length);
    cfg.onRendered?.();
  };

  const nlInput = document.getElementById(uid + '-nl') as HTMLInputElement | null;
  if (nlInput) {
    nlInput.oninput = () => {
      nlQuery = nlInput.value;
      refreshGridState();
    };
  }

  const csvBtn = document.getElementById(uid + '-csv');
  if (csvBtn) {
    csvBtn.onclick = () => {
      api.exportDataAsCsv({
        fileName: cfg.csvFileName || 'kerdon-ag-grid-export.csv',
        processCellCallback: (params: any) => {
          const raw = String(params.value ?? '');
          return raw.replace(/<[^>]+>/g, '').trim();
        },
      });
    };
  }

  container.querySelectorAll('[data-ag-preset]').forEach((btn: any) => {
    btn.onclick = () => {
      activePresetId = btn.getAttribute('data-ag-preset') || 'all';
      container.querySelectorAll('[data-ag-preset]').forEach((b: any) => {
        b.classList.toggle('active', b === btn);
      });
      refreshGridState();
    };
  });

  cfg.onRendered?.();
  return api;
}

function buildChartThemeOptions(baseOpts: Record<string, any>): Record<string, any> {
  const light = isLightMode();
  return {
    ...baseOpts,
    theme: light ? 'ag-default' : 'ag-default-dark',
    background: { fill: light ? '#ffffff' : '#141a2e' },
  };
}

export function mountEnterpriseChart(container: HTMLElement | null, baseOpts: Record<string, any>): any {
  if (!container) return null;
  pruneDetached();
  container.innerHTML = '';
  try {
    const fullOpts = buildChartThemeOptions({ ...baseOpts, container });
    const chart = AgCharts.create(fullOpts as any);
    activeCharts.add({ el: container, chart, baseOpts });
    return chart;
  } catch {
    return null;
  }
}

export interface KpiDefinition {
  titleEn: string;
  titleEl: string;
  meaningEn: string;
  meaningEl: string;
  formulaEn: string;
  formulaEl: string;
  basisEn: string;
  basisEl: string;
}

export const KPI_CATALOG: Record<string, KpiDefinition> = {
  cash: {
    titleEn: 'Cash balance',
    titleEl: 'Ταμειακά Διαθέσιμα',
    meaningEn: 'Posted cash and payment-processor balances available across bank and PayPal accounts.',
    meaningEl: 'Λογιστικοποιημένα διαθέσιμα ταμείου, τραπεζών και λογαριασμών PayPal.',
    formulaEn: 'Opening Cash + Period Cash Debits (Inflows) - Period Cash Credits (Outflows)',
    formulaEl: 'Αρχικό Ταμείο + Εισπράξεις Περιόδου (Χρέωση) - Πληρωμές Περιόδου (Πίστωση)',
    basisEn: 'IFRS IAS 7 · GL 1000_CASH (Cumulative · Reconciled to Balance Sheet & Cash Card)',
    basisEl: 'ΔΛΠ 7 · Λογ. 1000_CASH (Σωρευτικό · Συμφωνία με Ισολογισμό & Καρτέλα Ταμείου)',
  },
  revenue: {
    titleEn: 'Period net revenue',
    titleEl: 'Καθαρά Έσοδα Περιόδου',
    meaningEn: 'Operating sales and principal commission revenue recognized in the selected period, excluding VAT.',
    meaningEl: 'Καθαρός κύκλος εργασιών πωλήσεων και προμηθειών στην επιλεγμένη περίοδο (προ ΦΠΑ).',
    formulaEn: 'GL 4000_SALES_REVENUE + GL 4100_COMMISSION_REVENUE (Credits - Debits)',
    formulaEl: 'Λογ. 4000_ΠΩΛΗΣΕΙΣ + 4100_ΠΡΟΜΗΘΕΙΕΣ (Πιστώσεις - Χρεώσεις)',
    basisEn: 'IFRS 15 Accrual Basis · Net ex-VAT (Credit Notes deducted)',
    basisEl: 'ΔΠΧΑ 15 Δεδουλευμένη Βάση · Καθαρή αξία προ ΦΠΑ',
  },
  receivables: {
    titleEn: 'Receivables',
    titleEl: 'Απαιτήσεις Πελατών (AR)',
    meaningEn: 'Total unpaid customer invoices currently owed to the company.',
    meaningEl: 'Συνολικό ανεξόφλητο υπόλοιπο πελατών από τιμολόγια επί πιστώσει.',
    formulaEn: 'GL 1100_AR (Debits - Credits) = Sum of Customer Open DR/CR Balances',
    formulaEl: 'Λογ. 1100_ΠΕΛΑΤΕΣ (Χρεώσεις - Πιστώσεις) = Άθροισμα Καρτελών Πελατών',
    basisEn: 'Gross inc-VAT · Reconciled 100% to Aging & Customer Account Cards',
    basisEl: 'Μικτή αξία με ΦΠΑ · 100% συμφωνία με Ενηλικίωση & Καρτέλες Πελατών',
  },
  payables: {
    titleEn: 'Payables',
    titleEl: 'Υποχρεώσεις Προμηθευτών (AP)',
    meaningEn: 'Total unpaid supplier bills and trade obligations currently owed by the company.',
    meaningEl: 'Συνολικό ανεξόφλητο υπόλοιπο προς προμηθευτές εμπορευμάτων και υπηρεσιών.',
    formulaEn: 'GL 2000_AP (Credits - Debits) = Sum of Supplier Open CR/DR Balances',
    formulaEl: 'Λογ. 2000_ΠΡΟΜΗΘΕΥΤΕΣ (Πιστώσεις - Χρεώσεις) = Άθροισμα Καρτελών Προμηθευτών',
    basisEn: 'Gross inc-VAT · Reconciled 100% to Aging & Supplier Account Cards',
    basisEl: 'Μικτή αξία με ΦΠΑ · 100% συμφωνία με Ενηλικίωση & Καρτέλες Προμηθευτών',
  },
  ebitda: {
    titleEn: 'Operating EBITDA',
    titleEl: 'Λειτουργικό EBITDA',
    meaningEn: 'Core operating profitability before interest, tax, depreciation, and amortization.',
    meaningEl: 'Λειτουργική κερδοφορία προ τόκων, φόρων και αποσβέσεων.',
    formulaEn: 'Net Revenue (4000/4100) - COGS (5000) - Operating Expenses (6000..6200)',
    formulaEl: 'Καθαρά Έσοδα - Κόστος Πωληθέντων (5000) - Λειτουργικά Έξοδα (6000..6200)',
    basisEn: 'IFRS 18 Income Statement · Excludes VAT',
    basisEl: 'ΔΠΧΑ 18 Κατάσταση Αποτελεσμάτων · Προ ΦΠΑ',
  },
  gross_margin: {
    titleEn: 'Gross Profit Margin',
    titleEl: 'Περιθώριο Μικτού Κέρδους',
    meaningEn: 'Share of net revenue retained after direct cost of goods sold (COGS).',
    meaningEl: 'Ποσοστό καθαρών εσόδων που απομένει μετά την αφαίρεση του κόστους πωληθέντων.',
    formulaEn: '(Net Revenue - Cost of Goods Sold 5000) / Net Revenue x 100',
    formulaEl: '(Καθαρά Έσοδα - Κόστος Πωληθέντων 5000) / Καθαρά Έσοδα x 100',
    basisEn: 'IAS 2 Weighted Average Cost (WAC) & IFRS 15',
    basisEl: 'ΔΛΠ 2 Μέσο Σταθμικό Κόστος & ΔΠΧΑ 15',
  },
  operating_cf: {
    titleEn: 'Operating Cash Flow (IAS 7)',
    titleEl: 'Λειτουργικές Ταμειακές Ροές (IAS 7)',
    meaningEn: 'Net cash generated or consumed by core business operations during the period.',
    meaningEl: 'Καθαρές ταμειακές εισροές/εκροές από τη λειτουργική δραστηριότητα της περιόδου.',
    formulaEn: 'Customer Cash Receipts - Supplier, Payroll, Rent, OpEx & Tax Cash Outflows',
    formulaEl: 'Εισπράξεις Πελατών - Πληρωμές Προμηθευτών, Μισθοδοσίας, Εξόδων & Φόρων',
    basisEn: 'IAS 7 Direct Method · Reconciled to GL 1000_CASH',
    basisEl: 'ΔΛΠ 7 Άμεση Μέθοδος · Συμφωνία με Λογ. 1000_CASH',
  },
  quick_ratio: {
    titleEn: 'Quick Ratio (Acid-Test)',
    titleEl: 'Άμεση Ρευστότητα (Quick Ratio)',
    meaningEn: 'Ability to cover all short-term liabilities using immediately liquid assets (Cash + AR).',
    meaningEl: 'Ικανότητα κάλυψης όλων των βραχυπρόθεσμων υποχρεώσεων με άμεσα ρευστοποιήσιμα στοιχεία.',
    formulaEn: '(Cash 1000 + Accounts Receivable 1100) / Total Current Liabilities (2000..2520)',
    formulaEl: '(Ταμείο 1000 + Απαιτήσεις 1100) / Σύνολο Βραχυπρόθεσμων Υποχρεώσεων',
    basisEn: 'IFRS Solvency Standard · Benchmark >= 1.00x',
    basisEl: 'Διεθνής Δείκτης Ρευστότητας · Όριο αναφοράς >= 1.00x',
  },
  current_ratio: {
    titleEn: 'Net Working Capital',
    titleEl: 'Καθαρό Κεφάλαιο Κίνησης (NWC)',
    meaningEn: 'Short-term capital buffer after deducting all current liabilities from current assets.',
    meaningEl: 'Απόθεμα βραχυπρόθεσμου κεφαλαίου (Κυκλοφορούν Ενεργητικό μείον Υποχρεώσεις).',
    formulaEn: 'Total Current Assets - Total Current Liabilities (Current Ratio = Assets / Liabilities)',
    formulaEl: 'Σύνολο Κυκλοφορούντος Ενεργητικού - Βραχυπρόθεσμες Υποχρεώσεις',
    basisEn: 'Balance Sheet Liquidity Cushion',
    basisEl: 'Ισολογισμός · Δείκτης Γενικής Ρευστότητας',
  },
  dso_dpo: {
    titleEn: 'Cash Cycle (DSO / DPO)',
    titleEl: 'Κύκλος Είσπραξης & Πληρωμής (DSO / DPO)',
    meaningEn: 'Average days to collect customer receivables (DSO) vs days taken to pay suppliers (DPO).',
    meaningEl: 'Μέσες ημέρες είσπραξης απαιτήσεων (DSO) έναντι ημερών εξόφλησης προμηθευτών (DPO).',
    formulaEn: 'DSO = (Open AR / Period Gross Sales) x Days · DPO = (Open AP / Period Purchases) x Days',
    formulaEl: 'DSO = (Απαιτήσεις / Πωλήσεις) x Ημέρες · DPO = (Υποχρεώσεις / Αγορές) x Ημέρες',
    basisEn: 'Corporate Treasury Working Capital Standard',
    basisEl: 'Διεθνές Πρότυπο Διαχείρισης Κεφαλαίου Κίνησης',
  },
};

let tipSeq = 0;

function escAttr(v: unknown): string {
  return String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] || c));
}

export function renderInfoTip(metricKey: string, lang: 'en' | 'el', custom?: Partial<KpiDefinition>): string {
  const base = KPI_CATALOG[metricKey] || {
    titleEn: metricKey,
    titleEl: metricKey,
    meaningEn: 'Posted General Ledger metric.',
    meaningEl: 'Λογιστικοποιημένο μέγεθος Γενικής Λογιστικής.',
    formulaEn: 'Derived from balanced double-entry journal lines.',
    formulaEl: 'Υπολογισμός από ισοσκελισμένες εγγραφές Γενικού Καθολικού.',
    basisEn: 'General Ledger integer cents',
    basisEl: 'Γενική Λογιστική (ακέραια λεπτά ευρώ)',
  };
  const def = { ...base, ...(custom || {}) };
  const tipId = 'kpi-tip-' + metricKey + '-' + (++tipSeq);
  const isEl = lang === 'el';
  const btnAria = isEl ? 'Ορισμός δείκτη και λογιστικός τύπος' : 'Metric definition and accounting formula';
  const meaning = isEl ? def.meaningEl : def.meaningEn;
  const formula = isEl ? def.formulaEl : def.formulaEn;
  const basis = isEl ? def.basisEl : def.basisEn;
  const fLbl = isEl ? 'Τύπος:' : 'Formula:';
  const bLbl = isEl ? 'Βάση GL:' : 'GL Basis:';
  return (
    '<span class="tip-anchor">' +
    '<button type="button" class="info-tip" aria-label="' +
    escAttr(btnAria) +
    '" aria-describedby="' +
    tipId +
    '">i</button>' +
    '<span id="' +
    tipId +
    '" role="tooltip" class="tip-pop">' +
    '<strong>' +
    escAttr(meaning) +
    '</strong>' +
    '<span><em>' +
    escAttr(fLbl) +
    '</em> ' +
    escAttr(formula) +
    '</span>' +
    '<span><em>' +
    escAttr(bLbl) +
    '</em> ' +
    escAttr(basis) +
    '</span>' +
    '</span></span>'
  );
}

export function renderKpiTile(opts: {
  metricKey: string;
  lang: 'en' | 'el';
  valueText: string;
  subText: string;
  dataAttrName?: string;
  dataAttrValue?: string;
  customTitle?: string;
  customTip?: Partial<KpiDefinition>;
}): string {
  const cat = KPI_CATALOG[opts.metricKey];
  const title =
    opts.customTitle ||
    (cat ? (opts.lang === 'el' ? cat.titleEl : cat.titleEn) : opts.metricKey);
  const attr = opts.dataAttrName ? ' ' + opts.dataAttrName + '="' + escAttr(opts.dataAttrValue ?? '') + '"' : '';
  return (
    '<div class="kpi-wrap">' +
    '<button type="button" class="kpi"' +
    attr +
    '><small>' +
    escAttr(title) +
    '</small><strong class="num-val">' +
    escAttr(opts.valueText) +
    '</strong><span>' +
    escAttr(opts.subText) +
    '</span></button>' +
    renderInfoTip(opts.metricKey, opts.lang, opts.customTip) +
    '</div>'
  );
}

export function renderRatioTile(opts: {
  metricKey: string;
  lang: 'en' | 'el';
  valueText: string;
  subText: string;
  customTitle?: string;
}): string {
  const cat = KPI_CATALOG[opts.metricKey];
  const title =
    opts.customTitle ||
    (cat ? (opts.lang === 'el' ? cat.titleEl : cat.titleEn) : opts.metricKey);
  return (
    '<div class="ratio-card">' +
    '<div class="ratio-head"><small>' +
    escAttr(title) +
    '</small>' +
    renderInfoTip(opts.metricKey, opts.lang) +
    '</div>' +
    '<strong class="num-val">' +
    escAttr(opts.valueText) +
    '</strong><span>' +
    escAttr(opts.subText) +
    '</span></div>'
  );
}

export function formatSideLabel(side: string | undefined, lang: 'en' | 'el'): string {
  const s = String(side || 'ZERO').toUpperCase();
  if (s === 'DR') return lang === 'el' ? 'ΧΡ' : 'DR';
  if (s === 'CR') return lang === 'el' ? 'ΠΙ' : 'CR';
  return '0.00';
}

export function renderSideBadge(side: string | undefined, lang: 'en' | 'el'): string {
  const s = String(side || 'ZERO').toUpperCase();
  const cls = s === 'DR' ? 'side-pill side-dr' : s === 'CR' ? 'side-pill side-cr' : 'side-pill side-zero';
  return '<span class="' + cls + '">' + escAttr(formatSideLabel(s, lang)) + '</span>';
}

"""Synthetic multi-tenant MSP fixtures covering all 8 Kerdon Mini-ERP modules."""
from __future__ import annotations

from dataclasses import dataclass

from .auth import Actor, Role
from .commissions import (
    AttributionStatus,
    ClawbackEvent,
    CommissionCaseStatus,
    CommissionGate,
    CommissionPlanVersion,
    CommissionTier,
    MonthlyCommissionCase,
    PrincipalSettlement,
    SalesAttribution,
    SalesEvent,
    TierMode,
    approve_commission_case,
    evaluate_seller_statement,
    submit_commission_case,
)
from .completeness import (
    BankMovement,
    CompletenessGap,
    TenantAuditInput,
    run_completeness_scan,
)
from .crm import (
    BookingStatus,
    ClientBooking,
    CommercialRegistry,
    CreditNote,
    Customer,
    DocumentRegisterEntry,
    Supplier,
)
from .docgen import (
    BoardPack,
    OutboundDraft,
    ProactiveDigest,
    build_cfo_board_pack,
    build_proactive_digest,
    draft_corrective_document,
)
from .fiscal import (
    ApdSocialSecurityDoc,
    FmyWithheldTaxDoc,
    PayrollRegisterDoc,
    VatPeriodSummary,
    WorkforceCostFusion,
    fuse_workforce_cost,
    summarize_vat_and_einvoice,
)
from .inbox import (
    AttachmentPayload,
    CandidateDocKind,
    EvidenceInbox,
    EvidenceSourceKind,
    ExtractedCandidate,
    FieldProvenance,
    RawEmailEnvelope,
)
from .ledger import AccountCode, FinancialEvent, GeneralLedger, LedgerLine
from .query import FactSheet, build_fact_sheet
from .reasoning import GapReasoning, reason_over_all_gaps
from .tenancy import (
    Direction,
    SalesTeam,
    SellerProfile,
    StoreLocation,
    TenancyCatalog,
    Tenant,
)
from .treasury import TreasuryEngine


@dataclass
class TenantMiniErpState:
    """Complete 8-module runtime state for one downstream MSP client tenant."""

    tenant: Tenant
    inbox: EvidenceInbox
    crm: CommercialRegistry
    ledger: GeneralLedger
    workforce_fusion: WorkforceCostFusion
    vat_summary: VatPeriodSummary
    commission_plan: CommissionPlanVersion
    commission_case: MonthlyCommissionCase
    settlements: tuple[PrincipalSettlement, ...]
    sales_events: tuple[SalesEvent, ...]
    attributions: tuple[SalesAttribution, ...]
    gaps: tuple[CompletenessGap, ...]
    reasonings: tuple[GapReasoning, ...]
    digest: ProactiveDigest
    outbound_drafts: tuple[OutboundDraft, ...]
    board_pack: BoardPack
    fact_sheet: FactSheet
    treasury: TreasuryEngine


@dataclass
class MspDemoWorkspace:
    """Multi-tenant MSP back-office workspace headed by Sofia Marinou."""

    director: Actor
    catalog: TenancyCatalog
    tenant_states: dict[str, TenantMiniErpState]
    default_tenant_id: str


def build_default_msp_workspace() -> MspDemoWorkspace:
    """Build deterministic synthetic MSP workspace with 3 downstream client tenants."""
    catalog = TenancyCatalog(msp_hub_id="msp-hellas-finops-01")
    director = Actor(
        actor_id="act-sofia-marinou",
        display_name="Sofia Marinou (MSP FinOps Director)",
        role=Role.MSP_FINOPS_DIRECTOR,
        allowed_tenant_ids=frozenset({"*"}),
    )

    t1 = catalog.onboard_tenant(
        slug="aegean-mobility",
        display_name="Aegean Mobility Stores S.A. (6 Franchise Stores)",
        legal_name="AEGEAN MOBILITY STORES SINGLE MEMBER SA",
        tax_id="EL998877665",
        aliases=("AEGEAN MOBILITY SA",),
    )
    t2 = catalog.onboard_tenant(
        slug="attica-grid-solar",
        display_name="Attica Commercial Solar & HVAC Ltd",
        legal_name="ATTICA COMMERCIAL SOLAR AND HVAC LTD",
        tax_id="EL997766554",
    )
    t3 = catalog.onboard_tenant(
        slug="cyclades-hospitality",
        display_name="Cyclades Boutique Hospitality Group",
        legal_name="CYCLADES BOUTIQUE HOSPITALITY IKE",
        tax_id="EL996655443",
    )

    states: dict[str, TenantMiniErpState] = {
        t1.tenant_id: _build_tenant_state(catalog, t1, scale=100),
        t2.tenant_id: _build_tenant_state(catalog, t2, scale=75),
        t3.tenant_id: _build_tenant_state(catalog, t3, scale=60),
    }
    return MspDemoWorkspace(
        director=director,
        catalog=catalog,
        tenant_states=states,
        default_tenant_id=t1.tenant_id,
    )


def _build_tenant_state(
    catalog: TenancyCatalog, tenant: Tenant, *, scale: int
) -> TenantMiniErpState:
    tid = tenant.tenant_id
    period = "2026-10"
    prior_period = "2026-09"

    store_a = StoreLocation(
        store_id=f"str-{tenant.slug}-syntagma",
        tenant_id=tid,
        parent_tenant_id=tid,
        name=f"{tenant.display_name.split()[0]} Flagship Store",
        city="Athens",
        monthly_target_cents=4_500_000 * scale // 100,
    )
    store_b = StoreLocation(
        store_id=f"str-{tenant.slug}-port",
        tenant_id=tid,
        parent_tenant_id=tid,
        name=f"{tenant.display_name.split()[0]} Port Branch",
        city="Piraeus",
        monthly_target_cents=3_200_000 * scale // 100,
    )
    catalog.register_store(store_a)
    catalog.register_store(store_b)

    team_a = SalesTeam(
        team_id=f"tm-{tenant.slug}-retail",
        tenant_id=tid,
        store_id=store_a.store_id,
        name="Enterprise & Retail Desk",
        lead_seller_id=f"slr-{tenant.slug}-01",
        monthly_target_cents=store_a.monthly_target_cents,
    )
    catalog.register_team(team_a)

    seller_1 = SellerProfile(
        seller_id=f"slr-{tenant.slug}-01",
        tenant_id=tid,
        store_id=store_a.store_id,
        team_id=team_a.team_id,
        full_name="Elena Papadopoulou",
        employee_code="EMP-101",
    )
    seller_2 = SellerProfile(
        seller_id=f"slr-{tenant.slug}-02",
        tenant_id=tid,
        store_id=store_b.store_id,
        team_id=team_a.team_id,
        full_name="Dimitris Vasileiou",
        employee_code="EMP-102",
    )
    catalog.register_seller(seller_1)
    catalog.register_seller(seller_2)

    # M2: Omnichannel Evidence Inbox with nested .msg/.eml & HTML table
    inbox = EvidenceInbox(tenant_id=tid)
    nested_eml = RawEmailEnvelope(
        message_id=f"msg-{tenant.slug}-nested-01",
        tenant_id=tid,
        sender="billing@alpine-logistics-synth.eu",
        recipient=tenant.inbox_address,
        subject="Forwarded Vendor Invoice INV-2026-881",
        received_at_epoch=1761900000,
        attachments=(
            AttachmentPayload(
                attachment_id="att-inv-881",
                filename="INV-2026-881.pdf",
                mime_type="application/pdf",
                raw_bytes=f"PDF-SYNTH-INV-881-{tid}".encode("utf-8"),
            ),
        ),
    )
    root_email = RawEmailEnvelope(
        message_id=f"msg-{tenant.slug}-root-01",
        tenant_id=tid,
        sender="store.manager@client-synth.eu",
        recipient=tenant.inbox_address,
        subject="October close pack + principal settlement table",
        received_at_epoch=1761900600,
        html_body_tables=(
            "<table><tr><td>Seller</td><td>Elena</td><td>42000.00</td></tr></table>",
        ),
        attachments=(
            AttachmentPayload(
                attachment_id="att-nested-msg",
                filename="vendor_bill.eml",
                mime_type="message/rfc822",
                raw_bytes=b"RFC822-CONTAINER",
                nested_message=nested_eml,
            ),
        ),
    )
    blob_hashes = inbox.ingest_email(root_email)
    primary_sha = blob_hashes[0]

    # M3: Commercial CRM
    crm = CommercialRegistry(tenant_id=tid)
    cust_1 = Customer(f"cus-{tenant.slug}-01", tid, "Olympus Retail Partners S.A.", "EL991122334", "ap@olympus-partners-synth.gr")
    cust_2 = Customer(f"cus-{tenant.slug}-02", tid, "Aegean Corporate Mobility Fleet S.A.", "EL094123987", "finance@aegean-fleet-synth.gr")
    cust_3 = Customer(f"cus-{tenant.slug}-03", tid, "Attica Retail Franchise Network IKE", "EL801445566", "accounts@attica-retail-synth.gr")
    sup_1 = Supplier(
        f"sup-{tenant.slug}-01", tid, "Alpine Cloud & Fiber Infrastructure Ltd", "EL994433221",
        "GR1601101250000000012300695", "Telecom & Cloud", (180_000, 195_000, 210_000), True,
    )
    sup_rent = Supplier(
        f"sup-{tenant.slug}-rent", tid, "Athenian Commercial Properties S.A.", "EL995544332",
        "GR1601101250000000099988776", "Store Rent", (350_000, 350_000, 350_000), True,
    )
    sup_3 = Supplier(
        f"sup-{tenant.slug}-ops", tid, "Hellas Managed Security & Utilities Ltd", "EL094887766",
        "GR1601101250000000055443322", "Managed Operations & Utilities", (250_000, 250_000), False,
    )
    for c_rec in (cust_1, cust_2, cust_3):
        crm.upsert_customer(c_rec)
    for s_rec in (sup_1, sup_rent, sup_3):
        crm.upsert_supplier(s_rec)

    sales_net = 8_500_000 * scale // 100
    sales_vat = sales_net * 24 // 100
    sales_gross = sales_net + sales_vat

    purch_net = 1_400_000 * scale // 100
    purch_vat = purch_net * 24 // 100
    purch_gross = purch_net + purch_vat

    doc_sale = DocumentRegisterEntry(
        document_id=f"doc-{tenant.slug}-sal-101",
        tenant_id=tid,
        direction=Direction.SALES_REVENUE,
        counterparty_id=cust_1.customer_id,
        counterparty_name=cust_1.legal_name,
        counterparty_tax_id=cust_1.tax_id,
        doc_type="SALES_INVOICE",
        net_cents=sales_net,
        vat_cents=sales_vat,
        gross_cents=sales_gross,
        paid_cents=sales_gross - 620_000,
        currency="EUR",
        issued_date="2026-10-08",
        due_date="2026-10-22",
        source_sha256=primary_sha,
        einvoice_mark="MARK-400099112233",
        store_id=store_a.store_id,
    )
    doc_purch = DocumentRegisterEntry(
        document_id=f"doc-{tenant.slug}-pur-201",
        tenant_id=tid,
        direction=Direction.PURCHASE_EXPENSE,
        counterparty_id=sup_1.supplier_id,
        counterparty_name=sup_1.legal_name,
        counterparty_tax_id=sup_1.tax_id,
        doc_type="PURCHASE_INVOICE",
        net_cents=purch_net,
        vat_cents=purch_vat,
        gross_cents=purch_gross,
        paid_cents=0,
        currency="EUR",
        issued_date="2026-10-12",
        due_date="2026-11-12",
        source_sha256=primary_sha,
        einvoice_mark="MARK-400099443322",
        store_id=store_a.store_id,
    )
    crm.register_document(doc_sale)
    crm.register_document(doc_purch)

    booking_1 = ClientBooking(
        booking_id=f"bk-{tenant.slug}-301",
        tenant_id=tid,
        customer_id=cust_1.customer_id,
        store_id=store_a.store_id,
        seller_id=seller_1.seller_id,
        total_agreed_cents=480_000,
        advance_deposit_cents=150_000,
        invoiced_cents=0,
        delivery_date="2026-10-28",
        status=BookingStatus.CONFIRMED,
    )
    crm.upsert_booking(booking_1)

    # M4: Ledger + Prior Period + 3-Doc Workforce Fusion
    ledger = GeneralLedger(tenant_id=tid)
    prior_net = 7_600_000 * scale // 100
    prior_vat = prior_net * 24 // 100
    prior_gross = prior_net + prior_vat
    prior_pur_net = 2_900_000 * scale // 100
    prior_pur_vat = prior_pur_net * 24 // 100
    prior_pur_gross = prior_pur_net + prior_pur_vat
    crm.register_document(
        DocumentRegisterEntry(
            f"doc-{tenant.slug}-prior", tid, Direction.SALES_REVENUE, cust_1.customer_id,
            cust_1.legal_name, cust_1.tax_id, "SALES_INVOICE", prior_net, prior_vat, prior_gross,
            prior_gross, "EUR", "2026-09-15", "2026-09-29", primary_sha, "MARK-400099001122", store_a.store_id,
        )
    )
    crm.register_document(
        DocumentRegisterEntry(
            f"doc-{tenant.slug}-prior-pur", tid, Direction.PURCHASE_EXPENSE, sup_1.supplier_id,
            sup_1.legal_name, sup_1.tax_id, "PURCHASE_INVOICE", prior_pur_net, prior_pur_vat, prior_pur_gross,
            prior_pur_gross, "EUR", "2026-09-18", "2026-09-30", primary_sha, "MARK-400099003344", store_a.store_id,
        )
    )
    ledger.post_sales_invoice(
        event_id=f"ev-{tenant.slug}-prior-sal",
        period=prior_period,
        posted_date="2026-09-15",
        document_id=f"doc-{tenant.slug}-prior",
        source_sha256=primary_sha,
        customer_id=cust_1.customer_id,
        net_cents=prior_net,
        vat_cents=prior_vat,
        gross_cents=prior_gross,
        store_id=store_a.store_id,
    )
    ledger.post_purchase_invoice(
        event_id=f"ev-{tenant.slug}-prior-pur",
        period=prior_period,
        posted_date="2026-09-18",
        document_id=f"doc-{tenant.slug}-prior-pur",
        source_sha256=primary_sha,
        supplier_id=sup_1.supplier_id,
        net_cents=prior_pur_net,
        vat_cents=prior_pur_vat,
        gross_cents=prior_pur_gross,
    )
    ledger.post(
        FinancialEvent(
            f"ev-{tenant.slug}-prior-cash-in", tid, prior_period, "2026-09-25",
            "Customer settlement on September invoice", f"doc-{tenant.slug}-prior", primary_sha,
            (LedgerLine(AccountCode.CASH_1000, debit_cents=prior_gross), LedgerLine(AccountCode.AR_1100, credit_cents=prior_gross, counterparty_id=cust_1.customer_id)),
        )
    )
    ledger.post(
        FinancialEvent(
            f"ev-{tenant.slug}-prior-cash-out", tid, prior_period, "2026-09-28",
            "Supplier settlement on September bill", f"doc-{tenant.slug}-prior-pur", primary_sha,
            (LedgerLine(AccountCode.AP_2000, debit_cents=prior_pur_gross, counterparty_id=sup_1.supplier_id), LedgerLine(AccountCode.CASH_1000, credit_cents=prior_pur_gross)),
        )
    )

    ledger.post_sales_invoice(
        event_id=f"ev-{tenant.slug}-curr-sal",
        period=period,
        posted_date="2026-10-08",
        document_id=doc_sale.document_id,
        source_sha256=primary_sha,
        customer_id=cust_1.customer_id,
        net_cents=sales_net,
        vat_cents=sales_vat,
        gross_cents=sales_gross,
        store_id=store_a.store_id,
    )
    ledger.post_purchase_invoice(
        event_id=f"ev-{tenant.slug}-curr-pur",
        period=period,
        posted_date="2026-10-12",
        document_id=doc_purch.document_id,
        source_sha256=primary_sha,
        supplier_id=sup_1.supplier_id,
        net_cents=purch_net,
        vat_cents=purch_vat,
        gross_cents=purch_gross,
        store_id=store_a.store_id,
    )
    # Cash collection on current sales invoice
    collected = doc_sale.paid_cents
    ledger.post(
        FinancialEvent(
            event_id=f"ev-{tenant.slug}-cash-in",
            tenant_id=tid,
            period=period,
            posted_date="2026-10-19",
            description="Customer wire collection",
            source_document_id=doc_sale.document_id,
            source_sha256=primary_sha,
            lines=(
                LedgerLine(account=AccountCode.CASH_1000, debit_cents=collected),
                LedgerLine(
                    account=AccountCode.AR_1100,
                    credit_cents=collected,
                    counterparty_id=cust_1.customer_id,
                ),
            ),
        )
    )

    payroll_doc = PayrollRegisterDoc(
        document_id=f"payreg-{tenant.slug}-{period}",
        tenant_id=tid,
        period=period,
        gross_wages_cents=2_200_000 * scale // 100,
        employee_social_security_cents=308_000 * scale // 100,
        withheld_tax_fmy_cents=242_000 * scale // 100,
        net_payable_cents=1_650_000 * scale // 100,
        commission_bonus_included_cents=185_000 * scale // 100,
        source_sha256=primary_sha,
    )
    apd_doc = ApdSocialSecurityDoc(
        document_id=f"apd-{tenant.slug}-{period}",
        tenant_id=tid,
        period=period,
        employer_contribution_cents=484_000 * scale // 100,
        employee_contribution_cents=308_000 * scale // 100,
        total_apd_cents=792_000 * scale // 100,
        source_sha256=primary_sha,
    )
    fmy_doc = FmyWithheldTaxDoc(
        document_id=f"fmy-{tenant.slug}-{period}",
        tenant_id=tid,
        period=period,
        withheld_income_tax_cents=242_000 * scale // 100,
        stamp_duty_cents=0,
        total_fmy_cents=242_000 * scale // 100,
        source_sha256=primary_sha,
    )
    wf_fusion = fuse_workforce_cost(
        payroll=payroll_doc,
        apd=apd_doc,
        fmy=fmy_doc,
        bank_net_transferred_cents=payroll_doc.net_payable_cents,
        posted_date="2026-10-30",
    )
    ledger.post(wf_fusion.journal_event)

    vat_summary = summarize_vat_and_einvoice(
        tid, period, tuple(crm.documents.values())
    )

    # M5: Seller Commissions & Principal Settlement
    settlement_1 = PrincipalSettlement(
        settlement_id=f"stl-{tenant.slug}-oct",
        tenant_id=tid,
        period=period,
        principal_name="Helios Carrier Network S.A.",
        principal_tax_id="EL990011223",
        agreed_net_cents=640_000,
        vat_cents=153_600,
        gross_cents=793_600,
        source_sha256=primary_sha,
        linked_sales_invoice_id="",
        linked_bank_receipt_id="",
    )
    plan = CommissionPlanVersion(
        plan_id=f"plan-{tenant.slug}-retail",
        version=2,
        tenant_id=tid,
        effective_from_period="2026-01",
        effective_to_period=None,
        mode=TierMode.PROGRESSIVE,
        tiers=(
            CommissionTier(0, 2_000_000, 300),
            CommissionTier(2_000_000, 5_000_000, 500),
            CommissionTier(5_000_000, None, 750),
        ),
        gate=CommissionGate(min_tnps_score=70, min_compliance_bps=9500),
        floor_cents=0,
        cap_cents=600_000,
    )
    sales_events = (
        SalesEvent(
            sale_id=f"sal-{tenant.slug}-01",
            tenant_id=tid,
            store_id=store_a.store_id,
            period=period,
            occurred_date="2026-10-09",
            net_revenue_cents=3_400_000,
            product_family="Fiber & Fleet Bundle",
            source_sha256=primary_sha,
        ),
        SalesEvent(
            sale_id=f"sal-{tenant.slug}-02",
            tenant_id=tid,
            store_id=store_b.store_id,
            period=period,
            occurred_date="2026-10-14",
            net_revenue_cents=2_100_000,
            product_family="Cloud PBX Upgrade",
            source_sha256=primary_sha,
        ),
        SalesEvent(
            sale_id=f"sal-{tenant.slug}-03-unattr",
            tenant_id=tid,
            store_id=store_b.store_id,
            period=period,
            occurred_date="2026-10-21",
            net_revenue_cents=410_000,
            product_family="Hardware Accessory Pack",
            source_sha256=primary_sha,
        ),
    )
    attributions = (
        SalesAttribution(
            attribution_id=f"att-{tenant.slug}-01",
            sale_id=sales_events[0].sale_id,
            tenant_id=tid,
            seller_id=seller_1.seller_id,
            status=AttributionStatus.APPROVED,
            share_bps=10_000,
            evidence_note="CRM order signed by Elena",
        ),
        SalesAttribution(
            attribution_id=f"att-{tenant.slug}-02",
            sale_id=sales_events[1].sale_id,
            tenant_id=tid,
            seller_id=seller_2.seller_id,
            status=AttributionStatus.APPROVED,
            share_bps=10_000,
            evidence_note="POS terminal attribution",
        ),
    )
    clawbacks = (
        ClawbackEvent(
            clawback_id=f"cb-{tenant.slug}-01",
            tenant_id=tid,
            seller_id=seller_1.seller_id,
            period=period,
            original_sale_id="sal-prior-cancelled",
            clawback_commission_cents=12_000,
            reason="Early subscriber cancellation within 30-day window",
        ),
    )
    stmt_1 = evaluate_seller_statement(
        seller_id=seller_1.seller_id,
        period=period,
        plan=plan,
        sales_events=sales_events,
        attributions=attributions,
        clawbacks=clawbacks,
        tnps_score=84,
    )
    stmt_2 = evaluate_seller_statement(
        seller_id=seller_2.seller_id,
        period=period,
        plan=plan,
        sales_events=sales_events,
        attributions=attributions,
        clawbacks=clawbacks,
        tnps_score=76,
    )
    draft_case = MonthlyCommissionCase(
        case_id=f"case-{tenant.slug}-{period}",
        tenant_id=tid,
        period=period,
        plan_id=plan.plan_id,
        plan_version=plan.version,
        statements=(stmt_1, stmt_2),
        status=CommissionCaseStatus.DRAFT,
    )
    submitted_case = submit_commission_case(draft_case, "mgr-store-lead")
    approved_case = approve_commission_case(submitted_case, "act-sofia-marinou")

    # Post approved seller commission expense to ledger
    ledger.post(
        FinancialEvent(
            event_id=f"ev-{tenant.slug}-comm-{period}",
            tenant_id=tid,
            period=period,
            posted_date="2026-10-31",
            description="Approved monthly seller commission accrual",
            source_document_id=approved_case.case_id,
            source_sha256=primary_sha,
            lines=(
                LedgerLine(
                    account=AccountCode.OPEX_COMMISSION_6050,
                    debit_cents=approved_case.total_payable_cents,
                ),
                LedgerLine(
                    account=AccountCode.PAYROLL_PAYABLE_2500,
                    credit_cents=approved_case.total_payable_cents,
                ),
            ),
        )
    )

    # M6: Completeness Scan & Gap Reasoner
    orphan_debit = BankMovement(
        movement_id=f"bnk-{tenant.slug}-orphan-01",
        tenant_id=tid,
        counterparty_id="sup-unknown-courier",
        counterparty_name="Aegean Express Courier Ltd",
        amount_cents=84_500,
        is_debit=True,
        value_date="2026-10-24",
        linked_document_id="",
    )
    audit_input = TenantAuditInput(
        tenant_id=tid,
        period=period,
        as_of_date="2026-11-05",
        documents=tuple(crm.documents.values()),
        suppliers=tuple(crm.suppliers.values()),
        bank_movements=(orphan_debit,),
        settlements=(settlement_1,),
        bookings=tuple(crm.bookings.values()),
        credit_notes=tuple(crm.credit_notes.values()),
        workforce_fusion=wf_fusion,
        commission_case=approved_case,
        payroll_commission_paid_cents=approved_case.total_payable_cents,
        sales_events=sales_events,
        attributions=attributions,
        clawbacks=clawbacks,
    )
    gaps = run_completeness_scan(audit_input)
    reasonings = reason_over_all_gaps(gaps)

    # M7: Digest, Outbound Auto-Drafts, Board Pack, Fact Sheet
    digest = build_proactive_digest(tid, period, gaps, reasonings)
    reason_by_id = {r.gap_id: r for r in reasonings}
    drafts = tuple(
        draft_corrective_document(g, reason_by_id[g.gap_id]) for g in gaps
    )
    pnl = ledger.summarize_period(period)
    mom = ledger.compute_mom_trend(period, prior_period)
    board_pack = build_cfo_board_pack(
        tenant_id=tid,
        period=period,
        pnl=pnl,
        mom_trend=mom,
        vat_summary=vat_summary,
        commission_case=approved_case,
        digest=digest,
        document_sha256s=(primary_sha,),
    )
    fact_sheet = build_fact_sheet(
        tenant_name=tenant.display_name,
        pnl=pnl,
        mom_trend=mom,
        vat_summary=vat_summary,
        commission_case=approved_case,
        gaps=gaps,
    )

    # M8: Multi-Currency Treasury & Approvals
    treasury = TreasuryEngine(tenant_id=tid)
    treasury.configure_pocket("EUR", balance_cents=pnl.cash_balance_cents, reserve_floor_cents=1_500_000)
    treasury.configure_pocket("USD", balance_cents=850_000, reserve_floor_cents=250_000)
    treasury.configure_pocket("GBP", balance_cents=420_000, reserve_floor_cents=150_000)

    treasury.create_approval(
        approval_id=f"apr-{tenant.slug}-sup-201",
        counterparty_id=sup_1.supplier_id,
        invoice_or_case_id=doc_purch.document_id,
        amount_cents=doc_purch.gross_cents,
        currency="EUR",
        evidence_sha256=primary_sha,
        approver_id="act-sofia-marinou",
        now_epoch=1761950000,
        preparer_id="act-nikos-controller",
    )
    treasury.create_approval(
        approval_id=f"apr-{tenant.slug}-comm-oct",
        counterparty_id="PAYROLL_COMMISSION_POOL",
        invoice_or_case_id=approved_case.case_id,
        amount_cents=approved_case.total_payable_cents,
        currency="EUR",
        evidence_sha256=primary_sha,
        approver_id="act-sofia-marinou",
        now_epoch=1761950100,
        preparer_id="act-nikos-controller",
    )

    return TenantMiniErpState(
        tenant=tenant,
        inbox=inbox,
        crm=crm,
        ledger=ledger,
        workforce_fusion=wf_fusion,
        vat_summary=vat_summary,
        commission_plan=plan,
        commission_case=approved_case,
        settlements=(settlement_1,),
        sales_events=sales_events,
        attributions=attributions,
        gaps=gaps,
        reasonings=reasonings,
        digest=digest,
        outbound_drafts=drafts,
        board_pack=board_pack,
        fact_sheet=fact_sheet,
        treasury=treasury,
    )


def build_empty_tenant_state(
    catalog: TenancyCatalog, tenant: Tenant, period: str = "2026-10"
) -> TenantMiniErpState:
    """Initialize a clean, zero-fixture tenant state for real production onboarding."""
    tid, z_sha = tenant.tenant_id, "0" * 64
    inbox, crm, ledger = EvidenceInbox(tid), CommercialRegistry(tid), GeneralLedger(tid)
    wf_fusion = WorkforceCostFusion(
        tenant_id=tid, period=period, true_employer_cost_cents=0, gross_wages_cents=0,
        employer_social_security_cents=0, net_salary_payable_cents=0, total_apd_payable_cents=0,
        total_fmy_payable_cents=0, bank_net_transferred_cents=0, missing_apd=False,
        missing_fmy=False, net_transfer_mismatch_cents=0,
        journal_event=FinancialEvent(
            f"ev-wf-init-{tid}", tid, period, f"{period}-28", "Unposted workforce placeholder",
            f"payreg-{tid}", z_sha,
            (LedgerLine(AccountCode.OPEX_WORKFORCE_6000, debit_cents=1), LedgerLine(AccountCode.PAYROLL_PAYABLE_2500, credit_cents=1)),
        ),
    )
    vat_summary = summarize_vat_and_einvoice(tid, period, ())
    plan = CommissionPlanVersion(
        f"pln-{tenant.slug}-v1", 1, tid, "2026-01", None, TierMode.PROGRESSIVE,
        (CommissionTier(0, None, 500),), CommissionGate(70, 9500), 0, 500_000,
    )
    case = MonthlyCommissionCase(f"case-{tenant.slug}-{period}", tid, period, plan.plan_id, 1, (), CommissionCaseStatus.DRAFT)
    pnl, mom = ledger.summarize_period(period), ledger.compute_mom_trend(period, "2026-09")
    digest = build_proactive_digest(tid, period, (), ())
    board_pack = build_cfo_board_pack(
        tenant_id=tid, period=period, pnl=pnl, mom_trend=mom,
        vat_summary=vat_summary, commission_case=case, digest=digest, document_sha256s=(z_sha,),
    )
    fact_sheet = build_fact_sheet(
        tenant_name=tenant.display_name, pnl=pnl, mom_trend=mom,
        vat_summary=vat_summary, commission_case=case, gaps=(),
    )
    treasury = TreasuryEngine(tenant_id=tid)
    for ccy in ("EUR", "USD", "GBP"):
        treasury.configure_pocket(ccy, balance_cents=0, reserve_floor_cents=0)
    return TenantMiniErpState(
        tenant=tenant, inbox=inbox, crm=crm, ledger=ledger, workforce_fusion=wf_fusion,
        vat_summary=vat_summary, commission_plan=plan, commission_case=case,
        settlements=(), sales_events=(), attributions=(), gaps=(), reasonings=(),
        digest=digest, outbound_drafts=(), board_pack=board_pack, fact_sheet=fact_sheet, treasury=treasury,
    )

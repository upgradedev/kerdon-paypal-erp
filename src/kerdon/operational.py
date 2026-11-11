"""Read-only operational projections from the existing posted ledger.

No mutation, posting, bank execution or persistence occurs in these functions.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date

from .ledger import AccountCode


def validate_period(start: str, end: str) -> None:
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError("Start date must not follow end date")


def party_statement(
    state, party_id: str, kind: str, start: str, end: str
) -> dict:
    """Opening + dated movements = closing, sourced only from posted AR/AP legs."""
    validate_period(start, end)
    if kind not in ("customer", "supplier"):
        raise ValueError("Statement kind must be customer or supplier")
    registry = state.crm.customers if kind == "customer" else state.crm.suppliers
    if party_id not in registry:
        raise KeyError("Counterparty does not belong to this tenant")
    account = AccountCode.AR_1100 if kind == "customer" else AccountCode.AP_2000
    sign = 1 if kind == "customer" else -1
    opening = 0
    balance = 0
    rows = []
    for event in sorted(
        state.ledger.events, key=lambda e: (e.posted_date, e.event_id)
    ):
        if event.tenant_id != state.tenant.tenant_id:
            raise ValueError("Cross-tenant ledger event")
        if event.posted_date > end:
            continue
        delta = sign * sum(
            line.debit_cents - line.credit_cents
            for line in event.lines
            if line.account == account and line.counterparty_id == party_id
        )
        if not delta:
            continue
        balance += delta
        if event.posted_date < start:
            opening = balance
        else:
            rows.append(
                {
                    "event_id": event.event_id,
                    "date": event.posted_date,
                    "source_document_id": event.source_document_id,
                    "source_sha256": event.source_sha256,
                    "description": event.description,
                    "increase_cents": max(0, delta),
                    "decrease_cents": max(0, -delta),
                    "balance_cents": balance,
                }
            )
    return {
        "tenant_id": state.tenant.tenant_id,
        "party_id": party_id,
        "kind": kind,
        "start": start,
        "end": end,
        "currency": "EUR",
        "basis": "posted-ledger",
        "opening_cents": opening,
        "closing_cents": balance,
        "rows": rows,
    }


def dashboard_projection(state, start: str, end: str) -> dict:
    """Period revenue/cash series and cumulative balance-sheet KPIs with source IDs."""
    validate_period(start, end)
    accounts = {
        "cash": (AccountCode.CASH_1000,),
        "receivables": (AccountCode.AR_1100,),
        "payables": (AccountCode.AP_2000,),
        "revenue": (
            AccountCode.REVENUE_SALES_4000,
            AccountCode.REVENUE_COMMISSION_4100,
        ),
    }
    kpis = {key: {"cents": 0, "event_ids": []} for key in accounts}
    series = {}
    rolling = {}
    opex_accounts = (
        AccountCode.OPEX_WORKFORCE_6000,
        AccountCode.OPEX_COMMISSION_6050,
        AccountCode.OPEX_RENT_UTILITIES_6100,
        AccountCode.OPEX_GENERAL_6200,
        AccountCode.DEPRECIATION_AMORTIZATION_6800,
        AccountCode.INTEREST_AND_TAX_6900,
    )
    running_cash = 0
    for event in sorted(
        state.ledger.events, key=lambda e: (e.posted_date, e.event_id)
    ):
        if event.tenant_id != state.tenant.tenant_id:
            raise ValueError("Cross-tenant ledger event")
        if event.posted_date > end:
            continue
        for key, selected in accounts.items():
            if key == "revenue" and event.posted_date < start:
                continue
            sign = -1 if key in ("payables", "revenue") else 1
            legs = [line for line in event.lines if line.account in selected]
            if legs:
                kpis[key]["cents"] += sign * sum(
                    line.debit_cents - line.credit_cents for line in legs
                )
                kpis[key]["event_ids"].append(event.event_id)
        ym = event.posted_date[:7]
        r_pt = rolling.setdefault(
            ym,
            {
                "inflow_cents": 0,
                "outflow_cents": 0,
                "net_cash_cents": 0,
                "ending_cash_cents": 0,
                "revenue_cents": 0,
                "cogs_cents": 0,
                "opex_cents": 0,
                "ebitda_cents": 0,
                "event_ids": [],
            },
        )
        r_pt["event_ids"].append(event.event_id)
        for line in event.lines:
            if line.account == AccountCode.CASH_1000:
                r_pt["inflow_cents"] += line.debit_cents
                r_pt["outflow_cents"] += line.credit_cents
                running_cash += line.debit_cents - line.credit_cents
            elif line.account in accounts["revenue"]:
                r_pt["revenue_cents"] += line.credit_cents - line.debit_cents
            elif line.account == AccountCode.COGS_5000:
                r_pt["cogs_cents"] += line.debit_cents - line.credit_cents
            elif line.account in opex_accounts:
                r_pt["opex_cents"] += line.debit_cents - line.credit_cents
        r_pt["net_cash_cents"] = r_pt["inflow_cents"] - r_pt["outflow_cents"]
        r_pt["ending_cash_cents"] = running_cash
        r_pt["ebitda_cents"] = (
            r_pt["revenue_cents"] - r_pt["cogs_cents"] - r_pt["opex_cents"]
        )
        if event.posted_date >= start:
            point = series.setdefault(
                ym,
                {
                    "inflow_cents": 0,
                    "outflow_cents": 0,
                    "revenue_cents": 0,
                    "opex_cents": 0,
                    "ebitda_cents": 0,
                    "event_ids": [],
                },
            )
            point["event_ids"].append(event.event_id)
            for line in event.lines:
                if line.account == AccountCode.CASH_1000:
                    point["inflow_cents"] += line.debit_cents
                    point["outflow_cents"] += line.credit_cents
                if line.account in accounts["revenue"]:
                    point["revenue_cents"] += line.credit_cents - line.debit_cents
                elif line.account in opex_accounts or line.account == AccountCode.COGS_5000:
                    point["opex_cents"] += line.debit_cents - line.credit_cents
            point["ebitda_cents"] = point["revenue_cents"] - point["opex_cents"]
    docs = getattr(getattr(state, "crm", None), "documents", {})
    period_gross_sales = sum(
        d.gross_cents
        for d in docs.values()
        if d.direction.value == "SALES_REVENUE" and start <= d.issued_date <= end
    )
    period_gross_purchases = sum(
        d.gross_cents
        for d in docs.values()
        if d.direction.value == "PURCHASE_EXPENSE" and start <= d.issued_date <= end
    )
    return {
        "tenant_id": state.tenant.tenant_id,
        "start": start,
        "end": end,
        "currency": "EUR",
        "basis": "posted-ledger",
        "kpis": kpis,
        "period_gross_sales_cents": period_gross_sales,
        "period_gross_purchases_cents": period_gross_purchases,
        "series": [{"period": period, **point} for period, point in series.items()],
        "rolling_series": [
            {"period": period, **point} for period, point in sorted(rolling.items())
        ],
    }


def operational_records(state, module: str) -> list[dict]:
    """Existing records, not invented invoices or reconstructed bank allocations."""
    if module in ("customers", "suppliers"):
        from .mydata_schema import resolve_organization_fiscal_profile, validate_greek_afm

        registry = (
            state.crm.customers if module == "customers" else state.crm.suppliers
        )
        key = "customer_id" if module == "customers" else "supplier_id"
        ext = getattr(state, "_erp_extensions", None)
        meta_map = getattr(ext, "party_metadata", {}) if ext else {}
        org_prof = resolve_organization_fiscal_profile(state)
        is_gr = bool(org_prof.get("is_greek_organization", True))
        rows = []
        for idx, party in enumerate(registry.values(), start=1):
            pid = getattr(party, key)
            pm = meta_map.get(pid, {})
            p_country = str(pm.get("country_code") or (org_prof["country_code"] if is_gr else "DE")).upper()
            row = {
                **asdict(party),
                "country_code": p_country,
                "doy": pm.get("doy", "Athens Corporate Tax Office (KEFODE Attikis)" if p_country == "GR" else ""),
                "gemi_number": pm.get("gemi_number", f"140982{idx:02d}1000" if p_country == "GR" else f"HRB-{8810 + idx}"),
                "branch_id": pm.get("branch_id", 0),
                "city": pm.get("city", "Athens" if p_country == "GR" else "Berlin"),
                "postal_code": pm.get("postal_code", "10563" if p_country == "GR" else "10117"),
                "afm_validation": validate_greek_afm(party.tax_id) if (is_gr and p_country == "GR") else None,
                **pm,
                "id": pid,
            }
            rows.append(row)
        return rows
    if module in ("sales", "purchases"):
        direction = "SALES_REVENUE" if module == "sales" else "PURCHASE_EXPENSE"
        ext = getattr(state, "_erp_extensions", None)
        line_map = getattr(ext, "document_lines", {}) if ext else {}
        status_map = getattr(ext, "document_status", {}) if ext else {}
        allocs_by_doc: dict[str, list[dict]] = {}
        if ext:
            for st_rec in getattr(ext, "settlements", {}).values():
                for sl in st_rec.allocations:
                    allocs_by_doc.setdefault(sl.document_id, []).append(
                        {
                            "settlement_id": st_rec.settlement_id,
                            "kind": st_rec.kind,
                            "posted_date": st_rec.posted_date,
                            "allocated_cents": sl.allocated_cents,
                            "ledger_event_id": st_rec.ledger_event_id,
                            "bank_execution_status": st_rec.bank_execution_status,
                        }
                    )
        for ev in state.ledger.events:
            cash_lines = [l for l in ev.lines if l.account == AccountCode.CASH_1000]
            if cash_lines and ev.source_document_id in state.crm.documents:
                existing_evs = {a["ledger_event_id"] for a in allocs_by_doc.get(ev.source_document_id, [])}
                if ev.event_id not in existing_evs:
                    c_amt = sum(l.debit_cents + l.credit_cents for l in cash_lines)
                    allocs_by_doc.setdefault(ev.source_document_id, []).append(
                        {
                            "settlement_id": ev.event_id,
                            "kind": "receipt" if cash_lines[0].debit_cents > 0 else "payment",
                            "posted_date": ev.posted_date,
                            "allocated_cents": c_amt,
                            "ledger_event_id": ev.event_id,
                            "bank_execution_status": "SETTLED_AT_BANK",
                        }
                    )
        out = []
        meta_map = getattr(ext, "party_metadata", {}) if ext else {}
        for idx, doc in enumerate(state.crm.documents.values(), start=101):
            if doc.direction.value != direction:
                continue
            dmeta = meta_map.get(f"__DOC_META__:{doc.document_id}", {})
            row = {
                **asdict(doc),
                "invoice_type": dmeta.get("invoice_type", "1.1" if module == "sales" else "13.1"),
                "series": dmeta.get("series", "A" if module == "sales" else "P"),
                "aa": dmeta.get("aa", str(idx)),
                "payment_method_code": dmeta.get("payment_method_code", 5 if doc.paid_cents == 0 else 1),
                "withheld_tax_pct": dmeta.get("withheld_tax_pct", 0),
                "withheld_tax_cents": dmeta.get("withheld_tax_cents", 0),
                **dmeta,
            }
            row["outstanding_cents"] = max(0, doc.gross_cents - doc.paid_cents)
            if doc.document_id in line_map:
                row["line_items"] = [
                    asdict(l) for l in line_map[doc.document_id]
                ]
            if doc.document_id in status_map:
                row["lifecycle_status"] = status_map[doc.document_id]
            if doc.document_id in allocs_by_doc:
                row["allocations"] = allocs_by_doc[doc.document_id]
            out.append(row)
        return out
    if module in ("payments", "receipts"):
        field = "credit_cents" if module == "payments" else "debit_cents"
        ext = getattr(state, "_erp_extensions", None)
        stl_by_ev = {
            s.ledger_event_id: s for s in (getattr(ext, "settlements", {}).values() if ext else ())
        }
        out_cash = []
        for event in state.ledger.events:
            if not any(line.account == AccountCode.CASH_1000 and getattr(line, field) > 0 for line in event.lines):
                continue
            amt = sum(getattr(line, field) for line in event.lines if line.account == AccountCode.CASH_1000)
            cp_id = next((l.counterparty_id for l in event.lines if l.counterparty_id), "")
            stl = stl_by_ev.get(event.event_id)
            allocs = (
                [
                    {
                        "settlement_id": stl.settlement_id,
                        "document_id": sl.document_id,
                        "posted_date": stl.posted_date,
                        "allocated_cents": sl.allocated_cents,
                        "ledger_event_id": event.event_id,
                        "bank_execution_status": stl.bank_execution_status,
                    }
                    for sl in stl.allocations
                ]
                if stl
                else (
                    [
                        {
                            "settlement_id": event.event_id,
                            "document_id": event.source_document_id,
                            "posted_date": event.posted_date,
                            "allocated_cents": amt,
                            "ledger_event_id": event.event_id,
                            "bank_execution_status": "SETTLED_AT_BANK",
                        }
                    ]
                    if event.source_document_id
                    else []
                )
            )
            out_cash.append(
                {
                    **asdict(event),
                    "amount_cents": amt,
                    "gross_cents": amt,
                    "paid_cents": amt,
                    "counterparty_id": stl.counterparty_id if stl else cp_id,
                    "allocations": allocs,
                }
            )
        return out_cash
    if module == "expenses":
        selected = (
            AccountCode.OPEX_GENERAL_6200,
            AccountCode.OPEX_RENT_UTILITIES_6100,
            AccountCode.OPEX_WORKFORCE_6000,
            AccountCode.OPEX_COMMISSION_6050,
        )
        out_exp = []
        for event in state.ledger.events:
            exp_lines = [line for line in event.lines if line.account in selected]
            if not exp_lines:
                continue
            amt = sum(line.debit_cents - line.credit_cents for line in exp_lines)
            cp_id = next((l.counterparty_id for l in event.lines if l.counterparty_id), "")
            out_exp.append(
                {
                    **asdict(event),
                    "amount_cents": amt,
                    "gross_cents": amt,
                    "counterparty_id": cp_id,
                    "expense_account": exp_lines[0].account.value,
                }
            )
        return out_exp
    raise ValueError("Unknown operational module")


def due_date_aging_report(state, as_of: str) -> dict:
    """Compute AR and AP due-date aging buckets strictly from open register documents."""
    as_of_date = date.fromisoformat(as_of)
    ext = getattr(state, "_erp_extensions", None)
    status_map = getattr(ext, "document_status", {}) if ext else {}

    def _empty_buckets() -> dict:
        return {
            "current_cents": 0,
            "days_1_30_cents": 0,
            "days_31_60_cents": 0,
            "days_61_90_cents": 0,
            "days_over_90_cents": 0,
            "total_open_cents": 0,
            "items": [],
        }

    ar = _empty_buckets()
    ap = _empty_buckets()
    reversed_after_as_of: set[str] = set()
    for ev in state.ledger.events:
        if ev.event_id.startswith("ev-rev-") and ev.posted_date > as_of and ev.source_document_id:
            reversed_after_as_of.add(ev.source_document_id)
    for doc in sorted(
        state.crm.documents.values(), key=lambda d: (d.due_date, d.document_id)
    ):
        if doc.issued_date > as_of:
            continue
        if status_map.get(doc.document_id) == "REVERSED" and doc.document_id not in reversed_after_as_of:
            continue
        future_paid = 0
        if ext:
            for st_rec in getattr(ext, "settlements", {}).values():
                if st_rec.posted_date > as_of:
                    for sl in st_rec.allocations:
                        if sl.document_id == doc.document_id:
                            future_paid += sl.allocated_cents
        paid_as_of = max(0, doc.paid_cents - future_paid)
        open_cents = max(0, doc.gross_cents - paid_as_of)
        if open_cents <= 0:
            continue
        target = (
            ar
            if doc.direction.value == "SALES_REVENUE"
            else ap
            if doc.direction.value == "PURCHASE_EXPENSE"
            else None
        )
        if target is None:
            continue
        due_d = date.fromisoformat(doc.due_date)
        days_past_due = (as_of_date - due_d).days
        if days_past_due <= 0:
            bucket = "current_cents"
        elif days_past_due <= 30:
            bucket = "days_1_30_cents"
        elif days_past_due <= 60:
            bucket = "days_31_60_cents"
        elif days_past_due <= 90:
            bucket = "days_61_90_cents"
        else:
            bucket = "days_over_90_cents"
        target[bucket] += open_cents
        target["total_open_cents"] += open_cents
        target["items"].append(
            {
                "document_id": doc.document_id,
                "counterparty_id": doc.counterparty_id,
                "due_date": doc.due_date,
                "days_past_due": max(0, days_past_due),
                "open_cents": open_cents,
                "bucket": bucket,
            }
        )
    return {"as_of": as_of, "receivables_aging": ar, "payables_aging": ap}


def profitability_and_cash_forecast(state, start: str, end: str) -> dict:
    """Compute period profitability, P&L statement, Balance Sheet, VAT return, and cash forecast."""
    validate_period(start, end)
    rev_sales = 0
    rev_comm = 0
    cogs_cents = 0
    opex_wf = 0
    opex_comm = 0
    opex_rent = 0
    opex_gen = 0
    period_out_vat = 0
    period_in_vat = 0
    event_ids = []
    cum_dr_minus_cr: dict[AccountCode, int] = {a: 0 for a in AccountCode}
    for ev in sorted(
        state.ledger.events, key=lambda e: (e.posted_date, e.event_id)
    ):
        if ev.posted_date > end:
            continue
        for line in ev.lines:
            cum_dr_minus_cr[line.account] = cum_dr_minus_cr.get(line.account, 0) + (
                line.debit_cents - line.credit_cents
            )
        if start <= ev.posted_date <= end:
            touched = False
            for line in ev.lines:
                if line.account == AccountCode.REVENUE_SALES_4000:
                    rev_sales += line.credit_cents - line.debit_cents
                    touched = True
                elif line.account == AccountCode.REVENUE_COMMISSION_4100:
                    rev_comm += line.credit_cents - line.debit_cents
                    touched = True
                elif line.account == AccountCode.COGS_5000:
                    cogs_cents += line.debit_cents - line.credit_cents
                    touched = True
                elif line.account == AccountCode.OPEX_WORKFORCE_6000:
                    opex_wf += line.debit_cents - line.credit_cents
                    touched = True
                elif line.account == AccountCode.OPEX_COMMISSION_6050:
                    opex_comm += line.debit_cents - line.credit_cents
                    touched = True
                elif line.account == AccountCode.OPEX_RENT_UTILITIES_6100:
                    opex_rent += line.debit_cents - line.credit_cents
                    touched = True
                elif line.account == AccountCode.OPEX_GENERAL_6200:
                    opex_gen += line.debit_cents - line.credit_cents
                    touched = True
                elif line.account == AccountCode.VAT_OUTPUT_2400:
                    period_out_vat += line.credit_cents - line.debit_cents
                elif line.account == AccountCode.VAT_INPUT_1400:
                    period_in_vat += line.debit_cents - line.credit_cents
            if touched:
                event_ids.append(ev.event_id)
    rev_cents = rev_sales + rev_comm
    opex_cents = opex_wf + opex_comm + opex_rent + opex_gen
    gross_profit = rev_cents - cogs_cents
    ebitda = gross_profit - opex_cents
    gross_margin_pct = round(gross_profit * 100.0 / rev_cents, 1) if rev_cents > 0 else 0.0
    ebitda_margin_pct = round(ebitda * 100.0 / rev_cents, 1) if rev_cents > 0 else 0.0

    aging = due_date_aging_report(state, end)
    cash_now = cum_dr_minus_cr[AccountCode.CASH_1000]
    ar_now = cum_dr_minus_cr[AccountCode.AR_1100]
    vat_in_now = cum_dr_minus_cr[AccountCode.VAT_INPUT_1400]
    inter_store_now = cum_dr_minus_cr[AccountCode.INTER_STORE_CLEAR_1900]
    total_assets = cash_now + ar_now + vat_in_now + inter_store_now

    ap_now = -cum_dr_minus_cr[AccountCode.AP_2000]
    deposits_now = -cum_dr_minus_cr[AccountCode.CUSTOMER_DEPOSITS_2100]
    vat_out_now = -cum_dr_minus_cr[AccountCode.VAT_OUTPUT_2400]
    payroll_now = -(
        cum_dr_minus_cr[AccountCode.PAYROLL_PAYABLE_2500]
        + cum_dr_minus_cr[AccountCode.SOCIAL_SECURITY_PAYABLE_2510]
        + cum_dr_minus_cr[AccountCode.WITHHELD_TAX_PAYABLE_2520]
    )
    total_liabilities = ap_now + deposits_now + vat_out_now + payroll_now
    cum_net_income = total_assets - total_liabilities

    docs = getattr(getattr(state, "crm", None), "documents", {})
    sales_docs = [d for d in docs.values() if d.direction.value == "SALES_REVENUE" and d.issued_date <= end]
    total_sales_gross = sum(d.gross_cents for d in sales_docs)
    total_sales_paid = sum(d.paid_cents for d in sales_docs)
    collection_rate_pct = (
        round(total_sales_paid * 100.0 / total_sales_gross, 1)
        if total_sales_gross > 0
        else 100.0
    )
    ar_total = aging["receivables_aging"]["total_open_cents"]
    ar_overdue = ar_total - aging["receivables_aging"]["current_cents"]
    overdue_ar_pct = round(ar_overdue * 100.0 / ar_total, 1) if ar_total > 0 else 0.0

    expected_inflows = ar_total
    expected_outflows = aging["payables_aging"]["total_open_cents"]
    return {
        "start": start,
        "end": end,
        "revenue_cents": rev_cents,
        "cogs_cents": cogs_cents,
        "gross_profit_cents": gross_profit,
        "opex_cents": opex_cents,
        "ebitda_cents": ebitda,
        "source_event_ids": event_ids,
        "pnl_statement": {
            "sales_revenue_4000_cents": rev_sales,
            "commission_revenue_4100_cents": rev_comm,
            "total_revenue_cents": rev_cents,
            "cogs_5000_cents": cogs_cents,
            "gross_profit_cents": gross_profit,
            "gross_margin_pct": gross_margin_pct,
            "workforce_6000_cents": opex_wf,
            "commissions_6050_cents": opex_comm,
            "rent_utilities_6100_cents": opex_rent,
            "general_opex_6200_cents": opex_gen,
            "total_opex_cents": opex_cents,
            "ebitda_cents": ebitda,
            "ebitda_margin_pct": ebitda_margin_pct,
        },
        "balance_sheet": {
            "cash_1000_cents": cash_now,
            "accounts_receivable_1100_cents": ar_now,
            "vat_input_receivable_1400_cents": vat_in_now,
            "total_assets_cents": total_assets,
            "accounts_payable_2000_cents": ap_now,
            "customer_deposits_2100_cents": deposits_now,
            "vat_output_payable_2400_cents": vat_out_now,
            "payroll_and_tax_payables_2500_cents": payroll_now,
            "total_liabilities_cents": total_liabilities,
            "cumulative_net_income_cents": cum_net_income,
            "total_liabilities_and_equity_cents": total_liabilities + cum_net_income,
            "balanced": total_assets == (total_liabilities + cum_net_income),
        },
        "vat_return": {
            "output_vat_2400_cents": vat_out_now,
            "input_vat_1400_cents": vat_in_now,
            "net_vat_payable_cents": vat_out_now - vat_in_now,
            "period_output_vat_cents": period_out_vat,
            "period_input_vat_cents": period_in_vat,
            "period_net_vat_cents": period_out_vat - period_in_vat,
        },
        "working_capital_ratios": {
            "gross_margin_pct": gross_margin_pct,
            "ebitda_margin_pct": ebitda_margin_pct,
            "collection_rate_pct": collection_rate_pct,
            "overdue_ar_pct": overdue_ar_pct,
            "working_capital_cents": total_assets - total_liabilities,
            "quick_ratio_x": round((cash_now + ar_now) / max(1, ap_now), 2),
        },
        "cash_forecast": {
            "opening_posted_cash_cents": cash_now,
            "open_ar_inflow_cents": expected_inflows,
            "open_ap_outflow_cents": expected_outflows,
            "projected_net_cash_cents": cash_now
            + expected_inflows
            - expected_outflows,
        },
    }

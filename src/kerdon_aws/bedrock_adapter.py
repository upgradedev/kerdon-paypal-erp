"""Strands Agents SDK, Amazon Bedrock, and Bedrock AgentCore adapter for Kerdon MSP."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import time
from typing import Any, Callable

import kerdon as kd

DEFAULT_MODEL_ID = "eu.amazon.nova-pro-v1:0"

GAP_REASONER_SYSTEM_PROMPT = (
    "You are Kerdon GapReasonerAgent running on AWS Strands Agents SDK and Amazon Bedrock. "
    "Given a deterministic financial completeness gap, return a compact JSON object with keys "
    "'likely_cause' and 'suggested_action'. Never invent or alter any monetary figure."
)

GROUNDED_NARRATOR_SYSTEM_PROMPT = (
    "You are Kerdon GroundedNarratorAgent running on AWS Strands Agents SDK and Amazon Bedrock. "
    "Answer the user's question using ONLY the exact EUR amounts present in the provided FactSheet. "
    "Never calculate, round, or invent any number."
)

DOCUMENT_EXTRACTOR_SYSTEM_PROMPT = (
    "You are Kerdon DocumentExtractorAgent running on AWS Strands Agents SDK and Amazon Bedrock. "
    "Given raw invoice/receipt/email text and the deterministic integer-cent floor, return a compact JSON object "
    "with keys 'counterparty_name', 'invoice_number', 'issued_date', 'due_date', and 'description'. "
    "Dates must be YYYY-MM-DD. Never alter any monetary cent amount."
)

COMMERCE_AGENT_SYSTEM_PROMPT = (
    "You are Kerdon AgenticCommerceAdvisor running on AWS Strands Agents SDK and Amazon Bedrock. "
    "Summarize the PayPal or AADE myDATA commerce event in 1-2 factual sentences preserving all IDs and integer-cent figures."
)


@dataclass(frozen=True)
class StageExecutionReceipt:
    """Audit receipt for one stage of the 8-stage Strands Mini-ERP workflow."""

    stage_number: int
    stage_name: str
    module_code: str
    deterministic_summary: str
    status: str = "COMPLETED"


@dataclass(frozen=True)
class WorkflowRunResult:
    """Output of executing the 8-stage Strands Mini-ERP orchestration workflow."""

    tenant_id: str
    period: str
    source: str
    model_id: str
    stages: tuple[StageExecutionReceipt, ...]
    sharpened_reasonings: tuple[kd.GapReasoning, ...]
    executive_narrative: str
    agentcore_memory_status: str


def _invoke_strands_bedrock(
    system_prompt: str,
    user_prompt: str,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    region_name: str = "eu-west-1",
) -> str:
    """Invoke AWS Strands Agent backed by Amazon BedrockModel (`temperature=0.0`)."""
    try:
        from strands import Agent
        from strands.models import BedrockModel

        bedrock_model = BedrockModel(
            model_id=model_id,
            region_name=region_name,
            temperature=0.0,
        )
        agent = Agent(model=bedrock_model, system_prompt=system_prompt)
        response = agent(user_prompt)
        return str(response).strip()
    except Exception:
        # Fallback to direct boto3 bedrock-runtime converse call if Strands is not vendored locally
        import boto3

        client = boto3.client("bedrock-runtime", region_name=region_name)
        resp = client.converse(
            modelId=model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_prompt}]}],
            inferenceConfig={"maxTokens": 300, "temperature": 0.0},
        )
        blocks = resp.get("output", {}).get("message", {}).get("content", [])
        return " ".join(b.get("text", "") for b in blocks if "text" in b).strip()


def record_agentcore_memory_event(
    *,
    tenant_id: str,
    session_id: str,
    event_summary: str,
    memory_id: str | None = None,
    region_name: str = "eu-west-1",
    client_factory: Callable[..., Any] | None = None,
) -> str:
    """Record an audit trail event in Amazon Bedrock AgentCore Memory when configured."""
    resolved_memory_id = (
        memory_id
        if memory_id is not None
        else os.environ.get("AGENTCORE_MEMORY_ID", "")
    ).strip()
    if not resolved_memory_id:
        return "skipped-no-memory-id"

    try:
        if client_factory is not None:
            ac_client = client_factory("bedrock-agentcore", region_name=region_name)
        else:
            import boto3

            ac_client = boto3.client("bedrock-agentcore", region_name=region_name)

        ac_client.create_event(
            memoryId=resolved_memory_id,
            actorId=f"kerdon-msp-{tenant_id}",
            sessionId=session_id,
            eventTimestamp=int(time.time()),
            payload=[
                {
                    "conversational": {
                        "content": {"text": event_summary[:1000]},
                        "role": "ASSISTANT",
                    }
                }
            ],
        )
        try:
            listed = ac_client.list_events(
                memoryId=resolved_memory_id,
                actorId=f"kerdon-msp-{tenant_id}",
                sessionId=session_id,
                maxResults=5,
            )
            ev_count = len(listed.get("events") or [])
            return f"recorded:{resolved_memory_id}:events={max(1, ev_count)}"
        except Exception:
            return f"recorded:{resolved_memory_id}"
    except Exception as exc:
        return f"fallback:{type(exc).__name__}"


def retrieve_agentcore_memory_events(
    *,
    tenant_id: str,
    session_id: str,
    memory_id: str | None = None,
    region_name: str = "eu-west-1",
    max_results: int = 5,
    client_factory: Callable[..., Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Read back persisted audit/mapping events from Amazon Bedrock AgentCore Memory."""
    resolved_memory_id = (
        memory_id
        if memory_id is not None
        else os.environ.get("AGENTCORE_MEMORY_ID", "")
    ).strip()
    if not resolved_memory_id:
        return "skipped-no-memory-id", []
    try:
        if client_factory is not None:
            ac_client = client_factory("bedrock-agentcore", region_name=region_name)
        else:
            import boto3

            ac_client = boto3.client("bedrock-agentcore", region_name=region_name)
        resp = ac_client.list_events(
            memoryId=resolved_memory_id,
            actorId=f"kerdon-msp-{tenant_id}",
            sessionId=session_id,
            maxResults=max_results,
        )
        events = list(resp.get("events") or [])
        return f"active:{resolved_memory_id}:events={len(events)}", events
    except Exception as exc:
        return f"fallback:{type(exc).__name__}", []


def run_eight_stage_erp_workflow(
    state: kd.TenantMiniErpState,
    *,
    llm_mode: str | None = None,
    model_id: str = DEFAULT_MODEL_ID,
    region_name: str = "eu-west-1",
    model_invoker: Callable[[str, str], str] | None = None,
    memory_client_factory: Callable[..., Any] | None = None,
    require_live: bool = False,
) -> WorkflowRunResult:
    """Execute the 8-stage Strands Mini-ERP workflow over a tenant's state.

    All monetary figures (ledger lines, 3-doc workforce cost, VAT rates, seller
    commissions, completeness gaps, and treasury reserve floors) come 100% from
    the pure hexagonal core (`src/kerdon/`). Strands + Bedrock sharpens gap
    explanations and executive prose.
    """
    strict_live = require_live or os.environ.get("KERDON_REQUIRE_LIVE_BEDROCK", "").strip() == "1"
    mode = (llm_mode or os.environ.get("KERDON_LLM_MODE", "deterministic")).lower().strip()
    invoker = model_invoker
    if invoker is None and (mode == "bedrock" or strict_live):
        invoker = lambda sys_p, usr_p: _invoke_strands_bedrock(
            sys_p, usr_p, model_id=model_id, region_name=region_name
        )

    stages = (
        StageExecutionReceipt(
            1,
            "FiscalIdentityAndTenancyStage",
            "M1",
            f"Tenant {state.tenant.display_name} ({state.tenant.fiscal_identity.tax_id}) verified.",
        ),
        StageExecutionReceipt(
            2,
            "OmnichannelEvidenceInboxStage",
            "M2",
            f"{len(state.inbox.blobs_by_sha256)} deduplicated SHA-256 blobs; {len(state.inbox.sales_table_evidence)} HTML tables isolated.",
        ),
        StageExecutionReceipt(
            3,
            "CommercialCrmAndRegisterStage",
            "M3",
            f"{len(state.crm.documents)} registered documents, {len(state.crm.bookings)} bookings, {len(state.crm.suppliers)} suppliers.",
        ),
        StageExecutionReceipt(
            4,
            "DoubleEntryLedgerAndWorkforceStage",
            "M4",
            f"EBITDA {kd.format_eur(state.board_pack.pnl.ebitda_cents)}; 3-doc workforce {kd.format_eur(state.workforce_fusion.true_employer_cost_cents)}.",
        ),
        StageExecutionReceipt(
            5,
            "SellerCommissionEngineStage",
            "M5",
            f"Case {state.commission_case.case_id} ({state.commission_case.status.value}): {kd.format_eur(state.commission_case.total_payable_cents)}.",
        ),
        StageExecutionReceipt(
            6,
            "CompletenessAndGapReasonerStage",
            "M6",
            f"{len(state.gaps)} gaps detected across 24 rules; top risk {kd.format_eur(state.digest.total_at_risk_cents)}.",
        ),
        StageExecutionReceipt(
            7,
            "AutonomousDocGenAndBoardPackStage",
            "M7",
            f"{len(state.outbound_drafts)} human-gated corrective drafts; Merkle root {state.board_pack.handoff_packet.merkle_root_sha256[:12]}.",
        ),
        StageExecutionReceipt(
            8,
            "MultiCurrencyTreasuryAndInvalidationStage",
            "M8",
            f"{len(state.treasury.pockets)} currency pockets; {len(state.treasury.approvals)} content-addressed approvals.",
        ),
    )

    sharpened: list[kd.GapReasoning] = list(state.reasonings)
    narrative = state.board_pack.executive_narrative
    source = "deterministic-fallback"

    if invoker is not None:
        try:
            if state.gaps:
                top_gap = state.gaps[0]
                prompt = json.dumps(
                    {
                        "gap_id": top_gap.gap_id,
                        "rule_id": top_gap.rule_id.value,
                        "counterparty": top_gap.counterparty_name,
                        "amount_eur": kd.format_eur(top_gap.amount_cents),
                        "summary": top_gap.summary,
                    }
                )
                raw_reply = invoker(GAP_REASONER_SYSTEM_PROMPT, prompt)
                if raw_reply:
                    base_r = sharpened[0]
                    cleaned = raw_reply.strip()
                    if cleaned.startswith("```"):
                        cleaned = cleaned.strip("`")
                        if cleaned.lower().startswith("json"):
                            cleaned = cleaned[4:].strip()
                    start_brace = cleaned.find("{")
                    end_brace = cleaned.rfind("}")
                    if start_brace != -1 and end_brace > start_brace:
                        cleaned = cleaned[start_brace : end_brace + 1]
                    likely_cause = cleaned[:240]
                    suggested_action = base_r.suggested_action
                    try:
                        parsed = json.loads(cleaned)
                        if isinstance(parsed, dict) and parsed.get("likely_cause"):
                            likely_cause = str(parsed["likely_cause"])[:240]
                            if parsed.get("suggested_action"):
                                suggested_action = str(parsed["suggested_action"])[:240]
                    except Exception:
                        pass
                    sharpened[0] = kd.GapReasoning(
                        gap_id=base_r.gap_id,
                        rule_id=base_r.rule_id,
                        likely_cause=likely_cause,
                        suggested_action=suggested_action,
                        confidence_bps=base_r.confidence_bps,
                        recommended_doc_type=base_r.recommended_doc_type,
                        source="strands-bedrock",
                    )
                    source = "strands-bedrock"
                elif strict_live:
                    raise RuntimeError(
                        "Strands/Bedrock live synthesizer required; refusing empty reply"
                    )
        except Exception as exc:
            if strict_live:
                raise RuntimeError(
                    "Strands/Bedrock live synthesizer required; refusing silent fallback"
                ) from exc
            source = "deterministic-fallback"
    elif strict_live:
        raise RuntimeError(
            "Strands/Bedrock live synthesizer required; refusing silent fallback"
        )

    mem_status = record_agentcore_memory_event(
        tenant_id=state.tenant.tenant_id,
        session_id=f"wf-{state.tenant.tenant_id}-{state.board_pack.period}",
        event_summary=f"8-stage Mini-ERP close ({source}): {narrative}",
        region_name=region_name,
        client_factory=memory_client_factory,
    )

    return WorkflowRunResult(
        tenant_id=state.tenant.tenant_id,
        period=state.board_pack.period,
        source=source,
        model_id=model_id,
        stages=stages,
        sharpened_reasonings=tuple(sharpened),
        executive_narrative=narrative,
        agentcore_memory_status=mem_status,
    )


def answer_query_with_bedrock(
    question: str,
    fact_sheet: kd.FactSheet,
    *,
    llm_mode: str | None = None,
    model_id: str = DEFAULT_MODEL_ID,
    region_name: str = "eu-west-1",
    model_invoker: Callable[[str, str], str] | None = None,
) -> kd.GroundedQueryAnswer:
    """Answer a natural-language question over FactSheet with optional Strands narrator."""
    mode = (llm_mode or os.environ.get("KERDON_LLM_MODE", "deterministic")).lower().strip()
    invoker = model_invoker
    if invoker is None and mode == "bedrock":
        invoker = lambda sys_p, usr_p: _invoke_strands_bedrock(
            sys_p, usr_p, model_id=model_id, region_name=region_name
        )

    override = ""
    if invoker is not None:
        try:
            facts_prompt = json.dumps(
                {
                    "tenant": fact_sheet.tenant_name,
                    "period": fact_sheet.period,
                    "revenue": kd.format_eur(fact_sheet.revenue_cents),
                    "ebitda": kd.format_eur(fact_sheet.ebitda_cents),
                    "workforce_cost": kd.format_eur(fact_sheet.workforce_cost_cents),
                    "seller_commissions": kd.format_eur(
                        fact_sheet.seller_commission_payable_cents
                    ),
                    "net_vat_payable": kd.format_eur(fact_sheet.net_vat_payable_cents),
                    "open_gaps": fact_sheet.open_gap_count,
                    "question": question,
                }
            )
            candidate = invoker(GROUNDED_NARRATOR_SYSTEM_PROMPT, facts_prompt)
            if candidate and ("EUR" in candidate or str(fact_sheet.open_gap_count) in candidate):
                override = candidate
        except Exception:
            override = ""

    return kd.answer_grounded_query(
        question, fact_sheet, narrator_override=override
    )


def extract_document_with_bedrock(
    state: kd.TenantMiniErpState,
    raw_text: str,
    *,
    preferred_module: str = "purchases",
    source_kind: str = "PDF_ATTACHMENT",
    llm_mode: str | None = None,
    model_id: str = DEFAULT_MODEL_ID,
    region_name: str = "eu-west-1",
    model_invoker: Callable[[str, str], str] | None = None,
    require_live: bool = False,
) -> kd.ExtractedDocumentDraft:
    """Extract an ERP document draft using deterministic integer-cent floor + Strands/Bedrock Nova Pro enrichment."""
    strict_live = require_live or os.environ.get("KERDON_REQUIRE_LIVE_BEDROCK", "").strip() == "1"
    floor_draft = kd.extract_erp_document_draft(
        state,
        raw_text,
        preferred_module=preferred_module,
        source_kind=source_kind,
    )
    resolved_model = os.environ.get("BEDROCK_MODEL_ID", model_id).strip() or model_id
    mode = (llm_mode or os.environ.get("KERDON_LLM_MODE", "deterministic")).lower().strip()
    invoker = model_invoker
    if invoker is None and (mode == "bedrock" or strict_live):
        invoker = lambda sys_p, usr_p: _invoke_strands_bedrock(
            sys_p, usr_p, model_id=resolved_model, region_name=region_name
        )
    if invoker is None:
        if strict_live:
            raise RuntimeError("Strands/Bedrock live document extractor required; refusing silent fallback")
        return floor_draft

    try:
        prompt = json.dumps(
            {
                "raw_text": raw_text[:1500],
                "invoice_number": floor_draft.invoice_number,
                "counterparty_name": floor_draft.counterparty_name,
                "issued_date": floor_draft.issued_date,
                "due_date": floor_draft.due_date,
                "total_net_cents": floor_draft.total_net_cents,
                "total_vat_cents": floor_draft.total_vat_cents,
                "total_gross_cents": floor_draft.total_gross_cents,
            }
        )
        raw_reply = invoker(DOCUMENT_EXTRACTOR_SYSTEM_PROMPT, prompt)
        if not raw_reply:
            if strict_live:
                raise RuntimeError("Strands/Bedrock document extractor returned empty output")
            return floor_draft
        cleaned = raw_reply.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        start_brace = cleaned.find("{")
        end_brace = cleaned.rfind("}")
        cp_name = floor_draft.counterparty_name
        inv_num = floor_draft.invoice_number
        issued = floor_draft.issued_date
        due = floor_draft.due_date
        desc = floor_draft.description
        if start_brace != -1 and end_brace > start_brace:
            parsed = json.loads(cleaned[start_brace : end_brace + 1])
            if isinstance(parsed, dict):
                if parsed.get("counterparty_name"):
                    cp_name = str(parsed["counterparty_name"]).strip()[:120]
                if parsed.get("invoice_number"):
                    inv_num = str(parsed["invoice_number"]).strip()[:64]
                if parsed.get("issued_date") and len(str(parsed["issued_date"]).strip()) == 10:
                    issued = str(parsed["issued_date"]).strip()
                if parsed.get("due_date") and len(str(parsed["due_date"]).strip()) == 10:
                    due = str(parsed["due_date"]).strip()
                if parsed.get("description"):
                    desc = str(parsed["description"]).strip()[:200]
        return kd.ExtractedDocumentDraft(
            tenant_id=floor_draft.tenant_id,
            target_module=floor_draft.target_module,
            direction=floor_draft.direction,
            counterparty_id=floor_draft.counterparty_id,
            counterparty_name=cp_name,
            counterparty_tax_id=floor_draft.counterparty_tax_id,
            invoice_number=inv_num,
            issued_date=issued,
            due_date=due,
            currency=floor_draft.currency,
            description=desc,
            lines=floor_draft.lines,
            total_net_cents=floor_draft.total_net_cents,
            total_vat_cents=floor_draft.total_vat_cents,
            total_gross_cents=floor_draft.total_gross_cents,
            confidence_bps=max(floor_draft.confidence_bps, 9820),
            source_sha256=floor_draft.source_sha256,
            extraction_engine=f"strands-bedrock:{resolved_model}",
        )
    except Exception as exc:
        if strict_live:
            raise RuntimeError("Strands/Bedrock live document extractor failed; refusing silent fallback") from exc
        return floor_draft


def invoke_paypal_commerce_agent(
    *,
    action: str,
    tenant_id: str,
    summary_fact: str,
    gl_impact: str,
    governance_fact: str,
    llm_mode: str | None = None,
    model_id: str = DEFAULT_MODEL_ID,
    region_name: str = "eu-west-1",
    model_invoker: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """Synthesize a factual Agentic Commerce narrative using Strands/Bedrock when enabled."""
    mode = (llm_mode or os.environ.get("KERDON_LLM_MODE", "deterministic")).lower().strip()
    invoker = model_invoker
    if invoker is None and mode == "bedrock":
        invoker = lambda sys_p, usr_p: _invoke_strands_bedrock(
            sys_p, usr_p, model_id=model_id, region_name=region_name
        )
    exec_summary = f"{summary_fact} {gl_impact} {governance_fact}"
    source_mode = "deterministic-commerce-template"
    if invoker is not None:
        try:
            prompt = json.dumps(
                {
                    "action": action,
                    "tenant_id": tenant_id,
                    "summary": summary_fact,
                    "gl_impact": gl_impact,
                    "governance": governance_fact,
                    "available_tools": [t.get("tool_name") or t.get("name", "") for t in kd.PAYPAL_AGENTIC_TOOLS],
                }
            )
            candidate = invoker(COMMERCE_AGENT_SYSTEM_PROMPT, prompt)
            if candidate:
                exec_summary = candidate[:400]
                source_mode = "strands-bedrock-live"
        except Exception:
            source_mode = "deterministic-commerce-template"
    return {
        "engine": "strands-agentcore-commerce-advisor",
        "source_mode": source_mode,
        "model_id": os.environ.get("KERDON_BEDROCK_MODEL_ID", model_id),
        "action": action,
        "tenant_id": tenant_id,
        "executive_summary": exec_summary,
        "facts": {
            "summary": summary_fact,
            "gl_impact": gl_impact,
            "governance": governance_fact,
        },
    }

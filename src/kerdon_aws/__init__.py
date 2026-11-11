"""AWS adapter layer for Kerdon MSP (Strands Agents SDK, Bedrock, AgentCore, DynamoDB, S3)."""
from __future__ import annotations

from .bedrock_adapter import (
    DEFAULT_MODEL_ID,
    StageExecutionReceipt,
    WorkflowRunResult,
    answer_query_with_bedrock,
    record_agentcore_memory_event,
    run_eight_stage_erp_workflow,
)
from .handlers import (
    dispatch_http_event,
    lambda_evaluator,
    lambda_reader,
    lambda_writer,
)
from .http_utils import (
    MAX_BODY_BYTES,
    PayloadTooLargeError,
    ValidationError,
    canonical_root_location,
    extract_http_route,
    html_reply,
    json_reply,
    parse_json_body,
    redirect_reply,
)
from .persistence import MultiTenantStore, get_store, reset_store
from .workspace_ui import render_workspace

__all__ = [
    "DEFAULT_MODEL_ID",
    "MAX_BODY_BYTES",
    "MultiTenantStore",
    "PayloadTooLargeError",
    "StageExecutionReceipt",
    "ValidationError",
    "WorkflowRunResult",
    "answer_query_with_bedrock",
    "canonical_root_location",
    "dispatch_http_event",
    "extract_http_route",
    "get_store",
    "html_reply",
    "json_reply",
    "lambda_evaluator",
    "lambda_reader",
    "lambda_writer",
    "parse_json_body",
    "record_agentcore_memory_event",
    "redirect_reply",
    "render_workspace",
    "reset_store",
    "run_eight_stage_erp_workflow",
]

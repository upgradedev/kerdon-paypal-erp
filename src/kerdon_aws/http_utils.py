"""HTTP API v2 helpers for Kerdon MSP with stage-prefix stripping, HEAD, and 16KB guard."""
from __future__ import annotations

import base64
import json
from typing import Any

MAX_BODY_BYTES = 16_384

CORS_HEADERS: dict[str, str] = {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET,HEAD,POST,OPTIONS",
    "access-control-allow-headers": "content-type,x-kerdon-actor,x-kerdon-role",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "cache-control": "no-store",
}


class ValidationError(ValueError):
    """Raised when an HTTP request body or parameter is malformed (HTTP 400)."""


class PayloadTooLargeError(ValueError):
    """Raised when an HTTP request body exceeds MAX_BODY_BYTES (HTTP 413)."""


def extract_http_route(event: dict[str, Any]) -> tuple[str, str]:
    """Extract (method, normalized_path) from API Gateway HTTP API v2 or REST v1 event.

    Strips any leading `/Prod` or `/$default` stage prefix so routes match identically
    whether invoked locally, via default stage, or via `/Prod/...`.
    """
    req_ctx = event.get("requestContext") or {}
    http_ctx = req_ctx.get("http") or {}
    method = str(
        http_ctx.get("method") or event.get("httpMethod") or "GET"
    ).upper().strip()
    raw_path = str(
        event.get("rawPath") or http_ctx.get("path") or event.get("path") or "/"
    ).strip()
    if "?" in raw_path:
        raw_path, qs = raw_path.split("?", 1)
        if not event.get("rawQueryString"):
            event["rawQueryString"] = qs

    stage = str(req_ctx.get("stage") or "").strip()
    if stage and stage != "$default" and raw_path.startswith(f"/{stage}"):
        raw_path = raw_path[len(stage) + 1 :] or "/"
    for prefix in ("/Prod/", "/Prod", "/prod/", "/prod"):
        if raw_path == prefix.rstrip("/"):
            raw_path = "/"
            break
        if raw_path.startswith(prefix):
            raw_path = "/" + raw_path[len(prefix) :]
            break

    if not raw_path.startswith("/"):
        raw_path = "/" + raw_path
    if len(raw_path) > 1 and raw_path.endswith("/"):
        raw_path = raw_path.rstrip("/")
    return method, raw_path


def parse_json_body(event: dict[str, Any]) -> dict[str, Any]:
    """Validate and parse an HTTP event body as a JSON object (`dict`).

    Enforces a strict 16 KB payload limit (HTTP 413) and rejects non-object JSON
    payloads such as `[]`, strings, or numbers with `ValidationError` (HTTP 400).
    """
    raw = event.get("body")
    if raw is None or raw == "":
        return {}

    if isinstance(raw, dict):
        encoded_len = len(json.dumps(raw).encode("utf-8"))
        if encoded_len > MAX_BODY_BYTES:
            raise PayloadTooLargeError(
                f"Request body ({encoded_len} bytes) exceeds 16384 byte limit"
            )
        return dict(raw)

    if not isinstance(raw, str):
        raise ValidationError("Request body must be a JSON object")

    if event.get("isBase64Encoded"):
        try:
            decoded_bytes = base64.b64decode(raw, validate=True)
        except Exception as exc:
            raise ValidationError("Invalid base64 request body") from exc
        if len(decoded_bytes) > MAX_BODY_BYTES:
            raise PayloadTooLargeError(
                f"Decoded body ({len(decoded_bytes)} bytes) exceeds 16384 byte limit"
            )
        try:
            raw_str = decoded_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError("Request body must be valid UTF-8") from exc
    else:
        raw_bytes = raw.encode("utf-8")
        if len(raw_bytes) > MAX_BODY_BYTES:
            raise PayloadTooLargeError(
                f"Request body ({len(raw_bytes)} bytes) exceeds 16384 byte limit"
            )
        raw_str = raw

    if not raw_str.strip():
        return {}
    try:
        parsed = json.loads(raw_str)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Malformed JSON body: {exc.msg}") from exc

    if not isinstance(parsed, dict):
        raise ValidationError("Request body must be a JSON object (dict), not list or scalar")
    return parsed


def json_reply(
    status: int, payload: dict[str, Any], *, head_only: bool = False
) -> dict[str, Any]:
    """Construct an API Gateway v2 JSON response."""
    body_str = "" if head_only else json.dumps(payload, sort_keys=True)
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json; charset=utf-8", **CORS_HEADERS},
        "body": body_str,
    }


def html_reply(
    status: int, html: str, *, head_only: bool = False
) -> dict[str, Any]:
    """Construct an API Gateway v2 HTML response with strict CSP."""
    return {
        "statusCode": status,
        "headers": {
            "content-type": "text/html; charset=utf-8",
            "content-security-policy": (
                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; base-uri 'none'; form-action 'none'"
            ),
            **CORS_HEADERS,
        },
        "body": "" if head_only else html,
    }


def canonical_root_location(event: dict[str, Any]) -> str:
    """Return canonical `/` redirect target, preserving `/Prod/` stage prefix when present."""
    req_ctx = event.get("requestContext") or {}
    stage = str(req_ctx.get("stage") or "").strip()
    raw_path = str(event.get("rawPath") or event.get("path") or "").strip()
    if stage in ("Prod", "prod") or raw_path.startswith(("/Prod/", "/prod/")):
        return "/Prod/"
    return "/"


def redirect_reply(
    location: str, *, status: int = 301, head_only: bool = False
) -> dict[str, Any]:
    """Construct an HTTP 301/302 canonical redirect response."""
    return {
        "statusCode": status,
        "headers": {
            "location": location,
            "content-type": "text/plain; charset=utf-8",
            **CORS_HEADERS,
        },
        "body": "" if head_only else f"Redirecting to {location}\n",
    }


def static_asset_reply(
    status: int, content_type: str, body: str, *, head_only: bool = False
) -> dict[str, Any]:
    """Construct an immutable fingerprinted static asset response (Vite + S3)."""
    return {
        "statusCode": status,
        "headers": {
            **CORS_HEADERS,
            "content-type": content_type,
            "cache-control": "public, max-age=31536000, immutable",
            "x-kerdon-asset-origin": "s3-vite-bundle",
        },
        "body": "" if head_only else body,
    }

"""Multi-tenant DynamoDB and S3 persistence adapter for Kerdon MSP.

Guarantees:
- Zero suppressed storage errors: when a table/bucket or client is configured,
  any write/read failure raises `PersistenceError` or `VersionConflictError`.
- Paginated journal hydration (`LastEvaluatedKey` loop) with strict ordering.
- Fail-closed journal replay: stops immediately on replay error or cross-tenant
  journal mismatch and NEVER marks a failed entry as applied.
- Conditional/optimistic-lock entity versioning (`expected_version`) and
  globally scoped tenant idempotency keys (`IDEM#<tenant>#<scope>#<key>`).
- Deterministic tenant backup and SHA-256 verified restore.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
import time
from typing import Any, Callable
import uuid

import kerdon as kd

from .identity import SubjectMembershipRegistry


class PersistenceError(RuntimeError):
    """Raised (HTTP 503) when a configured DynamoDB or S3 operation fails."""


class VersionConflictError(RuntimeError):
    """Raised (HTTP 409) on optimistic lock version mismatch or conditional write failure."""


class PersistenceReplayError(PersistenceError):
    """Raised when journal hydration encounters a corrupt, failed, or cross-tenant entry."""


def _extract_tenant_from_path(path: str) -> str:
    parts = [p for p in str(path or "").split("/") if p]
    if len(parts) >= 2 and parts[0] == "tenants" and parts[1] != "onboard":
        return parts[1]
    return "GLOBAL"


@dataclass
class MultiTenantStore:
    """Authoritative runtime store backed by in-memory state and live DynamoDB/S3."""

    workspace: kd.MspDemoWorkspace = field(
        default_factory=kd.build_default_msp_workspace
    )
    identity_registry: SubjectMembershipRegistry = field(
        default_factory=SubjectMembershipRegistry
    )
    app_table_name: str = field(
        default_factory=lambda: os.environ.get("KERDON_APP_TABLE", "")
    )
    approvals_table_name: str = field(
        default_factory=lambda: os.environ.get("KERDON_APPROVALS_TABLE", "")
    )
    evidence_bucket_name: str = field(
        default_factory=lambda: os.environ.get("EVIDENCE_BUCKET", "")
    )
    region_name: str = field(
        default_factory=lambda: os.environ.get("AWS_REGION", "eu-west-1")
    )
    ddb_client: Any = None
    s3_client: Any = None
    dynamo_writes: list[dict[str, Any]] = field(default_factory=list)
    s3_puts: list[dict[str, Any]] = field(default_factory=list)
    s3_blobs: dict[str, bytes] = field(default_factory=dict)
    applied_journal_sks: set[str] = field(default_factory=set)
    journal_log: list[dict[str, Any]] = field(default_factory=list)
    entity_versions: dict[str, int] = field(default_factory=dict)
    idempotency_claims: dict[str, str] = field(default_factory=dict)
    last_reset_epoch_ns: int = 0
    _replaying_journal: bool = False

    def _get_ddb(self) -> Any:
        if self.ddb_client is not None:
            return self.ddb_client
        import boto3

        return boto3.client("dynamodb", region_name=self.region_name)

    def _get_s3(self) -> Any:
        if self.s3_client is not None:
            return self.s3_client
        import boto3

        return boto3.client("s3", region_name=self.region_name)

    @staticmethod
    def _raise_ddb_error(exc: Exception, operation: str) -> None:
        msg = str(exc)
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        if "ConditionalCheckFailed" in msg or "ConditionalCheckFailed" in code:
            raise VersionConflictError(
                f"DynamoDB conditional check failed during {operation}: {msg}"
            ) from exc
        raise PersistenceError(
            f"Durable DynamoDB {operation} failed: {msg}"
        ) from exc

    def get_tenant_state(self, tenant_id: str) -> kd.TenantMiniErpState:
        state = self.workspace.tenant_states.get(tenant_id)
        if state is None:
            raise KeyError(f"Unknown tenant_id: {tenant_id}")
        return state

    def put_versioned_entity(
        self,
        tenant_id: str,
        entity_kind: str,
        entity_id: str,
        payload: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> int:
        """Conditionally write a versioned entity and return the new version integer."""
        vkey = f"{tenant_id}:{entity_kind}:{entity_id}"
        current_ver = self.entity_versions.get(vkey, 0)
        if expected_version is not None and current_ver != expected_version:
            raise VersionConflictError(
                f"Version conflict on {vkey}: expected v{expected_version}, current is v{current_ver}"
            )
        new_ver = current_ver + 1
        item = {
            "pk": f"TENANT#{tenant_id}",
            "sk": f"ENTITY#{entity_kind}#{entity_id}",
            "tenant_id": tenant_id,
            "record_kind": entity_kind,
            "record_id": entity_id,
            "entity_version": new_ver,
            "payload_json": json.dumps(payload, sort_keys=True),
        }
        if (self.app_table_name or self.ddb_client is not None) and not self._replaying_journal:
            try:
                ddb = self._get_ddb()
                put_kwargs: dict[str, Any] = {
                    "TableName": self.app_table_name or "kerdon-msp-app",
                    "Item": {
                        "pk": {"S": item["pk"]},
                        "sk": {"S": item["sk"]},
                        "tenant_id": {"S": tenant_id},
                        "record_kind": {"S": entity_kind},
                        "record_id": {"S": entity_id},
                        "entity_version": {"N": str(new_ver)},
                        "payload_json": {"S": item["payload_json"]},
                    },
                }
                if current_ver == 0:
                    put_kwargs["ConditionExpression"] = (
                        "attribute_not_exists(entity_version) OR entity_version = :zero"
                    )
                    put_kwargs["ExpressionAttributeValues"] = {":zero": {"N": "0"}}
                else:
                    put_kwargs["ConditionExpression"] = "entity_version = :expected"
                    put_kwargs["ExpressionAttributeValues"] = {
                        ":expected": {"N": str(current_ver)}
                    }
                ddb.put_item(**put_kwargs)
            except Exception as exc:
                self._raise_ddb_error(exc, f"put_versioned_entity({vkey})")
        self.entity_versions[vkey] = new_ver
        self.dynamo_writes.append(item)
        return new_ver

    def claim_idempotency_key(
        self,
        tenant_id: str,
        scope: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> str:
        """Claim a globally scoped tenant idempotency lock before mutating state."""
        clean_key = str(idempotency_key or "").strip()
        if not clean_key:
            raise ValueError("idempotency_key must not be empty")
        global_id = f"IDEM#{tenant_id}#{scope}#{clean_key}"
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        existing_hash = self.idempotency_claims.get(global_id)
        if existing_hash is not None:
            if existing_hash != payload_hash:
                raise VersionConflictError(
                    f"Idempotency key '{clean_key}' reused with different payload in scope {scope}"
                )
            raise kd.DuplicateIdempotencyError(
                f"Duplicate request blocked by idempotency key '{clean_key}' in scope {scope}"
            )
        if (self.app_table_name or self.ddb_client is not None) and not self._replaying_journal:
            try:
                ddb = self._get_ddb()
                ddb.put_item(
                    TableName=self.app_table_name or "kerdon-msp-app",
                    Item={
                        "pk": {"S": f"TENANT#{tenant_id}"},
                        "sk": {"S": global_id},
                        "tenant_id": {"S": tenant_id},
                        "payload_sha256": {"S": payload_hash},
                    },
                    ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
                )
            except Exception as exc:
                self._raise_ddb_error(exc, f"claim_idempotency_key({global_id})")
        self.idempotency_claims[global_id] = payload_hash
        return global_id

    def unit_of_work(
        self, tenant_id: str, actor_id: str = "system"
    ) -> kd.DomainUnitOfWork:
        """Open an atomic transactional Unit of Work with automatic rollback and Outbox."""
        state = self.get_tenant_state(tenant_id)
        return kd.DomainUnitOfWork(
            state,
            tenant_id=tenant_id,
            actor_id=actor_id,
            commit_batch_fn=self._commit_uow_batch,
        )

    def _commit_uow_batch(
        self,
        entities: list[kd.StagedEntityWrite],
        outbox_events: list[kd.StagedOutboxEvent],
        idempotency_claim: tuple[str, str] | None,
    ) -> dict[str, int]:
        """Atomically validate and commit staged entity writes, outbox events, and idempotency lock."""
        pending_versions: dict[str, int] = {}
        staged_items: list[dict[str, Any]] = []
        transact_items: list[dict[str, Any]] = []
        table_name = self.app_table_name or "kerdon-msp-app"

        # 1. Pre-validate idempotency lock if present
        idem_global_id = ""
        idem_hash = ""
        if idempotency_claim is not None:
            scope, clean_key = idempotency_claim
            tenant_id = entities[0].tenant_id if entities else "GLOBAL"
            idem_global_id = f"IDEM#{tenant_id}#{scope}#{clean_key}"
            idem_hash = hashlib.sha256(
                json.dumps([e.payload for e in entities], sort_keys=True).encode("utf-8")
            ).hexdigest()
            existing_hash = self.idempotency_claims.get(idem_global_id)
            if existing_hash is not None:
                if existing_hash != idem_hash:
                    raise VersionConflictError(
                        f"Idempotency key '{clean_key}' reused with different payload in scope {scope}"
                    )
                raise kd.DuplicateIdempotencyError(
                    f"Duplicate request blocked by idempotency key '{clean_key}' in scope {scope}"
                )
            transact_items.append(
                {
                    "Put": {
                        "TableName": table_name,
                        "Item": {
                            "pk": {"S": f"TENANT#{tenant_id}"},
                            "sk": {"S": idem_global_id},
                            "tenant_id": {"S": tenant_id},
                            "payload_sha256": {"S": idem_hash},
                        },
                        "ConditionExpression": "attribute_not_exists(pk) AND attribute_not_exists(sk)",
                    }
                }
            )

        # 2. Pre-validate all optimistic entity versions before any write
        for ent in entities:
            vkey = f"{ent.tenant_id}:{ent.entity_kind}:{ent.entity_id}"
            current_ver = pending_versions.get(vkey, self.entity_versions.get(vkey, 0))
            if ent.expected_version is not None and current_ver != ent.expected_version:
                raise VersionConflictError(
                    f"Version conflict on {vkey}: expected v{ent.expected_version}, current is v{current_ver}"
                )
            new_ver = current_ver + 1
            pending_versions[vkey] = new_ver
            item = {
                "pk": f"TENANT#{ent.tenant_id}",
                "sk": f"ENTITY#{ent.entity_kind}#{ent.entity_id}",
                "tenant_id": ent.tenant_id,
                "record_kind": ent.entity_kind,
                "record_id": ent.entity_id,
                "entity_version": new_ver,
                "payload_json": json.dumps(ent.payload, sort_keys=True),
            }
            staged_items.append(item)
            put_spec: dict[str, Any] = {
                "TableName": table_name,
                "Item": {
                    "pk": {"S": item["pk"]},
                    "sk": {"S": item["sk"]},
                    "tenant_id": {"S": ent.tenant_id},
                    "record_kind": {"S": ent.entity_kind},
                    "record_id": {"S": ent.entity_id},
                    "entity_version": {"N": str(new_ver)},
                    "payload_json": {"S": item["payload_json"]},
                },
            }
            if current_ver == 0:
                put_spec["ConditionExpression"] = (
                    "attribute_not_exists(entity_version) OR entity_version = :zero"
                )
                put_spec["ExpressionAttributeValues"] = {":zero": {"N": "0"}}
            else:
                put_spec["ConditionExpression"] = "entity_version = :expected"
                put_spec["ExpressionAttributeValues"] = {
                    ":expected": {"N": str(current_ver)}
                }
            transact_items.append({"Put": put_spec})

        # 3. Stage Transactional Outbox items in the same atomic batch
        for obx in outbox_events:
            obx_item = {
                "pk": f"TENANT#{obx.tenant_id}",
                "sk": f"OUTBOX#{obx.outbox_id}",
                "tenant_id": obx.tenant_id,
                "record_kind": "OUTBOX_EVENT",
                "record_id": obx.outbox_id,
                "event_type": obx.event_type,
                "aggregate_id": obx.aggregate_id,
                "payload_sha256": obx.payload_sha256,
                "payload_json": json.dumps(obx.payload, sort_keys=True),
            }
            staged_items.append(obx_item)
            transact_items.append(
                {
                    "Put": {
                        "TableName": table_name,
                        "Item": {
                            "pk": {"S": obx_item["pk"]},
                            "sk": {"S": obx_item["sk"]},
                            "tenant_id": {"S": obx.tenant_id},
                            "record_kind": {"S": "OUTBOX_EVENT"},
                            "record_id": {"S": obx.outbox_id},
                            "event_type": {"S": obx.event_type},
                            "aggregate_id": {"S": obx.aggregate_id},
                            "payload_sha256": {"S": obx.payload_sha256},
                            "payload_json": {"S": obx_item["payload_json"]},
                        },
                    }
                }
            )

        # 4. Execute atomic DynamoDB TransactWriteItems when configured
        if (
            (self.app_table_name or self.ddb_client is not None)
            and not self._replaying_journal
            and transact_items
        ):
            try:
                ddb = self._get_ddb()
                if hasattr(ddb, "transact_write_items"):
                    ddb.transact_write_items(TransactItems=transact_items)
                else:
                    for t_item in transact_items:
                        ddb.put_item(**t_item["Put"])
            except Exception as exc:
                self._raise_ddb_error(exc, "transact_write_items(uow_batch)")

        # 5. Update in-memory version and outbox tables only after durable commit succeeds
        for vkey, new_ver in pending_versions.items():
            self.entity_versions[vkey] = new_ver
        if idem_global_id:
            self.idempotency_claims[idem_global_id] = idem_hash
        self.dynamo_writes.extend(staged_items)
        return pending_versions

    def persist_audit_record(
        self, tenant_id: str, record_kind: str, record_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Write an item to the tenant-partitioned DynamoDB table when configured."""
        item = {
            "pk": f"TENANT#{tenant_id}",
            "sk": f"{record_kind}#{record_id}",
            "tenant_id": tenant_id,
            "record_kind": record_kind,
            "record_id": record_id,
            "payload_json": json.dumps(payload, sort_keys=True),
        }
        if (self.app_table_name or self.ddb_client is not None) and not self._replaying_journal:
            try:
                ddb = self._get_ddb()
                ddb.put_item(
                    TableName=self.app_table_name or "kerdon-msp-app",
                    Item={
                        "pk": {"S": item["pk"]},
                        "sk": {"S": item["sk"]},
                        "tenant_id": {"S": tenant_id},
                        "record_kind": {"S": record_kind},
                        "record_id": {"S": record_id},
                        "payload_json": {"S": item["payload_json"]},
                    },
                )
            except Exception as exc:
                self._raise_ddb_error(exc, f"persist_audit_record({record_kind}#{record_id})")
        self.dynamo_writes.append(item)
        return item

    def persist_approval_state(
        self,
        approval_id: str,
        tenant_id: str,
        state_str: str,
        evidence_sha256: str,
    ) -> None:
        """Write approval lock state to `kerdon-msp-approvals` when configured."""
        if self._replaying_journal or not (
            self.approvals_table_name or self.ddb_client is not None
        ):
            return
        try:
            ddb = self._get_ddb()
            ddb.put_item(
                TableName=self.approvals_table_name or "kerdon-msp-approvals",
                Item={
                    "pk": {"S": f"APPROVAL#{approval_id}"},
                    "tenant_id": {"S": tenant_id},
                    "approval_state": {"S": state_str},
                    "evidence_sha256": {"S": evidence_sha256},
                    "updated_epoch_ns": {"N": str(time.time_ns())},
                },
            )
        except Exception as exc:
            self._raise_ddb_error(exc, f"persist_approval_state({approval_id})")

    def append_journal_mutation(
        self, path: str, body: dict[str, Any], role: str, *, tenant_id: str | None = None
    ) -> str:
        """Append a mutation command to DynamoDB `WORKSPACE#JOURNAL` for cross-Lambda hydration."""
        resolved_tid = tenant_id or _extract_tenant_from_path(path)
        ts_ns = time.time_ns()
        sk = f"SEQ#{ts_ns:020d}#{uuid.uuid4().hex[:8]}"
        entry = {
            "sk": sk,
            "seq_ns": ts_ns,
            "tenant_id": resolved_tid,
            "path": path,
            "role": role,
            "body_json": json.dumps(body, sort_keys=True),
        }
        if self._replaying_journal:
            return sk
        if self.app_table_name or self.ddb_client is not None:
            try:
                ddb = self._get_ddb()
                ddb.put_item(
                    TableName=self.app_table_name or "kerdon-msp-app",
                    Item={
                        "pk": {"S": "WORKSPACE#JOURNAL"},
                        "sk": {"S": sk},
                        "seq_ns": {"N": str(ts_ns)},
                        "tenant_id": {"S": resolved_tid},
                        "path": {"S": path},
                        "role": {"S": role},
                        "body_json": {"S": entry["body_json"]},
                    },
                    ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
                )
            except Exception as exc:
                self._raise_ddb_error(exc, f"append_journal_mutation({sk})")
        self.applied_journal_sks.add(sk)
        self.journal_log.append(entry)
        return sk

    def write_journal_reset(self) -> None:
        """Record a workspace reset epoch in DynamoDB so all Lambda functions reset cleanly."""
        if self._replaying_journal:
            return
        ts_ns = time.time_ns()
        if self.app_table_name or self.ddb_client is not None:
            try:
                ddb = self._get_ddb()
                ddb.put_item(
                    TableName=self.app_table_name or "kerdon-msp-app",
                    Item={
                        "pk": {"S": "WORKSPACE#JOURNAL"},
                        "sk": {"S": "META#RESET"},
                        "reset_epoch_ns": {"N": str(ts_ns)},
                    },
                )
            except Exception as exc:
                self._raise_ddb_error(exc, "write_journal_reset")
        self.last_reset_epoch_ns = ts_ns
        self.applied_journal_sks.clear()
        self.journal_log.clear()
        self.entity_versions.clear()
        self.idempotency_claims.clear()

    def sync_from_dynamodb(
        self,
        replay_fn: Callable[[str, dict[str, Any], str], None],
        reset_callback: Callable[[], None],
    ) -> int:
        """Hydrate mutations written by `WriterFunction` into `Reader`/`Evaluator` via paginated Query."""
        if self._replaying_journal or not (
            self.app_table_name or self.ddb_client is not None
        ):
            return 0
        items: list[dict[str, Any]] = []
        last_key: dict[str, Any] | None = None
        try:
            ddb = self._get_ddb()
            while True:
                query_kwargs: dict[str, Any] = {
                    "TableName": self.app_table_name or "kerdon-msp-app",
                    "KeyConditionExpression": "pk = :pk",
                    "ExpressionAttributeValues": {":pk": {"S": "WORKSPACE#JOURNAL"}},
                    "ConsistentRead": True,
                }
                if last_key is not None:
                    query_kwargs["ExclusiveStartKey"] = last_key
                resp = ddb.query(**query_kwargs)
                items.extend(resp.get("Items", []))
                last_key = resp.get("LastEvaluatedKey")
                if not last_key:
                    break
        except Exception as exc:
            self._raise_ddb_error(exc, "sync_from_dynamodb")

        remote_reset_ns = 0
        seq_items: list[tuple[int, str, str, str, str, str]] = []
        for it in items:
            sk = it.get("sk", {}).get("S", "")
            if sk == "META#RESET":
                remote_reset_ns = int(it.get("reset_epoch_ns", {}).get("N", "0"))
            elif sk.startswith("SEQ#"):
                seq_ns = int(it.get("seq_ns", {}).get("N", "0"))
                path = it.get("path", {}).get("S", "")
                role = it.get("role", {}).get("S", "MSP_FINOPS_DIRECTOR")
                body_json = it.get("body_json", {}).get("S", "{}")
                item_tid = it.get("tenant_id", {}).get("S", "")
                seq_items.append((seq_ns, sk, path, role, body_json, item_tid))

        if remote_reset_ns > self.last_reset_epoch_ns:
            self._replaying_journal = True
            try:
                reset_callback()
                self.applied_journal_sks.clear()
                self.journal_log.clear()
                self.entity_versions.clear()
                self.idempotency_claims.clear()
                self.last_reset_epoch_ns = remote_reset_ns
            finally:
                self._replaying_journal = False

        seq_items.sort(key=lambda x: (x[0], x[1]))
        replayed_count = 0
        self._replaying_journal = True
        try:
            for seq_ns, sk, path, role, body_json, item_tid in seq_items:
                if seq_ns <= self.last_reset_epoch_ns:
                    continue
                if sk in self.applied_journal_sks:
                    continue
                expected_tid = _extract_tenant_from_path(path)
                if item_tid and expected_tid != "GLOBAL" and item_tid != expected_tid:
                    raise PersistenceReplayError(
                        f"Journal tenant segregation violation on {sk}: item tenant '{item_tid}' != route tenant '{expected_tid}'"
                    )
                try:
                    parsed_body = json.loads(body_json)
                except Exception as exc:
                    raise PersistenceReplayError(
                        f"Corrupt JSON in journal entry {sk}: {exc}"
                    ) from exc
                if not isinstance(parsed_body, dict):
                    raise PersistenceReplayError(
                        f"Journal entry {sk} body must be a JSON object"
                    )
                body_tid = str(parsed_body.get("tenant_id") or "").strip()
                if body_tid and expected_tid != "GLOBAL" and body_tid != expected_tid:
                    raise PersistenceReplayError(
                        f"Cross-tenant journal payload in {sk}: body tenant '{body_tid}' != route tenant '{expected_tid}'"
                    )
                try:
                    replay_fn(path, parsed_body, role)
                except Exception as exc:
                    raise PersistenceReplayError(
                        f"Failed to replay journal entry {sk} ({path}): {exc}"
                    ) from exc
                self.applied_journal_sks.add(sk)
                replayed_count += 1
        finally:
            self._replaying_journal = False
        return replayed_count

    def persist_evidence_blob(
        self, tenant_id: str, sha256: str, raw_bytes: bytes, mime_type: str
    ) -> str:
        """Store content-addressed evidence bytes in S3 when configured."""
        s3_key = f"tenants/{tenant_id}/blobs/{sha256[:2]}/{sha256}"
        if (self.evidence_bucket_name or self.s3_client is not None) and not self._replaying_journal:
            try:
                s3 = self._get_s3()
                s3.put_object(
                    Bucket=self.evidence_bucket_name or "kerdon-msp-evidence",
                    Key=s3_key,
                    Body=raw_bytes,
                    ContentType=mime_type,
                )
            except Exception as exc:
                raise PersistenceError(
                    f"Durable S3 put_object failed for {s3_key}: {exc}"
                ) from exc
        self.s3_puts.append(
            {
                "tenant_id": tenant_id,
                "sha256": sha256,
                "s3_key": s3_key,
                "size_bytes": len(raw_bytes),
                "mime_type": mime_type,
            }
        )
        self.s3_blobs[s3_key] = raw_bytes
        return s3_key

    def export_tenant_backup(self, tenant_id: str) -> dict[str, Any]:
        """Export a deterministic, SHA-256 checksummed backup bundle for `tenant_id`."""
        state = self.get_tenant_state(tenant_id)
        tenant_journal = [
            e for e in self.journal_log if e.get("tenant_id") in (tenant_id, "GLOBAL")
        ]
        tenant_versions = {
            k: v
            for k, v in self.entity_versions.items()
            if k.startswith(f"{tenant_id}:")
        }
        tenant_audits = [
            w for w in self.dynamo_writes if w.get("tenant_id") == tenant_id
        ]
        core_data = {
            "tenant_id": tenant_id,
            "slug": state.tenant.slug,
            "journal_entries": tenant_journal,
            "entity_versions": tenant_versions,
            "audit_records": tenant_audits,
            "ledger_event_count": len(state.ledger.events),
            "document_count": len(state.crm.documents),
        }
        canonical = json.dumps(core_data, sort_keys=True).encode("utf-8")
        checksum = hashlib.sha256(canonical).hexdigest()
        return {**core_data, "backup_sha256": checksum}

    def verify_and_restore_backup(
        self,
        backup_bundle: dict[str, Any],
        replay_fn: Callable[[str, dict[str, Any], str], None],
    ) -> dict[str, Any]:
        """Verify backup SHA-256 integrity and replay journal mutations onto fresh state."""
        provided_sha = str(backup_bundle.get("backup_sha256") or "")
        core_data = {k: v for k, v in backup_bundle.items() if k != "backup_sha256"}
        expected_sha = hashlib.sha256(
            json.dumps(core_data, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if not provided_sha or provided_sha != expected_sha:
            raise PersistenceReplayError("Backup bundle SHA-256 integrity check failed")
        entries = list(core_data.get("journal_entries") or [])
        entries.sort(key=lambda e: (int(e.get("seq_ns", 0)), str(e.get("sk", ""))))
        replayed = 0
        self._replaying_journal = True
        try:
            for entry in entries:
                sk = str(entry.get("sk") or "")
                if sk in self.applied_journal_sks:
                    continue
                body = json.loads(str(entry.get("body_json") or "{}"))
                replay_fn(str(entry.get("path") or ""), body, str(entry.get("role") or "MSP_FINOPS_DIRECTOR"))
                self.applied_journal_sks.add(sk)
                self.journal_log.append(entry)
                replayed += 1
        finally:
            self._replaying_journal = False
        for k, v in (core_data.get("entity_versions") or {}).items():
            self.entity_versions[str(k)] = int(v)
        return {"restored_tenant_id": core_data.get("tenant_id"), "replayed_entries": replayed}

    def save_snapshot(self, tenant_id: str) -> dict[str, Any]:
        """Persist a deterministic snapshot for `tenant_id` (WorkspaceRepositoryPort)."""
        state = self.get_tenant_state(tenant_id)
        return self.persist_audit_record(
            tenant_id,
            "SNAPSHOT",
            state.board_pack.period,
            {
                "period": state.board_pack.period,
                "ebitda_cents": state.board_pack.pnl.ebitda_cents,
                "merkle_root_sha256": state.board_pack.handoff_packet.merkle_root_sha256,
            },
        )

    def put_evidence_blob(
        self,
        tenant_id: str,
        sha256_hex: str,
        raw_bytes: bytes,
        mime_type: str = "application/octet-stream",
    ) -> str:
        """Store raw evidence bytes and return an addressable URI (EvidenceBlobStorePort)."""
        return self.persist_evidence_blob(tenant_id, sha256_hex, raw_bytes, mime_type)


_GLOBAL_STORE: MultiTenantStore | None = None


def get_store() -> MultiTenantStore:
    global _GLOBAL_STORE
    if _GLOBAL_STORE is None:
        _GLOBAL_STORE = MultiTenantStore()
    return _GLOBAL_STORE


def reset_store() -> MultiTenantStore:
    global _GLOBAL_STORE
    _GLOBAL_STORE = MultiTenantStore()
    return _GLOBAL_STORE

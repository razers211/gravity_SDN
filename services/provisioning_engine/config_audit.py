"""
Configuration Audit Engine.

Maintains config snapshots, computes diffs between versions,
and provides rollback audit trails for all NETCONF transactions.
"""

from __future__ import annotations

import difflib
import logging
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ConfigSnapshot(BaseModel):
    """A point-in-time configuration snapshot for a device."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    device_id: str
    device_hostname: str = ""
    config_type: str = Field(default="running", examples=["running", "candidate", "startup"])
    config_xml: str = ""
    captured_at: datetime = Field(default_factory=datetime.utcnow)
    triggered_by: str = Field(default="system", examples=["system", "user", "provisioning", "ztp"])
    transaction_id: str | None = None
    version: int = 1


class ConfigDiff(BaseModel):
    """Diff between two configuration snapshots."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    device_id: str
    device_hostname: str = ""
    before_snapshot_id: str
    after_snapshot_id: str
    diff_lines: list[str] = Field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    modifications: int = 0
    computed_at: datetime = Field(default_factory=datetime.utcnow)


class AuditEntry(BaseModel):
    """Audit trail entry for a configuration change."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    device_id: str
    device_hostname: str = ""
    action: str = Field(examples=["commit", "rollback", "ztp-deploy", "intent-provision"])
    transaction_id: str | None = None
    user: str = "system"
    snapshot_before_id: str | None = None
    snapshot_after_id: str | None = None
    status: str = Field(default="success", examples=["success", "failed", "rolled-back"])
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: dict[str, Any] = Field(default_factory=dict)


class ConfigAuditEngine:
    """
    Configuration audit engine for tracking all config changes.

    Stores rolling snapshots per device, computes unified diffs,
    and maintains a full audit trail.
    """

    def __init__(self):
        self._snapshots: dict[str, list[ConfigSnapshot]] = {}  # device_id → [snapshots]
        self._audit_log: list[AuditEntry] = []

    def capture_snapshot(
        self,
        device_id: str,
        device_hostname: str,
        config_xml: str,
        config_type: str = "running",
        triggered_by: str = "system",
        transaction_id: str | None = None,
    ) -> ConfigSnapshot:
        """Capture a new configuration snapshot."""
        device_snapshots = self._snapshots.setdefault(device_id, [])
        version = len(device_snapshots) + 1

        snapshot = ConfigSnapshot(
            device_id=device_id,
            device_hostname=device_hostname,
            config_type=config_type,
            config_xml=config_xml,
            triggered_by=triggered_by,
            transaction_id=transaction_id,
            version=version,
        )
        device_snapshots.append(snapshot)
        logger.info(
            "Config snapshot captured: %s v%d (%s)",
            device_hostname, version, triggered_by,
        )
        return snapshot

    def compute_diff(
        self,
        device_id: str,
        before_id: str | None = None,
        after_id: str | None = None,
    ) -> ConfigDiff | None:
        """Compute diff between two snapshots (defaults to last two)."""
        snapshots = self._snapshots.get(device_id, [])
        if len(snapshots) < 2 and not (before_id and after_id):
            return None

        before = None
        after = None

        if before_id and after_id:
            for s in snapshots:
                if s.id == before_id:
                    before = s
                if s.id == after_id:
                    after = s
        else:
            before = snapshots[-2]
            after = snapshots[-1]

        if not before or not after:
            return None

        before_lines = before.config_xml.splitlines(keepends=True)
        after_lines = after.config_xml.splitlines(keepends=True)

        diff = list(difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"{before.device_hostname} v{before.version}",
            tofile=f"{after.device_hostname} v{after.version}",
            lineterm="",
        ))

        additions = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))

        return ConfigDiff(
            device_id=device_id,
            device_hostname=before.device_hostname,
            before_snapshot_id=before.id,
            after_snapshot_id=after.id,
            diff_lines=diff,
            additions=additions,
            deletions=deletions,
            modifications=min(additions, deletions),
        )

    def record_audit(
        self,
        device_id: str,
        device_hostname: str = "",
        action: str = "commit",
        transaction_id: str | None = None,
        user: str = "system",
        status: str = "success",
        snapshot_before_id: str | None = None,
        snapshot_after_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Record a configuration change in the audit log."""
        entry = AuditEntry(
            device_id=device_id,
            device_hostname=device_hostname,
            action=action,
            transaction_id=transaction_id,
            user=user,
            status=status,
            snapshot_before_id=snapshot_before_id,
            snapshot_after_id=snapshot_after_id,
            details=details or {},
        )
        self._audit_log.append(entry)
        logger.info(
            "Audit entry: %s on %s by %s — %s",
            action, device_hostname, user, status,
        )
        return entry

    def get_device_history(
        self,
        device_id: str,
        limit: int = 50,
    ) -> list[AuditEntry]:
        """Get audit history for a specific device."""
        entries = [e for e in self._audit_log if e.device_id == device_id]
        return sorted(entries, key=lambda e: e.timestamp, reverse=True)[:limit]

    def get_audit_log(self, limit: int = 100) -> list[AuditEntry]:
        """Get the global audit log."""
        return sorted(self._audit_log, key=lambda e: e.timestamp, reverse=True)[:limit]

    def get_snapshots(self, device_id: str) -> list[ConfigSnapshot]:
        """Get all snapshots for a device."""
        return self._snapshots.get(device_id, [])

    def get_latest_snapshot(self, device_id: str) -> ConfigSnapshot | None:
        """Get the most recent snapshot for a device."""
        snapshots = self._snapshots.get(device_id, [])
        return snapshots[-1] if snapshots else None

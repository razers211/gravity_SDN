"""
Telemetry domain models.

Represents telemetry events, alarms, and metrics ingested from CloudEngine
devices via YANG Push, gRPC, and syslog feeds.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Any

from pydantic import BaseModel, Field


# ── Enumerations ─────────────────────────────────────────────────────────────


class AlarmSeverity(IntEnum):
    """Alarm severity levels (ITU-T X.733)."""
    CLEARED = 0
    INDETERMINATE = 1
    WARNING = 2
    MINOR = 3
    MAJOR = 4
    CRITICAL = 5


class TelemetrySource(StrEnum):
    """Origin protocol of a telemetry event."""
    YANG_PUSH = "yang-push"
    GRPC = "grpc"
    SYSLOG = "syslog"
    SNMP_TRAP = "snmp-trap"
    BFD = "bfd"
    NETCONF_NOTIFICATION = "netconf-notification"


class AlarmCategory(StrEnum):
    """High-level alarm categorisation."""
    LINK = "link"
    DEVICE = "device"
    BGP = "bgp"
    VXLAN = "vxlan"
    QOS = "qos"
    POWER = "power"
    FAN = "fan"
    TEMPERATURE = "temperature"
    MEMORY = "memory"
    CPU = "cpu"
    SECURITY = "security"
    CONFIGURATION = "configuration"


class RemediationStatus(StrEnum):
    """Status of an automated remediation action."""
    PENDING = "pending"
    IN_PROGRESS = "in-progress"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


# ── Core Models ──────────────────────────────────────────────────────────────


class Metric(BaseModel):
    """A single telemetry metric data point."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    device_id: str = Field(..., description="Source device ID")
    device_hostname: str = Field(default="")
    interface_name: str | None = None
    metric_path: str = Field(
        ...,
        description="YANG XPath or sensor path",
        examples=["huawei-ifm:ifm/interfaces/interface/statistics/in-octets"],
    )
    value: float = Field(..., examples=[1048576.0])
    unit: str = Field(default="", examples=["bytes", "percent", "bps", "pps", "celsius"])
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: TelemetrySource = TelemetrySource.YANG_PUSH
    labels: dict[str, str] = Field(default_factory=dict)


class Alarm(BaseModel):
    """
    A network alarm raised by telemetry analysis or device notification.

    Alarms are the primary trigger for the 1-3-5 troubleshooting framework:
    - 1 min: Detection (alarm raised)
    - 3 min: Impact location (graph traversal)
    - 5 min: Autonomous remediation
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    device_id: str = Field(..., description="Source device ID")
    device_hostname: str = Field(default="")
    severity: AlarmSeverity = AlarmSeverity.WARNING
    category: AlarmCategory = AlarmCategory.LINK
    source: TelemetrySource = TelemetrySource.YANG_PUSH

    # ── Alarm Details ────────────────────────────────────────────────────
    title: str = Field(..., examples=["Interface 10GE1/0/1 Link Down"])
    message: str = Field(default="")
    interface_name: str | None = Field(default=None, examples=["10GE1/0/1"])
    affected_resource: str = Field(default="", description="YANG path or resource identifier")
    root_cause: str | None = None

    # ── Timestamps ───────────────────────────────────────────────────────
    raised_at: datetime = Field(default_factory=datetime.utcnow)
    acknowledged_at: datetime | None = None
    cleared_at: datetime | None = None

    # ── Impact Analysis ──────────────────────────────────────────────────
    impacted_tenants: list[str] = Field(default_factory=list)
    impacted_vms: list[str] = Field(default_factory=list)
    impacted_services: list[str] = Field(default_factory=list)
    impact_score: float = Field(default=0.0, ge=0.0, le=100.0)

    # ── Remediation ──────────────────────────────────────────────────────
    remediation_status: RemediationStatus = RemediationStatus.PENDING
    remediation_action: str | None = None
    remediation_task_id: str | None = None

    # ── Correlation ──────────────────────────────────────────────────────
    correlation_id: str | None = Field(default=None, description="Groups related alarms")
    is_root_cause: bool = False
    child_alarm_ids: list[str] = Field(default_factory=list)

    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.cleared_at is None

    @property
    def is_critical(self) -> bool:
        return self.severity >= AlarmSeverity.MAJOR


class TelemetryEvent(BaseModel):
    """
    Raw telemetry event envelope — wraps YANG Push notifications,
    gRPC telemetry messages, and syslog entries before processing.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: TelemetrySource = TelemetrySource.YANG_PUSH
    device_id: str | None = None
    device_ip: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # ── YANG Push Fields ─────────────────────────────────────────────────
    subscription_id: int | None = Field(default=None, description="RFC 8639 subscription ID")
    xpath: str | None = Field(default=None, examples=["/huawei-ifm:ifm/interfaces/interface"])
    notification_type: str | None = Field(
        default=None, examples=["push-update", "push-change-update"]
    )

    # ── Payload ──────────────────────────────────────────────────────────
    raw_payload: str = Field(default="", description="Raw XML/JSON/protobuf payload")
    parsed_data: dict[str, Any] = Field(default_factory=dict)

    # ── Processing State ─────────────────────────────────────────────────
    processed: bool = False
    processing_error: str | None = None

    # ── Derived Objects ──────────────────────────────────────────────────
    metrics: list[Metric] = Field(default_factory=list)
    alarms: list[Alarm] = Field(default_factory=list)


class ImpactReport(BaseModel):
    """
    Output of the graph-based impact analysis — maps a network fault
    to the affected tenants, VMs, and services via the 5-layer digital map.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    alarm_id: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    analysis_duration_ms: float = 0.0

    # ── Fault Source ─────────────────────────────────────────────────────
    fault_device_id: str
    fault_interface: str | None = None
    fault_type: str = Field(default="link-down", examples=["link-down", "device-unreachable"])

    # ── 5-Layer Impact ───────────────────────────────────────────────────
    impacted_physical_devices: list[str] = Field(default_factory=list)
    impacted_servers: list[str] = Field(default_factory=list)
    impacted_virtual_networks: list[str] = Field(default_factory=list)
    impacted_vms: list[str] = Field(default_factory=list)
    impacted_services: list[str] = Field(default_factory=list)

    # ── Severity ─────────────────────────────────────────────────────────
    total_impacted_count: int = 0
    max_severity: AlarmSeverity = AlarmSeverity.WARNING
    recommended_action: str | None = None


class RemediationRecord(BaseModel):
    """Audit trail for an autonomous remediation action."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    alarm_id: str
    impact_report_id: str | None = None
    status: RemediationStatus = RemediationStatus.PENDING

    # ── Action Details ───────────────────────────────────────────────────
    action_type: str = Field(default="bypass-path", examples=["bypass-path", "ecmp-rehash", "failover"])
    description: str = ""
    target_devices: list[str] = Field(default_factory=list)
    netconf_payloads: list[str] = Field(default_factory=list, description="XML payloads applied")

    # ── Timing ───────────────────────────────────────────────────────────
    initiated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    duration_ms: float = 0.0

    # ── Result ───────────────────────────────────────────────────────────
    success: bool = False
    error_message: str | None = None
    rollback_performed: bool = False

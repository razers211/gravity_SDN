"""Shared domain models package."""

from shared.models.device import Device, DeviceCredentials, DeviceInterface, DeviceRole, DeviceStatus
from shared.models.fabric import BridgeDomain, RouteTarget, VNIBinding, VPNInstance, VtepEndpoint
from shared.models.intent import (
    FirewallPolicy,
    IntentPayload,
    IntentResult,
    MicrosegmentationRule,
    Subnet,
    Tenant,
    VPC,
)
from shared.models.telemetry import Alarm, AlarmSeverity, Metric, TelemetryEvent, TelemetrySource

__all__ = [
    # Device
    "Device",
    "DeviceCredentials",
    "DeviceInterface",
    "DeviceRole",
    "DeviceStatus",
    # Fabric
    "BridgeDomain",
    "RouteTarget",
    "VNIBinding",
    "VPNInstance",
    "VtepEndpoint",
    # Intent
    "FirewallPolicy",
    "IntentPayload",
    "IntentResult",
    "MicrosegmentationRule",
    "Subnet",
    "Tenant",
    "VPC",
    # Telemetry
    "Alarm",
    "AlarmSeverity",
    "Metric",
    "TelemetryEvent",
    "TelemetrySource",
]

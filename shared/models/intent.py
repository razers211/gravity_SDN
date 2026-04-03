"""
Intent domain models.

Represents the high-level tenant intent payload received via the REST NBI,
including VPCs, subnets, and microsegmentation policies.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, IPvAnyNetwork


# ── Enumerations ─────────────────────────────────────────────────────────────


class IntentStatus(StrEnum):
    """Lifecycle states for an intent."""
    PENDING = "pending"
    VALIDATING = "validating"
    VERIFIED = "verified"
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class PolicyAction(StrEnum):
    """Firewall / microsegmentation rule action."""
    PERMIT = "permit"
    DENY = "deny"
    REDIRECT = "redirect"


class PolicyProtocol(StrEnum):
    """Supported L4 protocols."""
    TCP = "tcp"
    UDP = "udp"
    ICMP = "icmp"
    ANY = "any"


# ── Core Models ──────────────────────────────────────────────────────────────


class Subnet(BaseModel):
    """A single subnet within a VPC."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., min_length=1, max_length=64, examples=["subnet-web"])
    cidr: IPvAnyNetwork = Field(..., examples=["10.100.1.0/24"])
    gateway: str | None = Field(default=None, examples=["10.100.1.1"])
    vlan_id: int | None = Field(default=None, ge=1, le=4094)
    vni: int | None = Field(default=None, ge=1, le=16777215, description="Auto-assigned if None")
    description: str = ""


class MicrosegmentationRule(BaseModel):
    """A single microsegmentation rule between subnets."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., examples=["web-to-db-deny"])
    source_subnet: str = Field(..., description="Source subnet name or ID")
    destination_subnet: str = Field(..., description="Destination subnet name or ID")
    protocol: PolicyProtocol = PolicyProtocol.ANY
    source_port: str | None = Field(default=None, examples=["1024-65535"])
    destination_port: str | None = Field(default=None, examples=["3306"])
    action: PolicyAction = PolicyAction.DENY
    priority: int = Field(default=100, ge=1, le=65535)


class FirewallPolicy(BaseModel):
    """Firewall insertion policy for microsegmentation between subnets."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., examples=["fw-policy-tenant-a"])
    source_subnets: list[str] = Field(default_factory=list, description="Subnet names/IDs")
    destination_subnets: list[str] = Field(default_factory=list)
    firewall_type: str = Field(default="virtual", description="virtual | physical")
    rules: list[MicrosegmentationRule] = Field(default_factory=list)
    enabled: bool = True


class VPC(BaseModel):
    """Virtual Private Cloud — a logical L3 network domain."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., min_length=1, max_length=64, examples=["vpc-1"])
    subnets: list[Subnet] = Field(default_factory=list)
    firewall_policies: list[FirewallPolicy] = Field(default_factory=list)
    vrf_name: str | None = Field(default=None, description="Auto-generated if None")
    route_distinguisher: str | None = Field(default=None, examples=["65000:100"])
    description: str = ""


class Tenant(BaseModel):
    """Top-level tenant abstraction owning VPCs."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., min_length=1, max_length=128, examples=["Tenant-A"])
    vpcs: list[VPC] = Field(default_factory=list)
    contact_email: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


# ── Intent Payloads ──────────────────────────────────────────────────────────


class IntentPayload(BaseModel):
    """
    Complete intent payload received from the Northbound REST API.

    Example:
        {
            "tenant": {"name": "Tenant-A"},
            "vpcs": [
                {
                    "name": "vpc-1",
                    "subnets": [
                        {"name": "subnet-web", "cidr": "10.100.1.0/24"},
                        {"name": "subnet-db",  "cidr": "10.100.2.0/24"}
                    ],
                    "firewall_policies": [
                        {
                            "name": "microseg-web-db",
                            "source_subnets": ["subnet-web"],
                            "destination_subnets": ["subnet-db"],
                            "rules": [
                                {
                                    "name": "deny-direct",
                                    "source_subnet": "subnet-web",
                                    "destination_subnet": "subnet-db",
                                    "action": "deny"
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant: Tenant
    vpcs: list[VPC] = Field(default_factory=list)
    dry_run: bool = Field(default=False, description="Validate only, do not provision")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: IntentStatus = IntentStatus.PENDING
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Verification Results ─────────────────────────────────────────────────────


class Violation(BaseModel):
    """A single verification violation."""

    code: str = Field(..., examples=["ROUTING_LOOP", "IP_CONFLICT", "POLICY_VIOLATION"])
    severity: str = Field(default="error", examples=["error", "warning"])
    message: str
    affected_resources: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    """Result of formal verification of a network intent."""

    intent_id: str
    passed: bool
    violations: list[Violation] = Field(default_factory=list)
    simulation_time_ms: float = 0.0
    topology_snapshot_id: str | None = None


class IntentResult(BaseModel):
    """Complete result returned after intent processing."""

    intent_id: str
    status: IntentStatus
    verification: VerificationResult | None = None
    provisioning_task_id: str | None = None
    error_message: str | None = None
    completed_at: datetime | None = None

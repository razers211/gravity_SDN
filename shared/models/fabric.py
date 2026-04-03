"""
Fabric domain models.

Represents VXLAN fabric constructs: Bridge Domains, VPN Instances (VRFs),
VNI bindings, Route Targets, and VTEP endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


# ── Enumerations ─────────────────────────────────────────────────────────────


class RouteTargetType(StrEnum):
    """Route target import/export designation."""
    IMPORT = "import"
    EXPORT = "export"
    BOTH = "both"


class VPNType(StrEnum):
    """VPN instance type."""
    L3VPN = "l3vpn"
    L2VPN = "l2vpn"
    EVPN = "evpn"


class BDStatus(StrEnum):
    """Bridge domain operational status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"


# ── Core Models ──────────────────────────────────────────────────────────────


class RouteTarget(BaseModel):
    """An import or export Route Target (RT) value."""

    value: str = Field(..., examples=["65000:100"], description="RT in ASN:NN format")
    type: RouteTargetType = RouteTargetType.BOTH

    def __str__(self) -> str:
        return f"{self.value} ({self.type})"


class VNIBinding(BaseModel):
    """Binding between a VNI and its associated Bridge Domain or VRF."""

    vni: int = Field(..., ge=1, le=16777215, examples=[10100])
    bridge_domain_id: int | None = Field(default=None, ge=1, le=16777215)
    vrf_name: str | None = Field(default=None, description="For L3 VNI binding")
    evpn_instance: str | None = None


class BridgeDomain(BaseModel):
    """
    Layer 2 Bridge Domain — the fundamental L2 broadcast domain
    in a VXLAN fabric, bound to a VNI for overlay transport.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    bd_id: int = Field(..., ge=1, le=16777215, examples=[100])
    name: str = Field(default="", examples=["bd-web-subnet"])
    description: str = ""
    status: BDStatus = BDStatus.PENDING

    # ── VNI Mapping ──────────────────────────────────────────────────────
    vni: int | None = Field(default=None, ge=1, le=16777215, examples=[10100])

    # ── EVPN Instance ────────────────────────────────────────────────────
    evpn_instance_name: str | None = Field(default=None, examples=["evpn-100"])
    route_distinguisher: str | None = Field(default=None, examples=["10.0.0.1:100"])
    route_targets: list[RouteTarget] = Field(default_factory=list)

    # ── VBDIF Anycast Gateway ────────────────────────────────────────────
    vbdif_ip: str | None = Field(default=None, examples=["10.100.1.1/24"])
    vbdif_mac: str | None = Field(
        default=None,
        examples=["00:00:5e:00:01:01"],
        description="Anycast MAC (same across all VTEP leaves)",
    )
    arp_proxy_enabled: bool = True

    # ── Member Interfaces ────────────────────────────────────────────────
    member_interfaces: list[str] = Field(default_factory=list, examples=[["10GE1/0/1", "10GE1/0/2"]])

    # ── Associated Devices ───────────────────────────────────────────────
    device_ids: list[str] = Field(default_factory=list, description="Devices where this BD is provisioned")

    # ── Metadata ─────────────────────────────────────────────────────────
    tenant_id: str | None = None
    vpc_id: str | None = None
    subnet_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VPNInstance(BaseModel):
    """
    Layer 3 VPN Instance (VRF) — provides multi-tenant L3 isolation
    within the VXLAN fabric.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., min_length=1, max_length=31, examples=["vrf-tenant-a"])
    description: str = ""
    vpn_type: VPNType = VPNType.L3VPN

    # ── Route Distinguisher & Targets ────────────────────────────────────
    route_distinguisher: str = Field(..., examples=["65000:100"])
    import_route_targets: list[RouteTarget] = Field(default_factory=list)
    export_route_targets: list[RouteTarget] = Field(default_factory=list)

    # ── L3 VNI (for symmetric IRB) ───────────────────────────────────────
    l3_vni: int | None = Field(default=None, ge=1, le=16777215, examples=[50000])

    # ── Address Families ─────────────────────────────────────────────────
    ipv4_unicast_enabled: bool = True
    ipv6_unicast_enabled: bool = False
    evpn_enabled: bool = True

    # ── Associated Bridge Domains ────────────────────────────────────────
    bridge_domain_ids: list[int] = Field(default_factory=list)

    # ── Associated Devices ───────────────────────────────────────────────
    device_ids: list[str] = Field(default_factory=list)

    # ── Metadata ─────────────────────────────────────────────────────────
    tenant_id: str | None = None
    vpc_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VtepEndpoint(BaseModel):
    """
    VXLAN Tunnel Endpoint (VTEP) — represents the NVE interface
    on a leaf switch that terminates VXLAN tunnels.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    device_id: str = Field(..., description="Parent device ID")
    nve_interface: str = Field(default="Nve1", examples=["Nve1"])
    source_interface: str = Field(..., examples=["LoopBack1"])
    source_ip: str = Field(..., examples=["10.0.0.1"])
    vni_list: list[int] = Field(default_factory=list, description="VNIs terminated by this VTEP")
    bgp_evpn_enabled: bool = True
    status: str = Field(default="active")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FabricTopology(BaseModel):
    """Aggregate view of the entire VXLAN fabric topology."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(default="dc-fabric-01")
    spine_asn: int = Field(default=65000, ge=1, le=4294967295)
    leaf_asn_range: str = Field(default="65001-65100")
    underlay_protocol: str = Field(default="OSPF", examples=["OSPF", "IS-IS", "eBGP"])
    overlay_protocol: str = Field(default="iBGP-EVPN")
    devices: list[str] = Field(default_factory=list, description="Device IDs in this fabric")
    bridge_domains: list[int] = Field(default_factory=list)
    vpn_instances: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)

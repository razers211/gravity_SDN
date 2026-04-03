"""
Device domain models.

Represents physical and logical network device entities in the CloudEngine
fabric, including connection credentials and interface descriptions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, IPvAnyAddress


# ── Enumerations ─────────────────────────────────────────────────────────────


class DeviceRole(StrEnum):
    """Role of a device in the VXLAN fabric."""
    SPINE = "spine"
    LEAF = "leaf"
    BORDER_LEAF = "border-leaf"
    ROUTE_REFLECTOR = "route-reflector"
    DCI_GATEWAY = "dci-gateway"
    SERVICE_LEAF = "service-leaf"
    SUPER_SPINE = "super-spine"


class DeviceStatus(StrEnum):
    """Operational status of a managed device."""
    UNKNOWN = "unknown"
    DISCOVERED = "discovered"
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    OFFLINE = "offline"
    DECOMMISSIONED = "decommissioned"


class InterfaceType(StrEnum):
    """Network interface types."""
    PHYSICAL = "physical"
    LOOPBACK = "loopback"
    VLANIF = "vlanif"
    VBDIF = "vbdif"
    NVE = "nve"
    ETH_TRUNK = "eth-trunk"
    MANAGEMENT = "management"


class InterfaceStatus(StrEnum):
    """Operational status of an interface."""
    UP = "up"
    DOWN = "down"
    ADMIN_DOWN = "admin-down"
    TESTING = "testing"


# ── Core Models ──────────────────────────────────────────────────────────────


class DeviceCredentials(BaseModel):
    """SSH / NETCONF credentials for a managed device."""

    username: str = Field(default="admin")
    password: str = Field(default="", description="Encrypted at rest")
    ssh_key_path: str | None = None
    netconf_port: int = Field(default=830, ge=1, le=65535)
    ssh_port: int = Field(default=22, ge=1, le=65535)


class DeviceInterface(BaseModel):
    """A single network interface on a managed device."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., examples=["10GE1/0/1", "LoopBack0", "Vbdif100", "Nve1"])
    type: InterfaceType = InterfaceType.PHYSICAL
    status: InterfaceStatus = InterfaceStatus.DOWN
    ip_address: str | None = Field(default=None, examples=["10.0.0.1/32"])
    mac_address: str | None = Field(default=None, examples=["00:11:22:33:44:55"])
    mtu: int = Field(default=1500, ge=64, le=9216)
    speed_mbps: int | None = Field(default=None, examples=[10000, 25000, 100000])
    description: str = ""
    vlan_id: int | None = Field(default=None, ge=1, le=4094)
    bridge_domain_id: int | None = None
    is_vtep_source: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class Device(BaseModel):
    """
    A managed CloudEngine network device.

    Represents a physical switch or router in the data center fabric with its
    identifiers, role, management connectivity, and interface inventory.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    hostname: str = Field(..., min_length=1, max_length=255, examples=["ce-spine-01"])
    management_ip: IPvAnyAddress = Field(..., examples=["10.255.0.1"])
    esn: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Equipment Serial Number",
        examples=["2102311TDN10L6000003"],
    )
    model: str = Field(default="CE6800", examples=["CE16800", "CE12800", "CE6800"])
    software_version: str = Field(default="V300R024C10", examples=["V300R024C10"])
    role: DeviceRole = DeviceRole.LEAF
    status: DeviceStatus = DeviceStatus.UNKNOWN
    site: str = Field(default="dc-01", examples=["dc-01", "dc-02"])
    pod: str = Field(default="pod-01", examples=["pod-01", "pod-02"])
    rack: str = Field(default="rack-01")

    # ── NETCONF Connectivity ─────────────────────────────────────────────
    credentials: DeviceCredentials = Field(default_factory=DeviceCredentials)
    router_id: str | None = Field(default=None, examples=["10.0.0.1"])
    system_mac: str | None = Field(default=None, examples=["00:aa:bb:cc:dd:01"])

    # ── VTEP Configuration ───────────────────────────────────────────────
    vtep_ip: str | None = Field(default=None, examples=["10.0.0.1"])
    vtep_source_interface: str = Field(default="LoopBack1")

    # ── BGP Configuration ────────────────────────────────────────────────
    bgp_asn: int | None = Field(default=None, ge=1, le=4294967295, examples=[65000])
    bgp_router_id: str | None = Field(default=None, examples=["10.0.0.1"])
    is_route_reflector: bool = False
    rr_cluster_id: str | None = None

    # ── Interface Inventory ──────────────────────────────────────────────
    interfaces: list[DeviceInterface] = Field(default_factory=list)

    # ── Metadata ─────────────────────────────────────────────────────────
    tags: dict[str, str] = Field(default_factory=dict)
    discovered_at: datetime | None = None
    last_synced_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def netconf_endpoint(self) -> str:
        """Return the primary NETCONF connection string."""
        return f"{self.management_ip}:{self.credentials.netconf_port}"

    @property
    def is_spine(self) -> bool:
        return self.role in (DeviceRole.SPINE, DeviceRole.SUPER_SPINE)

    @property
    def is_leaf(self) -> bool:
        return self.role in (DeviceRole.LEAF, DeviceRole.BORDER_LEAF, DeviceRole.SERVICE_LEAF)

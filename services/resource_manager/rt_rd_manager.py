"""
Route Target / Route Distinguisher Manager.

Manages auto-allocation of Route Targets (RT) and Route Distinguishers (RD)
for BGP EVPN / L3VPN configurations. Ensures uniqueness across tenants
and supports both Type 0 (2-byte ASN:NN) and Type 1 (IP:NN) formats.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RTRDError(Exception):
    """Raised on RT/RD allocation failures."""


class RTAllocation(BaseModel):
    """An allocated Route Target."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    value: str = Field(..., examples=["65000:100"])
    rt_type: str = Field(default="both", examples=["import", "export", "both"])
    format_type: str = Field(default="type0", examples=["type0", "type1"])
    allocated_to: str = ""
    tenant_id: str | None = None
    vpc_id: str | None = None
    allocated_at: datetime = Field(default_factory=datetime.utcnow)


class RDAllocation(BaseModel):
    """An allocated Route Distinguisher."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    value: str = Field(..., examples=["65000:100"])
    format_type: str = Field(default="type0")
    allocated_to: str = ""
    tenant_id: str | None = None
    vpc_id: str | None = None
    allocated_at: datetime = Field(default_factory=datetime.utcnow)


class RTRDManager:
    """
    Route Target and Route Distinguisher allocation manager.

    Supports two allocation formats:
      - Type 0: <2-byte ASN>:<4-byte NN>  (e.g., 65000:100)
      - Type 1: <IPv4>:<2-byte NN>        (e.g., 10.0.0.1:100)
    """

    def __init__(self, base_asn: int = 65000, base_ip: str = "10.0.0.1"):
        self.base_asn = base_asn
        self.base_ip = base_ip
        self._rt_counter = 100
        self._rd_counter = 100
        self._allocated_rts: dict[str, RTAllocation] = {}
        self._allocated_rds: dict[str, RDAllocation] = {}

    def allocate_rt(
        self,
        tenant_id: str | None = None,
        vpc_id: str | None = None,
        rt_type: str = "both",
        format_type: str = "type0",
    ) -> RTAllocation:
        """Allocate a unique Route Target."""
        self._rt_counter += 1

        if format_type == "type0":
            value = f"{self.base_asn}:{self._rt_counter}"
        else:
            value = f"{self.base_ip}:{self._rt_counter}"

        # Ensure uniqueness
        while value in self._allocated_rts:
            self._rt_counter += 1
            if format_type == "type0":
                value = f"{self.base_asn}:{self._rt_counter}"
            else:
                value = f"{self.base_ip}:{self._rt_counter}"

        allocation = RTAllocation(
            value=value,
            rt_type=rt_type,
            format_type=format_type,
            allocated_to=f"tenant:{tenant_id}/vpc:{vpc_id}",
            tenant_id=tenant_id,
            vpc_id=vpc_id,
        )
        self._allocated_rts[value] = allocation
        logger.info("RT allocated: %s (type=%s) → tenant=%s, vpc=%s", value, rt_type, tenant_id, vpc_id)
        return allocation

    def allocate_rd(
        self,
        tenant_id: str | None = None,
        vpc_id: str | None = None,
        format_type: str = "type0",
    ) -> RDAllocation:
        """Allocate a unique Route Distinguisher."""
        self._rd_counter += 1

        if format_type == "type0":
            value = f"{self.base_asn}:{self._rd_counter}"
        else:
            value = f"{self.base_ip}:{self._rd_counter}"

        while value in self._allocated_rds:
            self._rd_counter += 1
            if format_type == "type0":
                value = f"{self.base_asn}:{self._rd_counter}"
            else:
                value = f"{self.base_ip}:{self._rd_counter}"

        allocation = RDAllocation(
            value=value,
            format_type=format_type,
            allocated_to=f"tenant:{tenant_id}/vpc:{vpc_id}",
            tenant_id=tenant_id,
            vpc_id=vpc_id,
        )
        self._allocated_rds[value] = allocation
        logger.info("RD allocated: %s → tenant=%s, vpc=%s", value, tenant_id, vpc_id)
        return allocation

    def allocate_rt_pair(
        self,
        tenant_id: str | None = None,
        vpc_id: str | None = None,
    ) -> dict[str, RTAllocation]:
        """Allocate matching import and export RT values."""
        export_rt = self.allocate_rt(tenant_id, vpc_id, rt_type="export")
        # For default intra-VPC, import RT = export RT
        import_alloc = RTAllocation(
            value=export_rt.value,
            rt_type="import",
            format_type=export_rt.format_type,
            allocated_to=export_rt.allocated_to,
            tenant_id=tenant_id,
            vpc_id=vpc_id,
        )
        self._allocated_rts[f"{import_alloc.value}-import"] = import_alloc
        return {"import": import_alloc, "export": export_rt}

    def release_rt(self, value: str) -> bool:
        """Release an allocated RT."""
        if value in self._allocated_rts:
            del self._allocated_rts[value]
            logger.info("RT released: %s", value)
            return True
        return False

    def release_rd(self, value: str) -> bool:
        """Release an allocated RD."""
        if value in self._allocated_rds:
            del self._allocated_rds[value]
            logger.info("RD released: %s", value)
            return True
        return False

    def get_allocations(self, tenant_id: str | None = None) -> dict[str, Any]:
        """Get all allocations, optionally filtered by tenant."""
        rts = list(self._allocated_rts.values())
        rds = list(self._allocated_rds.values())

        if tenant_id:
            rts = [rt for rt in rts if rt.tenant_id == tenant_id]
            rds = [rd for rd in rds if rd.tenant_id == tenant_id]

        return {
            "route_targets": [rt.model_dump() for rt in rts],
            "route_distinguishers": [rd.model_dump() for rd in rds],
        }

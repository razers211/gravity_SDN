"""
VNI Allocator.

Manages VXLAN Network Identifier (VNI) pools for L2 and L3 allocations.
Ensures uniqueness and supports range-based pool partitioning.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class VNIAllocationError(Exception):
    """Raised on VNI allocation failures."""


class VNIPool(BaseModel):
    """A VNI allocation pool."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., examples=["l2-vni-pool", "l3-vni-pool"])
    range_start: int = Field(..., ge=1, le=16777215)
    range_end: int = Field(..., ge=1, le=16777215)
    pool_type: str = Field(default="l2", examples=["l2", "l3"])
    allocated: dict[int, dict[str, Any]] = Field(default_factory=dict)

    @property
    def total_capacity(self) -> int:
        return self.range_end - self.range_start + 1

    @property
    def available_count(self) -> int:
        return self.total_capacity - len(self.allocated)


class VNIAllocator:
    """
    VNI pool manager supporting L2 and L3 VNI allocation.

    Default pools:
      - L2 VNI: 10000 - 15999999 (Bridge Domain binding)
      - L3 VNI: 50000 - 59999    (VRF symmetric IRB)
    """

    def __init__(self):
        self._pools: dict[str, VNIPool] = {}
        self._initialize_default_pools()

    def _initialize_default_pools(self) -> None:
        """Create default L2 and L3 VNI pools."""
        self.create_pool("l2-vni-pool", 10000, 15999999, "l2")
        self.create_pool("l3-vni-pool", 50000, 59999, "l3")

    def create_pool(
        self,
        name: str,
        range_start: int,
        range_end: int,
        pool_type: str = "l2",
    ) -> VNIPool:
        """Create a new VNI pool."""
        pool = VNIPool(
            name=name,
            range_start=range_start,
            range_end=range_end,
            pool_type=pool_type,
        )
        self._pools[pool.id] = pool
        logger.info(
            "VNI pool created: %s (%d-%d, type=%s, capacity=%d)",
            name, range_start, range_end, pool_type, pool.total_capacity,
        )
        return pool

    def allocate(
        self,
        pool_type: str = "l2",
        allocated_to: str = "",
    ) -> dict[str, Any]:
        """Allocate the next available VNI from the appropriate pool."""
        pool = self._find_pool_by_type(pool_type)
        if not pool:
            raise VNIAllocationError(f"No pool found for type '{pool_type}'")

        if pool.available_count <= 0:
            raise VNIAllocationError(f"VNI pool '{pool.name}' exhausted")

        for vni in range(pool.range_start, pool.range_end + 1):
            if vni not in pool.allocated:
                pool.allocated[vni] = {
                    "allocated_to": allocated_to,
                    "allocated_at": datetime.utcnow().isoformat(),
                }
                logger.debug("VNI allocated: %d (type=%s) → %s", vni, pool_type, allocated_to)
                return {"vni": vni, "pool": pool.name, "type": pool_type}

        raise VNIAllocationError(f"No available VNIs in pool '{pool.name}'")

    def release(self, vni: int) -> bool:
        """Release an allocated VNI back to its pool."""
        for pool in self._pools.values():
            if vni in pool.allocated:
                del pool.allocated[vni]
                logger.info("VNI released: %d → pool '%s'", vni, pool.name)
                return True
        return False

    def is_allocated(self, vni: int) -> bool:
        """Check if a VNI is currently allocated."""
        return any(vni in pool.allocated for pool in self._pools.values())

    def get_pool_status(self, pool_type: str = "l2") -> dict[str, Any] | None:
        """Get pool utilisation statistics."""
        pool = self._find_pool_by_type(pool_type)
        if not pool:
            return None
        return {
            "name": pool.name,
            "type": pool.pool_type,
            "range": f"{pool.range_start}-{pool.range_end}",
            "total": pool.total_capacity,
            "allocated": len(pool.allocated),
            "available": pool.available_count,
        }

    def _find_pool_by_type(self, pool_type: str) -> VNIPool | None:
        for pool in self._pools.values():
            if pool.pool_type == pool_type:
                return pool
        return None

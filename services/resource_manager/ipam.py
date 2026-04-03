"""
IP Address Management (IPAM).

Manages IP address pools, subnet allocations, and gateway assignments
for the data center fabric. Supports hierarchical pool structures
and conflict-free allocation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from ipaddress import IPv4Address, IPv4Network, ip_address, ip_network
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class IPAMError(Exception):
    """Raised on IPAM allocation failures."""


class IPPool(BaseModel):
    """An IP address pool for allocation."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., examples=["loopback-pool", "management-pool"])
    cidr: str = Field(..., examples=["10.0.0.0/16"])
    description: str = ""
    gateway: str | None = None
    reserved_addresses: list[str] = Field(default_factory=list)
    allocated_addresses: dict[str, dict[str, Any]] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def network(self) -> IPv4Network:
        return ip_network(self.cidr, strict=False)

    @property
    def total_addresses(self) -> int:
        return self.network.num_addresses - 2  # Exclude network and broadcast

    @property
    def available_count(self) -> int:
        return self.total_addresses - len(self.allocated_addresses) - len(self.reserved_addresses)

    @property
    def utilization_percent(self) -> float:
        if self.total_addresses == 0:
            return 0.0
        return (len(self.allocated_addresses) / self.total_addresses) * 100


class SubnetAllocation(BaseModel):
    """A subnet allocation from an IPAM pool."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pool_id: str
    cidr: str
    gateway: str
    allocated_to: str = Field(default="", description="Tenant/VPC/Subnet reference")
    allocated_at: datetime = Field(default_factory=datetime.utcnow)


class IPAMService:
    """
    IP Address Management service.

    Provides hierarchical pool management, conflict-free subnet
    allocation, and address tracking.
    """

    def __init__(self):
        self._pools: dict[str, IPPool] = {}
        self._allocations: dict[str, SubnetAllocation] = {}

    def create_pool(
        self,
        name: str,
        cidr: str,
        description: str = "",
        reserved: list[str] | None = None,
    ) -> IPPool:
        """Create a new IP address pool."""
        # Validate no overlap with existing pools
        new_network = ip_network(cidr, strict=False)
        for pool in self._pools.values():
            if new_network.overlaps(pool.network):
                raise IPAMError(
                    f"Pool '{name}' ({cidr}) overlaps with existing pool "
                    f"'{pool.name}' ({pool.cidr})"
                )

        pool = IPPool(
            name=name,
            cidr=cidr,
            description=description,
            reserved_addresses=reserved or [],
        )
        self._pools[pool.id] = pool
        logger.info("IP pool created: %s (%s) — %d addresses", name, cidr, pool.total_addresses)
        return pool

    def allocate_address(
        self,
        pool_name: str,
        allocated_to: str = "",
    ) -> dict[str, str]:
        """Allocate the next available IP address from a pool."""
        pool = self._find_pool_by_name(pool_name)
        if not pool:
            raise IPAMError(f"Pool '{pool_name}' not found")

        if pool.available_count <= 0:
            raise IPAMError(f"Pool '{pool_name}' exhausted")

        # Find next available address
        used = set(pool.allocated_addresses.keys()) | set(pool.reserved_addresses)

        for host in pool.network.hosts():
            addr_str = str(host)
            if addr_str not in used:
                pool.allocated_addresses[addr_str] = {
                    "allocated_to": allocated_to,
                    "allocated_at": datetime.utcnow().isoformat(),
                }
                logger.debug(
                    "IP allocated: %s from pool '%s' → %s",
                    addr_str, pool_name, allocated_to,
                )
                return {
                    "ip_address": addr_str,
                    "pool": pool_name,
                    "cidr": pool.cidr,
                }

        raise IPAMError(f"No available addresses in pool '{pool_name}'")

    def allocate_subnet(
        self,
        pool_name: str,
        prefix_length: int = 24,
        allocated_to: str = "",
    ) -> SubnetAllocation:
        """Allocate a subnet with the specified prefix length from a pool."""
        pool = self._find_pool_by_name(pool_name)
        if not pool:
            raise IPAMError(f"Pool '{pool_name}' not found")

        # Find available subnets of the requested size
        used_subnets = [
            ip_network(a.cidr, strict=False)
            for a in self._allocations.values()
            if a.pool_id == pool.id
        ]

        for subnet in pool.network.subnets(new_prefix=prefix_length):
            overlap = False
            for used in used_subnets:
                if subnet.overlaps(used):
                    overlap = True
                    break
            if not overlap:
                gateway = str(list(subnet.hosts())[0])
                allocation = SubnetAllocation(
                    pool_id=pool.id,
                    cidr=str(subnet),
                    gateway=gateway,
                    allocated_to=allocated_to,
                )
                self._allocations[allocation.id] = allocation
                logger.info(
                    "Subnet allocated: %s (gw: %s) from pool '%s' → %s",
                    subnet, gateway, pool_name, allocated_to,
                )
                return allocation

        raise IPAMError(
            f"No available /{prefix_length} subnet in pool '{pool_name}'"
        )

    def release_address(self, pool_name: str, address: str) -> bool:
        """Release an allocated IP address back to the pool."""
        pool = self._find_pool_by_name(pool_name)
        if pool and address in pool.allocated_addresses:
            del pool.allocated_addresses[address]
            logger.info("IP released: %s → pool '%s'", address, pool_name)
            return True
        return False

    def get_pool_status(self, pool_name: str) -> dict[str, Any] | None:
        """Get utilisation statistics for a pool."""
        pool = self._find_pool_by_name(pool_name)
        if not pool:
            return None
        return {
            "name": pool.name,
            "cidr": pool.cidr,
            "total": pool.total_addresses,
            "allocated": len(pool.allocated_addresses),
            "reserved": len(pool.reserved_addresses),
            "available": pool.available_count,
            "utilization_pct": round(pool.utilization_percent, 2),
        }

    def _find_pool_by_name(self, name: str) -> IPPool | None:
        for pool in self._pools.values():
            if pool.name == name:
                return pool
        return None

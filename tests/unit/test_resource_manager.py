"""
Unit tests for the Resource Manager (IPAM + VNI Allocator).
"""

from __future__ import annotations

import pytest

from services.resource_manager.ipam import IPAMService, IPAMError
from services.resource_manager.vni_allocator import VNIAllocator, VNIAllocationError
from services.resource_manager.rt_rd_manager import RTRDManager


class TestIPAM:
    """Tests for IP Address Management service."""

    def test_create_pool(self):
        ipam = IPAMService()
        pool = ipam.create_pool("test-pool", "10.0.0.0/24")
        assert pool.name == "test-pool"
        assert pool.total_addresses == 254

    def test_allocate_address(self):
        ipam = IPAMService()
        ipam.create_pool("test-pool", "10.0.0.0/24")
        result = ipam.allocate_address("test-pool", "device-1")
        assert "ip_address" in result
        assert result["pool"] == "test-pool"

    def test_sequential_allocation(self):
        ipam = IPAMService()
        ipam.create_pool("seq-pool", "10.0.0.0/28")  # 14 usable addresses
        addresses = set()
        for _ in range(5):
            r = ipam.allocate_address("seq-pool")
            addresses.add(r["ip_address"])
        assert len(addresses) == 5  # All unique

    def test_allocate_subnet(self):
        ipam = IPAMService()
        ipam.create_pool("big-pool", "10.0.0.0/16")
        alloc = ipam.allocate_subnet("big-pool", prefix_length=24, allocated_to="tenant-1")
        assert alloc.cidr is not None
        assert alloc.gateway is not None

    def test_overlapping_pools_rejected(self):
        ipam = IPAMService()
        ipam.create_pool("pool-1", "10.0.0.0/16")
        with pytest.raises(IPAMError, match="overlaps"):
            ipam.create_pool("pool-2", "10.0.1.0/24")

    def test_pool_utilization(self):
        ipam = IPAMService()
        pool = ipam.create_pool("util-pool", "10.0.0.0/28")
        assert pool.utilization_percent == 0.0
        ipam.allocate_address("util-pool")
        status = ipam.get_pool_status("util-pool")
        assert status["allocated"] == 1
        assert status["utilization_pct"] > 0

    def test_release_address(self):
        ipam = IPAMService()
        ipam.create_pool("rel-pool", "10.0.0.0/28")
        result = ipam.allocate_address("rel-pool")
        assert ipam.release_address("rel-pool", result["ip_address"]) is True

    def test_unknown_pool(self):
        ipam = IPAMService()
        with pytest.raises(IPAMError, match="not found"):
            ipam.allocate_address("nonexistent")


class TestVNIAllocator:
    """Tests for VNI pool allocation."""

    def test_default_pools_initialized(self):
        allocator = VNIAllocator()
        l2_status = allocator.get_pool_status("l2")
        l3_status = allocator.get_pool_status("l3")
        assert l2_status is not None
        assert l3_status is not None

    def test_allocate_l2_vni(self):
        allocator = VNIAllocator()
        result = allocator.allocate("l2", "bd-100")
        assert "vni" in result
        assert result["type"] == "l2"
        assert 10000 <= result["vni"] <= 15999999

    def test_allocate_l3_vni(self):
        allocator = VNIAllocator()
        result = allocator.allocate("l3", "vrf-test")
        assert "vni" in result
        assert result["type"] == "l3"
        assert 50000 <= result["vni"] <= 59999

    def test_sequential_vni_allocation(self):
        allocator = VNIAllocator()
        vnis = set()
        for _ in range(5):
            r = allocator.allocate("l2")
            vnis.add(r["vni"])
        assert len(vnis) == 5  # All unique

    def test_release_vni(self):
        allocator = VNIAllocator()
        result = allocator.allocate("l2")
        assert allocator.is_allocated(result["vni"]) is True
        assert allocator.release(result["vni"]) is True
        assert allocator.is_allocated(result["vni"]) is False


class TestRTRDManager:
    """Tests for Route Target / Route Distinguisher management."""

    def test_allocate_rt(self):
        mgr = RTRDManager(base_asn=65000)
        rt = mgr.allocate_rt(tenant_id="t1", vpc_id="v1")
        assert "65000:" in rt.value

    def test_allocate_rd(self):
        mgr = RTRDManager(base_asn=65000)
        rd = mgr.allocate_rd(tenant_id="t1", vpc_id="v1")
        assert "65000:" in rd.value

    def test_rt_uniqueness(self):
        mgr = RTRDManager()
        rt1 = mgr.allocate_rt()
        rt2 = mgr.allocate_rt()
        assert rt1.value != rt2.value

    def test_allocate_rt_pair(self):
        mgr = RTRDManager()
        pair = mgr.allocate_rt_pair(tenant_id="t1")
        assert "import" in pair
        assert "export" in pair
        # Import RT should match export RT for intra-VPC
        assert pair["import"].value == pair["export"].value

    def test_release_rt(self):
        mgr = RTRDManager()
        rt = mgr.allocate_rt()
        assert mgr.release_rt(rt.value) is True

    def test_get_allocations(self):
        mgr = RTRDManager()
        mgr.allocate_rt(tenant_id="t1")
        mgr.allocate_rd(tenant_id="t1")
        allocs = mgr.get_allocations(tenant_id="t1")
        assert len(allocs["route_targets"]) >= 1
        assert len(allocs["route_distinguishers"]) >= 1

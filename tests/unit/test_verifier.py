"""
Unit tests for the Formal Verifier.
"""

from __future__ import annotations

import pytest

from shared.models.intent import (
    FirewallPolicy,
    IntentPayload,
    MicrosegmentationRule,
    PolicyAction,
    Subnet,
    Tenant,
    VPC,
)
from services.intent_engine.translator import NetworkState
from services.intent_engine.verifier import FormalVerifier


@pytest.fixture
def verifier():
    return FormalVerifier()


@pytest.fixture
def clean_state():
    """A clean NetworkState with no conflicts."""
    state = NetworkState()
    state.add_vrf("vrf-a", "65000:100", ["65000:100"], ["65000:100"], 50000)
    state.add_subnet("subnet-web", "10.100.1.0/24", 10100, 100, "10.100.1.1", "vrf-a")
    state.add_subnet("subnet-db", "10.100.2.0/24", 10200, 200, "10.100.2.1", "vrf-a")
    state.add_routing_adjacency("subnet-web", "vrf-a", route_type="connected")
    state.add_routing_adjacency("subnet-db", "vrf-a", route_type="connected")
    return state


@pytest.fixture
def clean_intent():
    return IntentPayload(
        tenant=Tenant(name="Test"),
        vpcs=[
            VPC(
                name="vpc-1",
                subnets=[
                    Subnet(name="subnet-web", cidr="10.100.1.0/24"),
                    Subnet(name="subnet-db", cidr="10.100.2.0/24"),
                ],
            )
        ],
    )


class TestRoutingLoopDetection:
    """Tests for DFS cycle detection in the RIB/FIB graph."""

    def test_no_loops_passes(self, verifier, clean_state, clean_intent):
        result = verifier.verify(clean_state, clean_intent)
        loop_violations = [v for v in result.violations if v.code == "ROUTING_LOOP"]
        assert len(loop_violations) == 0

    def test_routing_loop_detected(self, verifier, clean_intent):
        state = NetworkState()
        state.add_subnet("s1", "10.0.1.0/24", 100, 1, "10.0.1.1", "vrf")
        state.add_subnet("s2", "10.0.2.0/24", 200, 2, "10.0.2.1", "vrf")
        state.add_vrf("vrf", "65000:1", [], [], None)

        # Create a cycle: s1 → s2 → s1
        state.add_routing_adjacency("s1", "s2", route_type="connected")
        state.add_routing_adjacency("s2", "s1", route_type="connected")

        result = verifier.verify(state, clean_intent)
        loop_violations = [v for v in result.violations if v.code == "ROUTING_LOOP"]
        assert len(loop_violations) > 0


class TestIPConflictDetection:
    """Tests for overlapping subnet detection."""

    def test_no_conflicts_passes(self, verifier, clean_state, clean_intent):
        result = verifier.verify(clean_state, clean_intent)
        ip_violations = [v for v in result.violations if v.code == "IP_CONFLICT"]
        assert len(ip_violations) == 0

    def test_overlapping_subnets_detected(self, verifier, clean_intent):
        state = NetworkState()
        state.add_vrf("vrf-a", "65000:100", [], [], None)
        # Overlapping: 10.100.1.0/24 overlaps with 10.100.1.0/25
        state.add_subnet("s1", "10.100.1.0/24", 100, 1, "10.100.1.1", "vrf-a")
        state.add_subnet("s2", "10.100.1.0/25", 200, 2, "10.100.1.1", "vrf-a")

        result = verifier.verify(state, clean_intent)
        ip_violations = [v for v in result.violations if v.code == "IP_CONFLICT"]
        assert len(ip_violations) > 0

    def test_same_subnets_different_vrfs_ok(self, verifier, clean_intent):
        state = NetworkState()
        state.add_vrf("vrf-a", "65000:100", [], [], None)
        state.add_vrf("vrf-b", "65000:200", [], [], None)
        # Same CIDR in different VRFs is OK
        state.add_subnet("s1", "10.0.1.0/24", 100, 1, "10.0.1.1", "vrf-a")
        state.add_subnet("s2", "10.0.1.0/24", 200, 2, "10.0.1.1", "vrf-b")

        result = verifier.verify(state, clean_intent)
        ip_violations = [v for v in result.violations if v.code == "IP_CONFLICT"]
        assert len(ip_violations) == 0


class TestVNIUniqueness:
    """Tests for VNI uniqueness validation."""

    def test_unique_vnis_pass(self, verifier, clean_state, clean_intent):
        result = verifier.verify(clean_state, clean_intent)
        vni_violations = [v for v in result.violations if v.code == "VNI_CONFLICT"]
        assert len(vni_violations) == 0

    def test_duplicate_vni_detected(self, verifier, clean_intent):
        state = NetworkState()
        state.add_vrf("vrf", "65000:1", [], [], None)
        # Same VNI 100 for two different subnets
        state.add_subnet("s1", "10.0.1.0/24", 100, 1, "10.0.1.1", "vrf")
        state.add_subnet("s2", "10.0.2.0/24", 100, 2, "10.0.2.1", "vrf")

        result = verifier.verify(state, clean_intent)
        vni_violations = [v for v in result.violations if v.code == "VNI_CONFLICT"]
        assert len(vni_violations) > 0


class TestSecurityPolicyValidation:
    """Tests for microsegmentation rule consistency."""

    def test_valid_policy_passes(self, verifier):
        state = NetworkState()
        state.add_vrf("vrf", "65000:1", [], [], None)
        state.add_subnet("subnet-web", "10.0.1.0/24", 100, 1, "10.0.1.1", "vrf")
        state.add_subnet("subnet-db", "10.0.2.0/24", 200, 2, "10.0.2.1", "vrf")

        intent = IntentPayload(
            tenant=Tenant(name="Test"),
            vpcs=[
                VPC(
                    name="vpc-1",
                    subnets=[
                        Subnet(name="subnet-web", cidr="10.0.1.0/24"),
                        Subnet(name="subnet-db", cidr="10.0.2.0/24"),
                    ],
                    firewall_policies=[
                        FirewallPolicy(
                            name="policy-1",
                            source_subnets=["subnet-web"],
                            destination_subnets=["subnet-db"],
                            rules=[
                                MicrosegmentationRule(
                                    name="deny-db",
                                    source_subnet="subnet-web",
                                    destination_subnet="subnet-db",
                                    action=PolicyAction.DENY,
                                )
                            ],
                        )
                    ],
                )
            ],
        )

        result = verifier.verify(state, intent)
        policy_violations = [v for v in result.violations if v.code == "POLICY_VIOLATION"]
        assert len(policy_violations) == 0

    def test_unknown_subnet_reference_detected(self, verifier):
        state = NetworkState()
        state.add_vrf("vrf", "65000:1", [], [], None)
        state.add_subnet("subnet-web", "10.0.1.0/24", 100, 1, "10.0.1.1", "vrf")
        # subnet-db does NOT exist in state

        intent = IntentPayload(
            tenant=Tenant(name="Test"),
            vpcs=[
                VPC(
                    name="vpc-1",
                    subnets=[Subnet(name="subnet-web", cidr="10.0.1.0/24")],
                    firewall_policies=[
                        FirewallPolicy(
                            name="policy-1",
                            rules=[
                                MicrosegmentationRule(
                                    name="rule-1",
                                    source_subnet="subnet-web",
                                    destination_subnet="nonexistent-subnet",
                                    action=PolicyAction.DENY,
                                )
                            ],
                        )
                    ],
                )
            ],
        )

        result = verifier.verify(state, intent)
        policy_violations = [v for v in result.violations if v.code == "POLICY_VIOLATION"]
        assert len(policy_violations) > 0


class TestVerificationResult:
    """Tests for overall verification result."""

    def test_clean_state_passes_verification(self, verifier, clean_state, clean_intent):
        result = verifier.verify(clean_state, clean_intent)
        assert result.passed is True
        assert len(result.violations) == 0
        assert result.simulation_time_ms >= 0

    def test_simulation_time_recorded(self, verifier, clean_state, clean_intent):
        result = verifier.verify(clean_state, clean_intent)
        assert result.simulation_time_ms >= 0

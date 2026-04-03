"""
Unit tests for the Intent Translator.
"""

from __future__ import annotations

import pytest

from shared.models.intent import IntentPayload, Subnet, Tenant, VPC
from services.intent_engine.translator import IntentTranslator, NetworkState


class TestNetworkState:
    """Tests for the NetworkState formal model."""

    def test_add_subnet(self):
        state = NetworkState()
        state.add_subnet(
            subnet_id="subnet-web",
            cidr="10.100.1.0/24",
            vni=10100,
            bd_id=100,
            gateway="10.100.1.1",
            vrf_name="vrf-test",
        )
        assert "subnet-web" in state.nodes
        assert state.subnets["subnet-web"]["cidr"] == "10.100.1.0/24"
        assert state.subnets["subnet-web"]["vni"] == 10100

    def test_add_vrf(self):
        state = NetworkState()
        state.add_vrf(
            vrf_name="vrf-test",
            rd="65000:100",
            import_rts=["65000:100"],
            export_rts=["65000:100"],
            l3_vni=50000,
        )
        assert "vrf-test" in state.nodes
        assert state.vrfs["vrf-test"]["rd"] == "65000:100"
        assert state.vrfs["vrf-test"]["l3_vni"] == 50000

    def test_add_routing_adjacency(self):
        state = NetworkState()
        state.add_subnet("s1", "10.0.1.0/24", 100, 1, "10.0.1.1", "vrf")
        state.add_vrf("vrf", "65000:1", [], [], None)
        state.add_routing_adjacency("s1", "vrf", route_type="connected")
        assert state.graph.has_edge("s1", "vrf")

    def test_multiple_subnets_in_vrf(self):
        state = NetworkState()
        state.add_vrf("vrf1", "65000:1", [], [], None)
        state.add_subnet("s1", "10.0.1.0/24", 100, 1, "10.0.1.1", "vrf1")
        state.add_subnet("s2", "10.0.2.0/24", 200, 2, "10.0.2.1", "vrf1")
        state.add_routing_adjacency("s1", "vrf1")
        state.add_routing_adjacency("s2", "vrf1")
        assert len(state.subnets) == 2
        assert len(state.vrfs) == 1


class TestIntentTranslator:
    """Tests for the IntentTranslator."""

    @pytest.mark.asyncio
    async def test_translate_simple_intent(self):
        translator = IntentTranslator()

        intent = IntentPayload(
            tenant=Tenant(name="Test-Tenant"),
            vpcs=[
                VPC(
                    name="vpc-1",
                    subnets=[
                        Subnet(name="subnet-web", cidr="10.100.1.0/24"),
                        Subnet(name="subnet-db", cidr="10.100.2.0/24"),
                    ],
                )
            ],
            dry_run=True,
        )

        state = await translator.translate(intent)

        # Should have 2 subnets + 1 VRF = 3 nodes
        assert len(state.subnets) == 2
        assert len(state.vrfs) == 1
        assert "subnet-web" in state.subnets
        assert "subnet-db" in state.subnets

    @pytest.mark.asyncio
    async def test_translate_generates_bridge_domains(self):
        translator = IntentTranslator()

        intent = IntentPayload(
            tenant=Tenant(name="Test"),
            vpcs=[
                VPC(
                    name="vpc-1",
                    subnets=[Subnet(name="s1", cidr="10.0.1.0/24")],
                )
            ],
        )

        state = await translator.translate(intent)
        assert len(state.bridge_domains) == 1

    @pytest.mark.asyncio
    async def test_generate_provisioning_plan(self):
        translator = IntentTranslator()

        intent = IntentPayload(
            tenant=Tenant(name="Test"),
            vpcs=[
                VPC(
                    name="vpc-1",
                    subnets=[
                        Subnet(name="s1", cidr="10.0.1.0/24"),
                    ],
                )
            ],
        )

        state = await translator.translate(intent)
        plan = await translator.generate_provisioning_plan(intent, state)

        assert "task_id" in plan
        assert len(plan["steps"]) > 0
        actions = [s["action"] for s in plan["steps"]]
        assert "create_vrf" in actions
        assert "create_bridge_domain" in actions

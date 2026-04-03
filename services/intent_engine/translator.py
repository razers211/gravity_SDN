"""
Intent Translator.

Translates high-level tenant intent payloads into:
  1. A formal NetworkState graph (networkx.DiGraph) for verification
  2. A concrete provisioning plan with NETCONF payloads for deployment

The translation process:
  - Resolves resource allocations (IP, VNI, RT/RD) from the Resource Manager
  - Builds the intended RIB/FIB as a directed graph
  - Maps tenant abstractions to physical fabric constructs (BD, VRF, VTEP)
"""

from __future__ import annotations

import logging
import uuid
from ipaddress import IPv4Network
from typing import Any

import httpx
import networkx as nx

from shared.config import get_settings
from shared.models.intent import IntentPayload, Subnet, VPC, Tenant

logger = logging.getLogger(__name__)

settings = get_settings()


class TranslationError(Exception):
    """Raised when intent translation fails."""


class NetworkState:
    """
    Formal mathematical representation of the intended network state.

    Models the RIB/FIB as a directed graph where:
      - Nodes: subnets, VRFs, devices (VTEPs), external endpoints
      - Edges: routing adjacencies with attributes (next-hop, metric, RT/RD)
    """

    def __init__(self):
        self.graph = nx.DiGraph()
        self.subnets: dict[str, dict[str, Any]] = {}
        self.vrfs: dict[str, dict[str, Any]] = {}
        self.bridge_domains: dict[int, dict[str, Any]] = {}
        self.route_targets: list[dict[str, Any]] = []
        self.vtep_bindings: list[dict[str, Any]] = []

    @property
    def nodes(self) -> Any:
        return self.graph.nodes

    @property
    def edges(self) -> Any:
        return self.graph.edges

    def add_subnet(
        self,
        subnet_id: str,
        cidr: str,
        vni: int,
        bd_id: int,
        gateway: str,
        vrf_name: str,
    ) -> None:
        """Add a subnet node to the network state graph."""
        self.graph.add_node(
            subnet_id,
            type="subnet",
            cidr=cidr,
            vni=vni,
            bd_id=bd_id,
            gateway=gateway,
            vrf_name=vrf_name,
        )
        self.subnets[subnet_id] = {
            "cidr": cidr,
            "vni": vni,
            "bd_id": bd_id,
            "gateway": gateway,
            "vrf_name": vrf_name,
        }

    def add_vrf(
        self,
        vrf_name: str,
        rd: str,
        import_rts: list[str],
        export_rts: list[str],
        l3_vni: int | None = None,
    ) -> None:
        """Add a VRF node to the network state graph."""
        self.graph.add_node(
            vrf_name,
            type="vrf",
            rd=rd,
            import_rts=import_rts,
            export_rts=export_rts,
            l3_vni=l3_vni,
        )
        self.vrfs[vrf_name] = {
            "rd": rd,
            "import_rts": import_rts,
            "export_rts": export_rts,
            "l3_vni": l3_vni,
        }

    def add_routing_adjacency(
        self,
        source: str,
        destination: str,
        route_type: str = "connected",
        metric: int = 0,
    ) -> None:
        """Add a routing adjacency (edge) between two network elements."""
        self.graph.add_edge(
            source,
            destination,
            route_type=route_type,
            metric=metric,
        )

    def add_inter_vrf_route(
        self,
        src_vrf: str,
        dst_vrf: str,
        leaked_prefix: str,
        import_rt: str,
    ) -> None:
        """Add a route leaking edge between VRFs."""
        self.graph.add_edge(
            src_vrf,
            dst_vrf,
            route_type="rt-import",
            prefix=leaked_prefix,
            import_rt=import_rt,
        )


class IntentTranslator:
    """
    Translates high-level tenant intents into formal network state
    and concrete provisioning plans.
    """

    def __init__(self):
        self._resource_client = httpx.AsyncClient(
            base_url=settings.resource_manager_url,
            timeout=10.0,
        )
        self._vni_counter = 10000  # Fallback VNI counter
        self._bd_counter = 100    # Fallback BD counter

    async def translate(self, intent: IntentPayload) -> NetworkState:
        """
        Translate an intent payload into a formal NetworkState.

        Steps:
          1. Create VRF for each VPC
          2. Allocate VNI and BD for each subnet
          3. Build RIB/FIB graph with routing adjacencies
          4. Model inter-subnet and inter-VPC route leaking
        """
        state = NetworkState()
        tenant = intent.tenant

        for vpc in intent.vpcs:
            await self._translate_vpc(state, tenant, vpc)

        logger.info(
            "Translation complete: %d nodes, %d edges, %d subnets, %d VRFs",
            len(state.nodes),
            len(state.edges),
            len(state.subnets),
            len(state.vrfs),
        )
        return state

    async def _translate_vpc(
        self,
        state: NetworkState,
        tenant: Tenant,
        vpc: VPC,
    ) -> None:
        """Translate a single VPC into VRF + Bridge Domains."""

        # Generate VRF name
        vrf_name = vpc.vrf_name or f"vrf-{tenant.name.lower()}-{vpc.name.lower()}"

        # Allocate Route Distinguisher and Route Targets
        rd = vpc.route_distinguisher or await self._allocate_rd(tenant.id, vpc.id)
        export_rt = f"{rd.split(':')[0]}:{self._bd_counter}"
        import_rt = export_rt  # Default: same RT for intra-VPC

        state.add_vrf(
            vrf_name=vrf_name,
            rd=rd,
            import_rts=[import_rt],
            export_rts=[export_rt],
            l3_vni=await self._allocate_vni("l3"),
        )

        # Translate each subnet
        for subnet in vpc.subnets:
            await self._translate_subnet(state, tenant, vpc, subnet, vrf_name)

        # Model firewall policies between subnets
        for policy in vpc.firewall_policies:
            for rule in policy.rules:
                if rule.action.value == "deny":
                    # Denied paths are modeled as missing edges (no adjacency)
                    logger.debug(
                        "Microsegmentation: %s → %s DENIED",
                        rule.source_subnet,
                        rule.destination_subnet,
                    )
                else:
                    # Permitted paths get routing adjacencies
                    state.add_routing_adjacency(
                        source=rule.source_subnet,
                        destination=rule.destination_subnet,
                        route_type="policy-permit",
                    )

    async def _translate_subnet(
        self,
        state: NetworkState,
        tenant: Tenant,
        vpc: VPC,
        subnet: Subnet,
        vrf_name: str,
    ) -> None:
        """Translate a single subnet into BD + VNI allocation."""
        # Allocate VNI
        vni = subnet.vni or await self._allocate_vni("l2")

        # Allocate Bridge Domain ID
        bd_id = self._bd_counter
        self._bd_counter += 1

        # Determine gateway IP
        network = IPv4Network(str(subnet.cidr))
        gateway = subnet.gateway or str(list(network.hosts())[0])

        state.add_subnet(
            subnet_id=subnet.name or subnet.id,
            cidr=str(subnet.cidr),
            vni=vni,
            bd_id=bd_id,
            gateway=gateway,
            vrf_name=vrf_name,
        )

        # Add routing adjacency: subnet → VRF (connected route)
        state.add_routing_adjacency(
            source=subnet.name or subnet.id,
            destination=vrf_name,
            route_type="connected",
        )

        # Store BD info for payload generation
        state.bridge_domains[bd_id] = {
            "bd_id": bd_id,
            "vni": vni,
            "subnet_cidr": str(subnet.cidr),
            "gateway": gateway,
            "vrf_name": vrf_name,
            "tenant_id": tenant.id,
            "vpc_id": vpc.id,
        }

    async def _allocate_vni(self, vni_type: str = "l2") -> int:
        """Allocate a VNI from the resource manager (with fallback)."""
        try:
            response = await self._resource_client.post(
                "/api/v1/resources/vni/allocate",
                json={"type": vni_type},
            )
            if response.status_code == 200:
                return response.json().get("vni", self._vni_counter)
        except httpx.HTTPError:
            logger.warning("Resource manager unavailable, using fallback VNI allocation")

        self._vni_counter += 1
        return self._vni_counter

    async def _allocate_rd(self, tenant_id: str, vpc_id: str) -> str:
        """Allocate a Route Distinguisher from the resource manager."""
        try:
            response = await self._resource_client.post(
                "/api/v1/resources/rd/allocate",
                json={"tenant_id": tenant_id, "vpc_id": vpc_id},
            )
            if response.status_code == 200:
                return response.json().get("rd", f"65000:{self._bd_counter}")
        except httpx.HTTPError:
            logger.warning("Resource manager unavailable, using fallback RD allocation")

        return f"65000:{self._bd_counter}"

    async def generate_provisioning_plan(
        self,
        intent: IntentPayload,
        state: NetworkState,
    ) -> dict[str, Any]:
        """
        Generate a concrete provisioning plan from the verified network state.

        Returns a structured plan with:
          - Target devices and their NETCONF payloads
          - Execution order (dependencies)
          - Rollback instructions
        """
        task_id = str(uuid.uuid4())

        plan = {
            "task_id": task_id,
            "intent_id": intent.id,
            "tenant_id": intent.tenant.id,
            "steps": [],
        }

        # Step 1: VRF creation on all leaf switches
        for vrf_name, vrf_data in state.vrfs.items():
            plan["steps"].append({
                "order": 1,
                "action": "create_vrf",
                "vrf_name": vrf_name,
                "rd": vrf_data["rd"],
                "import_rts": vrf_data["import_rts"],
                "export_rts": vrf_data["export_rts"],
                "l3_vni": vrf_data["l3_vni"],
            })

        # Step 2: Bridge Domain + VNI binding
        for bd_id, bd_data in state.bridge_domains.items():
            plan["steps"].append({
                "order": 2,
                "action": "create_bridge_domain",
                "bd_id": bd_id,
                "vni": bd_data["vni"],
                "vrf_name": bd_data["vrf_name"],
            })

        # Step 3: VBDIF anycast gateway
        for bd_id, bd_data in state.bridge_domains.items():
            plan["steps"].append({
                "order": 3,
                "action": "create_anycast_gateway",
                "bd_id": bd_id,
                "gateway_ip": bd_data["gateway"],
                "subnet_cidr": bd_data["subnet_cidr"],
                "vrf_name": bd_data["vrf_name"],
            })

        # Step 4: NVE VNI member registration
        for bd_id, bd_data in state.bridge_domains.items():
            plan["steps"].append({
                "order": 4,
                "action": "register_vni_on_nve",
                "vni": bd_data["vni"],
            })

        logger.info(
            "Provisioning plan generated: task_id=%s, steps=%d",
            task_id,
            len(plan["steps"]),
        )
        return plan

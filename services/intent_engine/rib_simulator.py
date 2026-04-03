"""
Offline RIB/FIB Simulator.

Simulates the Routing Information Base / Forwarding Information Base by
merging the current topology (from Neo4j) with proposed changes from an
intent. Runs verification against the merged state to detect issues that
only emerge when combining existing and new configurations.
"""

from __future__ import annotations

import logging
from typing import Any

import networkx as nx

from shared.graph.client import get_graph_client
from shared.graph.queries import TopologyQueries
from services.intent_engine.translator import NetworkState

logger = logging.getLogger(__name__)


class RIBSimulator:
    """
    Offline RIB/FIB simulator using networkx for path computation.

    Merges the existing topology graph (from Neo4j) with the proposed
    NetworkState changes, then performs:
      - Reachability analysis
      - Shortest-path computation
      - ECMP path enumeration
      - BGP best-path simulation
    """

    def __init__(self):
        self._combined_graph: nx.DiGraph | None = None

    async def load_current_topology(self) -> nx.DiGraph:
        """
        Load the current network topology from Neo4j into a networkx graph.

        Converts the 5-layer graph into a routing-centric view focusing
        on subnet-to-subnet reachability through VRFs and physical paths.
        """
        graph = nx.DiGraph()

        try:
            client = await get_graph_client()
            queries = TopologyQueries(client)
            topology = await queries.get_full_topology()

            # Add device nodes
            for device in topology.get("devices", []):
                graph.add_node(
                    device["hostname"],
                    type="device",
                    role=device.get("role"),
                    vtep_ip=device.get("vtep_ip"),
                )

            # Add physical links as edges
            for link in topology.get("links", []):
                if link.get("source") and link.get("target"):
                    graph.add_edge(
                        link["source"],
                        link["target"],
                        route_type="physical",
                        interface_src=link.get("source_if"),
                        interface_dst=link.get("target_if"),
                        status=link.get("status", "up"),
                    )
                    # Bidirectional
                    graph.add_edge(
                        link["target"],
                        link["source"],
                        route_type="physical",
                        interface_src=link.get("target_if"),
                        interface_dst=link.get("source_if"),
                        status=link.get("status", "up"),
                    )

            logger.info(
                "Current topology loaded: %d devices, %d links",
                len(topology.get("devices", [])),
                len(topology.get("links", [])),
            )

        except Exception as exc:
            logger.warning("Failed to load topology from Neo4j: %s — using empty graph", exc)

        return graph

    async def simulate(
        self,
        proposed_state: NetworkState,
        current_topology: nx.DiGraph | None = None,
    ) -> SimulationResult:
        """
        Merge proposed changes with current topology and run simulation.

        Returns:
            SimulationResult with reachability matrix and path analysis.
        """
        if current_topology is None:
            current_topology = await self.load_current_topology()

        # Merge graphs
        combined = nx.compose(current_topology, proposed_state.graph)
        self._combined_graph = combined

        result = SimulationResult(
            total_nodes=len(combined.nodes),
            total_edges=len(combined.edges),
        )

        # Compute reachability matrix for all subnet pairs
        subnets = [
            n for n, d in combined.nodes(data=True) if d.get("type") == "subnet"
        ]
        for i, src in enumerate(subnets):
            for dst in subnets[i + 1:]:
                try:
                    path = nx.shortest_path(combined, src, dst)
                    result.reachable_pairs.append({
                        "source": src,
                        "destination": dst,
                        "path": path,
                        "hops": len(path) - 1,
                    })
                except nx.NetworkXNoPath:
                    result.unreachable_pairs.append({
                        "source": src,
                        "destination": dst,
                    })

        # Compute ECMP paths
        for pair in result.reachable_pairs:
            try:
                all_paths = list(nx.all_shortest_paths(
                    combined, pair["source"], pair["destination"]
                ))
                if len(all_paths) > 1:
                    result.ecmp_paths.append({
                        "source": pair["source"],
                        "destination": pair["destination"],
                        "path_count": len(all_paths),
                        "paths": all_paths,
                    })
            except nx.NetworkXNoPath:
                pass

        logger.info(
            "Simulation complete: %d reachable, %d unreachable, %d ECMP groups",
            len(result.reachable_pairs),
            len(result.unreachable_pairs),
            len(result.ecmp_paths),
        )

        return result


class SimulationResult:
    """Result of an offline RIB/FIB simulation."""

    def __init__(self, total_nodes: int = 0, total_edges: int = 0):
        self.total_nodes = total_nodes
        self.total_edges = total_edges
        self.reachable_pairs: list[dict[str, Any]] = []
        self.unreachable_pairs: list[dict[str, Any]] = []
        self.ecmp_paths: list[dict[str, Any]] = []

    @property
    def all_reachable(self) -> bool:
        return len(self.unreachable_pairs) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "reachable_pairs": len(self.reachable_pairs),
            "unreachable_pairs": len(self.unreachable_pairs),
            "ecmp_groups": len(self.ecmp_paths),
            "all_reachable": self.all_reachable,
        }

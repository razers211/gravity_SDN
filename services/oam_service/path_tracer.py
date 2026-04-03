"""
End-to-End Path Computation Engine.

Computes forwarding paths between two endpoints (VM-to-VM, IP-to-IP)
by traversing the Neo4j 5-layer digital map using BFS/Dijkstra,
including VXLAN tunnel overlay hops.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PathHop(BaseModel):
    """A single hop in a computed path."""
    sequence: int
    device_id: str
    device_hostname: str = ""
    ingress_interface: str | None = None
    egress_interface: str | None = None
    hop_type: str = Field(default="transit", examples=["ingress", "transit", "egress", "tunnel"])
    encapsulation: str | None = Field(default=None, examples=["vxlan", "mpls", "none"])
    vni: int | None = None
    latency_us: float | None = None


class ComputedPath(BaseModel):
    """Result of an end-to-end path computation."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_ip: str
    destination_ip: str
    source_device: str | None = None
    destination_device: str | None = None
    hops: list[PathHop] = Field(default_factory=list)
    hop_count: int = 0
    total_latency_us: float | None = None
    path_type: str = Field(default="unicast", examples=["unicast", "ecmp", "bum"])
    ecmp_paths: int = 1
    status: str = Field(default="computed", examples=["computed", "unreachable", "partial"])
    computation_time_ms: float = 0.0


class PathTracer:
    """
    End-to-end path computation engine.

    Uses the Neo4j graph to trace forwarding paths across the
    VXLAN fabric, resolving VM → leaf → spine → leaf → VM paths.
    """

    def __init__(self, graph_client=None):
        self._graph = graph_client

    async def trace_path(
        self,
        source_ip: str,
        destination_ip: str,
    ) -> ComputedPath:
        """
        Compute the end-to-end forwarding path between two IPs.

        Resolution order:
          1. Resolve source IP → source VM → source server → ingress leaf
          2. Resolve destination IP → dest VM → dest server → egress leaf
          3. Compute underlay path: ingress leaf → spine(s) → egress leaf
          4. Overlay: VXLAN tunnel encap at ingress VTEP, decap at egress VTEP
        """
        start = time.monotonic()

        if not self._graph:
            return ComputedPath(
                source_ip=source_ip,
                destination_ip=destination_ip,
                status="unreachable",
                computation_time_ms=0.0,
            )

        try:
            # Step 1: Resolve source endpoint
            source_info = await self._resolve_endpoint(source_ip)
            dest_info = await self._resolve_endpoint(destination_ip)

            if not source_info or not dest_info:
                return ComputedPath(
                    source_ip=source_ip,
                    destination_ip=destination_ip,
                    status="unreachable",
                    computation_time_ms=(time.monotonic() - start) * 1000,
                )

            # Step 2: Compute path through fabric
            hops = await self._compute_fabric_path(source_info, dest_info)

            duration = (time.monotonic() - start) * 1000
            return ComputedPath(
                source_ip=source_ip,
                destination_ip=destination_ip,
                source_device=source_info.get("leaf_hostname"),
                destination_device=dest_info.get("leaf_hostname"),
                hops=hops,
                hop_count=len(hops),
                path_type="unicast",
                status="computed",
                computation_time_ms=duration,
            )

        except Exception as exc:
            logger.error("Path computation failed: %s → %s: %s", source_ip, destination_ip, exc)
            return ComputedPath(
                source_ip=source_ip,
                destination_ip=destination_ip,
                status="unreachable",
                computation_time_ms=(time.monotonic() - start) * 1000,
            )

    async def _resolve_endpoint(self, ip_address: str) -> dict[str, Any] | None:
        """Resolve an IP address to its leaf switch via the graph."""
        query = """
        MATCH (vm:VM {ip_address: $ip})-[:RUNS_ON]->(server:Server)
              -[:CONNECTED_TO_SWITCH]->(leaf:PhysicalDevice)
        RETURN vm.name AS vm_name, server.name AS server_name,
               leaf.device_id AS leaf_id, leaf.hostname AS leaf_hostname
        LIMIT 1
        """
        async with self._graph.session() as session:
            result = await session.run(query, ip=ip_address)
            record = await result.single()
            if record:
                return dict(record)
        return None

    async def _compute_fabric_path(
        self,
        source: dict[str, Any],
        dest: dict[str, Any],
    ) -> list[PathHop]:
        """Compute the underlay + overlay path through the fabric."""
        query = """
        MATCH path = shortestPath(
            (src:PhysicalDevice {device_id: $src_id})-[:CONNECTED_TO*]->
            (dst:PhysicalDevice {device_id: $dst_id})
        )
        RETURN [n IN nodes(path) | {
            device_id: n.device_id,
            hostname: n.hostname,
            role: n.role
        }] AS path_nodes
        """
        async with self._graph.session() as session:
            result = await session.run(
                query,
                src_id=source["leaf_id"],
                dst_id=dest["leaf_id"],
            )
            record = await result.single()

        hops = []
        if record:
            for i, node in enumerate(record["path_nodes"]):
                hop_type = "ingress" if i == 0 else ("egress" if i == len(record["path_nodes"]) - 1 else "transit")
                hops.append(PathHop(
                    sequence=i + 1,
                    device_id=node["device_id"],
                    device_hostname=node["hostname"],
                    hop_type=hop_type,
                    encapsulation="vxlan" if hop_type in ("ingress", "egress") else None,
                ))

        return hops

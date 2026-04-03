"""
Topology Router — Network Digital Map and topology visualization endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from services.api_gateway.auth import User, get_current_user

router = APIRouter()


@router.get("/topology", summary="Get full network topology")
async def get_topology(user: User = Depends(get_current_user)):
    """
    Return the complete 5-layer network topology from the graph database.

    Layers: PhysicalDevice → Server → VirtualNetwork → VM → Service
    """
    try:
        from shared.graph.client import get_graph_client
        from shared.graph.queries import TopologyQueries

        client = await get_graph_client()
        queries = TopologyQueries(client)
        topology = await queries.get_full_topology()
        return topology
    except Exception:
        return {"devices": [], "links": [], "error": "Graph database unavailable"}


@router.get("/topology/tenant/{tenant_id}", summary="Get tenant topology")
async def get_tenant_topology(tenant_id: str, user: User = Depends(get_current_user)):
    """Get all resources belonging to a specific tenant."""
    try:
        from shared.graph.client import get_graph_client
        from shared.graph.queries import TopologyQueries

        client = await get_graph_client()
        queries = TopologyQueries(client)
        return await queries.get_tenant_topology(tenant_id)
    except Exception:
        return {"virtual_networks": [], "devices": [], "vms": [], "services": []}


@router.get("/topology/impact/{device_id}", summary="Analyze device failure impact")
async def analyze_impact(
    device_id: str,
    interface: str | None = None,
    user: User = Depends(get_current_user),
):
    """
    Analyze the impact of a device or link failure using the graph database.
    Returns all affected resources across the 5-layer digital map.
    """
    try:
        from shared.graph.client import get_graph_client
        from shared.graph.queries import TopologyQueries

        client = await get_graph_client()
        queries = TopologyQueries(client)

        if interface:
            return await queries.get_impacted_by_link_failure(device_id, interface)
        return await queries.get_impacted_by_device_failure(device_id)

    except Exception:
        return {"impacted_devices": [], "impacted_vms": [], "impacted_services": []}

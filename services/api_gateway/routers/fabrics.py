"""
Fabrics Router — VXLAN fabric management endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from services.api_gateway.auth import User, get_current_user, require_role

router = APIRouter()


class FabricCreateRequest(BaseModel):
    name: str = "dc-fabric-01"
    spine_asn: int = 65000
    leaf_asn_range: str = "65001-65100"
    underlay_protocol: str = "OSPF"
    overlay_protocol: str = "iBGP-EVPN"


@router.get("/fabrics", summary="List all fabrics")
async def list_fabrics(user: User = Depends(get_current_user)):
    return {"fabrics": [], "total": 0}


@router.post("/fabrics", status_code=201, summary="Create a fabric")
async def create_fabric(
    request: FabricCreateRequest,
    user: User = Depends(require_role("admin")),
):
    return {
        "id": "fabric-001",
        "name": request.name,
        "status": "provisioning",
        "underlay": request.underlay_protocol,
        "overlay": request.overlay_protocol,
    }


@router.get("/fabrics/{fabric_id}", summary="Get fabric details")
async def get_fabric(fabric_id: str, user: User = Depends(get_current_user)):
    return {"id": fabric_id, "status": "active"}


@router.post("/fabrics/{fabric_id}/provision", summary="Provision fabric overlay")
async def provision_fabric(
    fabric_id: str,
    user: User = Depends(require_role("admin", "operator")),
):
    """Trigger full VXLAN overlay provisioning for a fabric."""
    return {"fabric_id": fabric_id, "action": "provision", "status": "in-progress"}

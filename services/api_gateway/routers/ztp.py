"""
ZTP Router — Zero Touch Provisioning endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from services.api_gateway.auth import User, get_current_user, require_role

router = APIRouter()


class ZTPRegistration(BaseModel):
    esn: str
    hostname: str | None = None
    role: str = "leaf"
    site: str = "dc-01"
    pod: str = "pod-01"


@router.post("/ztp/register", status_code=201, summary="Register device for ZTP")
async def register_for_ztp(
    registration: ZTPRegistration,
    user: User = Depends(require_role("admin", "operator")),
):
    """Pre-register a device ESN for Zero Touch Provisioning."""
    return {
        "esn": registration.esn,
        "status": "registered",
        "message": "Device registered for ZTP. Connect the switch to trigger onboarding.",
    }


@router.get("/ztp/devices", summary="List ZTP-discovered devices")
async def list_ztp_devices(user: User = Depends(get_current_user)):
    """List all devices discovered via ZTP."""
    return {"devices": [], "total": 0}


@router.get("/ztp/devices/{esn}", summary="Get ZTP device status")
async def get_ztp_status(esn: str, user: User = Depends(get_current_user)):
    """Get the onboarding status of a ZTP device by ESN."""
    return {"esn": esn, "status": "pending"}


@router.post("/ztp/devices/{esn}/retry", summary="Retry ZTP for a device")
async def retry_ztp(esn: str, user: User = Depends(require_role("admin", "operator"))):
    """Retry the ZTP onboarding process for a failed device."""
    return {"esn": esn, "action": "retry", "status": "in-progress"}

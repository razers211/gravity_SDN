"""
Devices Router — NBI endpoint for device inventory management.

GET    /api/v1/devices         — List all managed devices
POST   /api/v1/devices         — Register a new device
GET    /api/v1/devices/{id}    — Get device details
PUT    /api/v1/devices/{id}    — Update device configuration
DELETE /api/v1/devices/{id}    — Decommission a device
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from shared.models.device import Device, DeviceRole, DeviceStatus
from services.api_gateway.auth import User, get_current_user, require_role

router = APIRouter()

# In-memory device store
_devices: dict[str, Device] = {}


class DeviceRegistration(BaseModel):
    """Payload for registering a new device."""
    hostname: str
    management_ip: str
    esn: str
    model: str = "CE6800"
    role: DeviceRole = DeviceRole.LEAF
    site: str = "dc-01"
    pod: str = "pod-01"
    bgp_asn: int | None = None
    router_id: str | None = None
    vtep_ip: str | None = None


@router.get("/devices", summary="List all devices")
async def list_devices(
    role: DeviceRole | None = None,
    status_filter: DeviceStatus | None = None,
    user: User = Depends(get_current_user),
):
    """List all managed devices with optional filtering."""
    results = list(_devices.values())
    if role:
        results = [d for d in results if d.role == role]
    if status_filter:
        results = [d for d in results if d.status == status_filter]
    return {"devices": [d.model_dump() for d in results], "total": len(results)}


@router.post("/devices", status_code=status.HTTP_201_CREATED, summary="Register a new device")
async def register_device(
    registration: DeviceRegistration,
    user: User = Depends(require_role("admin", "operator")),
):
    """Register a new CloudEngine device in the inventory."""
    device = Device(
        hostname=registration.hostname,
        management_ip=registration.management_ip,
        esn=registration.esn,
        model=registration.model,
        role=registration.role,
        site=registration.site,
        pod=registration.pod,
        bgp_asn=registration.bgp_asn,
        router_id=registration.router_id,
        vtep_ip=registration.vtep_ip,
        status=DeviceStatus.DISCOVERED,
    )
    _devices[device.id] = device
    return {"id": device.id, "hostname": device.hostname, "status": device.status}


@router.get("/devices/{device_id}", summary="Get device details")
async def get_device(device_id: str, user: User = Depends(get_current_user)):
    """Retrieve detailed information about a specific device."""
    if device_id not in _devices:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")
    return _devices[device_id].model_dump()


@router.put("/devices/{device_id}", summary="Update a device")
async def update_device(
    device_id: str,
    updates: dict,
    user: User = Depends(require_role("admin", "operator")),
):
    """Update device properties."""
    if device_id not in _devices:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")
    device = _devices[device_id]
    for key, value in updates.items():
        if hasattr(device, key):
            setattr(device, key, value)
    return device.model_dump()


@router.delete("/devices/{device_id}", summary="Decommission a device")
async def decommission_device(
    device_id: str,
    user: User = Depends(require_role("admin")),
):
    """Mark a device as decommissioned."""
    if device_id not in _devices:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")
    _devices[device_id].status = DeviceStatus.DECOMMISSIONED
    return {"id": device_id, "status": "decommissioned"}

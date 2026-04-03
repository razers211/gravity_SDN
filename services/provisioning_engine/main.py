"""
NETCONF Provisioning Engine — Service Entry.

FastAPI microservice responsible for:
  - Executing ACID NETCONF transactions across the fabric
  - Building XML payloads from Jinja2 templates + domain models
  - Automating BGP EVPN peer construction and VXLAN gateway provisioning
"""

from __future__ import annotations

import logging

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

from shared.config import get_settings

settings = get_settings()

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.getLevelName(settings.log_level)
    ),
)
log = structlog.get_logger()

app = FastAPI(
    title="Gravity SDN — Provisioning Engine",
    description="ACID NETCONF Configuration Deployment Service",
    version="1.0.0",
)


class ProvisioningRequest(BaseModel):
    """Request to execute a provisioning plan."""
    intent_id: str
    task_id: str
    target_device_ids: list[str]
    plan_steps: list[dict]
    dry_run: bool = False


class ProvisioningResponse(BaseModel):
    """Response from provisioning execution."""
    transaction_id: str
    success: bool
    duration_ms: float
    device_results: dict
    error_message: str | None = None


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "provisioning-engine"}


@app.post("/api/v1/provision", response_model=ProvisioningResponse)
async def execute_provisioning(request: ProvisioningRequest) -> ProvisioningResponse:
    """Execute an ACID provisioning transaction across target devices."""
    from services.provisioning_engine.orchestrator import ProvisioningOrchestrator

    log.info(
        "provisioning.request",
        intent_id=request.intent_id,
        task_id=request.task_id,
        devices=len(request.target_device_ids),
    )

    try:
        orchestrator = ProvisioningOrchestrator()
        result = await orchestrator.execute_plan(request)

        return ProvisioningResponse(
            transaction_id=result.transaction_id,
            success=result.success,
            duration_ms=result.duration_ms,
            device_results=result.device_results,
            error_message=result.error_message,
        )

    except Exception as exc:
        log.error("provisioning.error", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


if __name__ == "__main__":
    uvicorn.run(
        "services.provisioning_engine.main:app",
        host="0.0.0.0",
        port=int(settings.service_port),
        reload=settings.environment == "development",
    )

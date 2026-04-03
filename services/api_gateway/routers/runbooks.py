"""
Runbooks Router — Runbook orchestration endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Any

from services.api_gateway.auth import User, get_current_user, require_role

router = APIRouter()


class RunbookExecuteRequest(BaseModel):
    runbook_yaml: str = Field(
        ...,
        description="YAML runbook definition",
        examples=[
            """
runbook:
  name: onboard-leaf-switch
  steps:
    - action: allocate_ip
      pool: loopback-pool
      output: loopback_ip
    - action: configure_vtep
      params:
        source_interface: "{{ loopback_ip }}"
    - action: apply_qos_profile
      profile: dc-leaf-default
    - action: register_in_topology
      role: leaf
"""
        ],
    )
    context: dict[str, Any] = Field(default_factory=dict, description="Initial context variables")


@router.post("/runbooks/execute", status_code=202, summary="Execute a runbook")
async def execute_runbook(
    request: RunbookExecuteRequest,
    user: User = Depends(require_role("admin", "operator")),
):
    """Parse and execute a YAML runbook definition."""
    from services.ztp_service.runbook_engine import RunbookEngine

    engine = RunbookEngine()
    runbook = RunbookEngine.parse_yaml(request.runbook_yaml)
    result = await engine.execute(runbook, initial_context=request.context)

    return {
        "execution_id": result.execution_id,
        "runbook_name": result.runbook_name,
        "status": result.status,
        "steps_completed": len([s for s in result.step_results if s.status == "success"]),
        "steps_total": len(result.step_results),
        "context": result.context,
        "error": result.error,
    }


@router.get("/runbooks/executions", summary="List runbook executions")
async def list_executions(user: User = Depends(get_current_user)):
    return {"executions": [], "total": 0}


@router.get("/runbooks/executions/{execution_id}", summary="Get execution status")
async def get_execution(execution_id: str, user: User = Depends(get_current_user)):
    return {"execution_id": execution_id, "status": "unknown"}

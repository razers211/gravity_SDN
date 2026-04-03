"""
Runbook Execution Engine.

Defines the JSON/YAML schema for runbooks and provides an execution
engine that sequences discrete tasks into automated workflows.

Example runbook:
  - Allocate IP from Pool
  - Configure VTEP
  - Apply QoS Profile
  - Register in Topology

Each step invokes the internal Network Resource Dictionary dynamically.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Runbook Schema ───────────────────────────────────────────────────────────


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunbookStep(BaseModel):
    """A single step in a runbook."""
    action: str = Field(..., examples=["allocate_ip", "configure_vtep", "apply_qos_profile"])
    params: dict[str, Any] = Field(default_factory=dict)
    pool: str | None = None
    profile: str | None = None
    output: str | None = Field(default=None, description="Variable name to store step output")
    role: str | None = None
    condition: str | None = Field(default=None, description="Jinja2 condition expression")
    on_failure: str = Field(default="abort", examples=["abort", "skip", "retry"])
    max_retries: int = Field(default=1, ge=1, le=5)


class RunbookDefinition(BaseModel):
    """Complete runbook definition."""
    name: str = Field(..., examples=["onboard-leaf-switch"])
    description: str = ""
    version: str = "1.0"
    tags: list[str] = Field(default_factory=list)
    steps: list[RunbookStep] = Field(default_factory=list)


class StepResult(BaseModel):
    """Result of a single runbook step execution."""
    step_index: int
    action: str
    status: StepStatus
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0


class RunbookResult(BaseModel):
    """Result of a complete runbook execution."""
    execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    runbook_name: str
    status: StepStatus
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    step_results: list[StepResult] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


# ── Action Handlers ──────────────────────────────────────────────────────────


class RunbookEngine:
    """
    Executes runbook definitions by sequencing steps and invoking
    the Network Resource Dictionary for each action.

    Supported actions:
      - allocate_ip: Allocate an IP from a named pool
      - configure_vtep: Configure VTEP on a device
      - apply_qos_profile: Apply a QoS profile
      - register_in_topology: Register device in the graph DB
      - configure_bgp: Configure BGP peering
      - configure_underlay: Deploy underlay routing config
      - run_netconf: Execute arbitrary NETCONF RPC
    """

    def __init__(self):
        self._action_handlers: dict[str, Any] = {
            "allocate_ip": self._handle_allocate_ip,
            "configure_vtep": self._handle_configure_vtep,
            "apply_qos_profile": self._handle_apply_qos_profile,
            "register_in_topology": self._handle_register_topology,
            "configure_bgp": self._handle_configure_bgp,
            "configure_underlay": self._handle_configure_underlay,
            "run_netconf": self._handle_run_netconf,
        }

    @classmethod
    def parse_yaml(cls, yaml_content: str) -> RunbookDefinition:
        """Parse a YAML runbook definition."""
        data = yaml.safe_load(yaml_content)
        runbook_data = data.get("runbook", data)
        return RunbookDefinition(**runbook_data)

    async def execute(
        self,
        runbook: RunbookDefinition,
        initial_context: dict[str, Any] | None = None,
    ) -> RunbookResult:
        """
        Execute a runbook definition step-by-step.

        Each step can output variables that subsequent steps reference
        via Jinja2 template syntax in their params.
        """
        import time

        result = RunbookResult(
            runbook_name=runbook.name,
            status=StepStatus.RUNNING,
            context=initial_context or {},
        )

        logger.info("Executing runbook: %s (%d steps)", runbook.name, len(runbook.steps))

        for i, step in enumerate(runbook.steps):
            step_start = time.monotonic()

            logger.info("Step %d/%d: %s", i + 1, len(runbook.steps), step.action)

            # Resolve template params from context
            resolved_params = self._resolve_params(step.params, result.context)

            handler = self._action_handlers.get(step.action)
            if not handler:
                step_result = StepResult(
                    step_index=i,
                    action=step.action,
                    status=StepStatus.FAILED,
                    error=f"Unknown action: {step.action}",
                )
                result.step_results.append(step_result)

                if step.on_failure == "abort":
                    result.status = StepStatus.FAILED
                    result.error = f"Step {i} failed: unknown action '{step.action}'"
                    break
                continue

            # Execute with retry logic
            step_result = await self._execute_with_retry(
                handler, step, resolved_params, i
            )
            step_result.duration_ms = (time.monotonic() - step_start) * 1000
            result.step_results.append(step_result)

            # Store output in context
            if step.output and step_result.output:
                result.context[step.output] = step_result.output

            # Handle failure
            if step_result.status == StepStatus.FAILED:
                if step.on_failure == "abort":
                    result.status = StepStatus.FAILED
                    result.error = f"Step {i} ({step.action}) failed: {step_result.error}"
                    break
                elif step.on_failure == "skip":
                    logger.warning("Step %d failed but marked as skip — continuing", i)

        if result.status == StepStatus.RUNNING:
            result.status = StepStatus.SUCCESS

        result.completed_at = datetime.utcnow()

        logger.info(
            "Runbook %s completed: status=%s, steps=%d",
            runbook.name,
            result.status,
            len(result.step_results),
        )
        return result

    async def _execute_with_retry(
        self,
        handler: Any,
        step: RunbookStep,
        params: dict[str, Any],
        index: int,
    ) -> StepResult:
        """Execute a step handler with retry logic."""
        last_error = None
        for attempt in range(step.max_retries):
            try:
                output = await handler(params, step)
                return StepResult(
                    step_index=index,
                    action=step.action,
                    status=StepStatus.SUCCESS,
                    output=output or {},
                )
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "Step %d attempt %d failed: %s",
                    index, attempt + 1, exc,
                )

        return StepResult(
            step_index=index,
            action=step.action,
            status=StepStatus.FAILED,
            error=last_error,
        )

    def _resolve_params(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve Jinja2 template expressions in step parameters."""
        from jinja2 import Template

        resolved = {}
        for key, value in params.items():
            if isinstance(value, str) and "{{" in value:
                template = Template(value)
                resolved[key] = template.render(**context)
            else:
                resolved[key] = value
        return resolved

    # ── Action Handlers ──────────────────────────────────────────────────

    async def _handle_allocate_ip(
        self, params: dict[str, Any], step: RunbookStep
    ) -> dict[str, Any]:
        """Allocate an IP address from a named pool."""
        pool = step.pool or params.get("pool", "default")
        logger.info("Allocating IP from pool: %s", pool)
        # Would call Resource Manager in production
        return {"ip_address": "10.0.0.1", "pool": pool}

    async def _handle_configure_vtep(
        self, params: dict[str, Any], step: RunbookStep
    ) -> dict[str, Any]:
        """Configure VTEP on a device."""
        source_if = params.get("source_interface", "LoopBack1")
        logger.info("Configuring VTEP: source=%s", source_if)
        return {"vtep_configured": True, "source_interface": source_if}

    async def _handle_apply_qos_profile(
        self, params: dict[str, Any], step: RunbookStep
    ) -> dict[str, Any]:
        """Apply a QoS profile to a device."""
        profile = step.profile or params.get("profile", "default")
        logger.info("Applying QoS profile: %s", profile)
        return {"qos_profile": profile, "applied": True}

    async def _handle_register_topology(
        self, params: dict[str, Any], step: RunbookStep
    ) -> dict[str, Any]:
        """Register device in the topology graph database."""
        role = step.role or params.get("role", "leaf")
        logger.info("Registering in topology: role=%s", role)
        return {"registered": True, "role": role}

    async def _handle_configure_bgp(
        self, params: dict[str, Any], step: RunbookStep
    ) -> dict[str, Any]:
        """Configure BGP peering."""
        logger.info("Configuring BGP: %s", params)
        return {"bgp_configured": True}

    async def _handle_configure_underlay(
        self, params: dict[str, Any], step: RunbookStep
    ) -> dict[str, Any]:
        """Configure underlay routing (OSPF/IS-IS)."""
        logger.info("Configuring underlay: %s", params)
        return {"underlay_configured": True}

    async def _handle_run_netconf(
        self, params: dict[str, Any], step: RunbookStep
    ) -> dict[str, Any]:
        """Execute an arbitrary NETCONF RPC."""
        logger.info("Running NETCONF RPC: %s", params.get("rpc", ""))
        return {"netconf_executed": True}

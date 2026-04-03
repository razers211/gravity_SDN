"""
Intent Translation & Formal Verification Engine — Service Entry.

FastAPI microservice responsible for:
  - Ingesting high-level tenant intents from the NBI
  - Translating intents into formal network state models
  - Running formal verification (routing loops, IP conflicts, policy violations)
  - Generating NETCONF provisioning plans on verification pass
"""

from __future__ import annotations

import logging

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, status

from shared.config import get_settings
from shared.models.intent import IntentPayload, IntentResult, IntentStatus
from services.intent_engine.translator import IntentTranslator
from services.intent_engine.verifier import FormalVerifier

settings = get_settings()

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.getLevelName(settings.log_level)
    ),
)
log = structlog.get_logger()

app = FastAPI(
    title="Gravity SDN — Intent Engine",
    description="Intent Translation & Formal Verification Service",
    version="1.0.0",
)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "intent-engine"}


@app.post("/api/v1/intents/translate", response_model=IntentResult)
async def translate_and_verify(payload: IntentPayload) -> IntentResult:
    """
    Translate a tenant intent and run formal verification.

    1. Parse and enrich the intent payload
    2. Translate to formal network state model
    3. Verify: no routing loops, IP conflicts, or policy violations
    4. Return verification result (pass/fail with violation details)
    """
    log.info("intent.received", intent_id=payload.id, tenant=payload.tenant.name)

    translator = IntentTranslator()
    verifier = FormalVerifier()

    try:
        # Step 1: Translate intent → formal network state
        payload.status = IntentStatus.VALIDATING
        network_state = await translator.translate(payload)
        log.info("intent.translated", intent_id=payload.id, nodes=len(network_state.nodes))

        # Step 2: Formal verification
        verification = verifier.verify(network_state, payload)
        log.info(
            "intent.verified",
            intent_id=payload.id,
            passed=verification.passed,
            violations=len(verification.violations),
        )

        if not verification.passed:
            return IntentResult(
                intent_id=payload.id,
                status=IntentStatus.FAILED,
                verification=verification,
                error_message=f"Verification failed with {len(verification.violations)} violation(s)",
            )

        # Step 3: Generate provisioning plan (if not dry-run)
        provisioning_task_id = None
        if not payload.dry_run:
            provisioning_plan = await translator.generate_provisioning_plan(payload, network_state)
            provisioning_task_id = provisioning_plan.get("task_id")
            payload.status = IntentStatus.VERIFIED

        return IntentResult(
            intent_id=payload.id,
            status=IntentStatus.VERIFIED,
            verification=verification,
            provisioning_task_id=provisioning_task_id,
        )

    except Exception as exc:
        log.error("intent.error", intent_id=payload.id, error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Intent processing failed: {exc}",
        ) from exc


if __name__ == "__main__":
    uvicorn.run(
        "services.intent_engine.main:app",
        host="0.0.0.0",
        port=int(settings.service_port),
        reload=settings.environment == "development",
    )

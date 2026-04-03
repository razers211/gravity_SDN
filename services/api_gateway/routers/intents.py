"""
Intents Router — NBI endpoint for tenant intent lifecycle.

POST /api/v1/intents         — Submit and process a tenant intent
GET  /api/v1/intents/{id}    — Get intent status
POST /api/v1/auth/token      — OAuth2 token endpoint
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from shared.models.intent import IntentPayload, IntentResult, IntentStatus
from services.api_gateway.auth import (
    Token,
    User,
    authenticate_user,
    create_access_token,
    get_current_user,
    require_role,
)

router = APIRouter()

# In-memory intent store (replace with DB in production)
_intents: dict[str, IntentResult] = {}


@router.post("/auth/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """OAuth2 password flow — issue JWT access token."""
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(data={"sub": user.username, "role": user.role})
    return Token(access_token=token, expires_in=3600)


@router.post(
    "/intents",
    response_model=IntentResult,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a tenant intent",
    description=(
        "Translates a high-level tenant intent into formal network state, "
        "runs verification, and triggers provisioning on success."
    ),
)
async def create_intent(
    payload: IntentPayload,
    user: User = Depends(require_role("admin", "operator")),
) -> IntentResult:
    """
    Complete intent processing pipeline:
      1. Translate high-level intent → formal model
      2. Verify: no routing loops, IP conflicts, or policy violations
      3. Generate NETCONF provisioning plan
      4. Execute ACID NETCONF transactions (unless dry-run)
    """
    from services.intent_engine.translator import IntentTranslator
    from services.intent_engine.verifier import FormalVerifier

    translator = IntentTranslator()
    verifier = FormalVerifier()

    # Step 1: Translate
    payload.status = IntentStatus.VALIDATING
    network_state = await translator.translate(payload)

    # Step 2: Verify
    verification = verifier.verify(network_state, payload)

    if not verification.passed:
        result = IntentResult(
            intent_id=payload.id,
            status=IntentStatus.FAILED,
            verification=verification,
            error_message=f"Verification failed with {len(verification.violations)} violation(s)",
        )
        _intents[payload.id] = result
        return result

    # Step 3: Generate provisioning plan
    provisioning_task_id = None
    if not payload.dry_run:
        plan = await translator.generate_provisioning_plan(payload, network_state)
        provisioning_task_id = plan.get("task_id")

    result = IntentResult(
        intent_id=payload.id,
        status=IntentStatus.VERIFIED if payload.dry_run else IntentStatus.PROVISIONING,
        verification=verification,
        provisioning_task_id=provisioning_task_id,
    )
    _intents[payload.id] = result
    return result


@router.get(
    "/intents/{intent_id}",
    response_model=IntentResult,
    summary="Get intent status",
)
async def get_intent(
    intent_id: str,
    user: User = Depends(get_current_user),
) -> IntentResult:
    """Retrieve the current status of an intent by ID."""
    if intent_id not in _intents:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Intent '{intent_id}' not found",
        )
    return _intents[intent_id]


@router.get("/intents", summary="List all intents")
async def list_intents(
    user: User = Depends(get_current_user),
    status_filter: IntentStatus | None = None,
):
    """List all intents, optionally filtered by status."""
    results = list(_intents.values())
    if status_filter:
        results = [r for r in results if r.status == status_filter]
    return {"intents": results, "total": len(results)}

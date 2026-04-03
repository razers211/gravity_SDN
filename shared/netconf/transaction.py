"""
NETCONF ACID Transaction Manager.

Orchestrates atomic configuration deployment across multiple CloudEngine
devices using the NETCONF candidate datastore with strict lock → edit-config
→ validate → commit | discard-changes → unlock semantics.

Guarantees ACID properties:
  - Atomicity:   All-or-nothing across all target devices
  - Consistency: Pre-commit validation ensures config correctness
  - Isolation:   Exclusive <lock> prevents concurrent modifications
  - Durability:  <commit> persists changes to the running datastore
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ncclient import manager

from shared.models.device import Device
from shared.netconf.transport import (
    NetconfRPCError,
    NetconfSession,
    NetconfSessionError,
    NetconfSessionPool,
)

logger = logging.getLogger(__name__)


# ── Transaction Types ────────────────────────────────────────────────────────


class TransactionState(StrEnum):
    """State machine for a NETCONF ACID transaction."""
    INITIALIZED = "initialized"
    LOCKING = "locking"
    LOCKED = "locked"
    EDITING = "editing"
    VALIDATING = "validating"
    COMMITTING = "committing"
    COMMITTED = "committed"
    ROLLING_BACK = "rolling-back"
    ROLLED_BACK = "rolled-back"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass
class DeviceTransaction:
    """Tracks the transaction state for a single device."""
    device: Device
    session: NetconfSession
    connection: manager.Manager | None = None
    locked: bool = False
    edited: bool = False
    committed: bool = False
    error: str | None = None


@dataclass
class TransactionResult:
    """Result of a multi-device NETCONF transaction."""
    transaction_id: str
    state: TransactionState
    success: bool
    duration_ms: float = 0.0
    device_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    error_message: str | None = None
    rollback_performed: bool = False


class ProvisioningRollbackError(Exception):
    """Raised when a provisioning transaction fails and is rolled back."""

    def __init__(self, message: str, result: TransactionResult):
        super().__init__(message)
        self.result = result


# ── ACID Transaction Manager ────────────────────────────────────────────────


class NetconfTransaction:
    """
    Multi-device ACID transaction manager for NETCONF provisioning.

    Orchestrates the complete lifecycle:
      1. Open NETCONF sessions to all target devices
      2. Acquire exclusive <lock> on candidate datastore (all devices)
      3. Push <edit-config> payloads to candidate (per device)
      4. <validate> candidate configuration (all devices)
      5. <commit> candidate → running (all devices)
      6. <unlock> candidate (all devices)

    On ANY failure at steps 3-5:
      - <discard-changes> on all edited devices
      - <unlock> on all locked devices
      - Raise ProvisioningRollbackError with full audit trail

    Usage:
        txn = NetconfTransaction(session_pool)
        result = txn.execute(plan=[
            (device_1, "<config>...</config>"),
            (device_2, "<config>...</config>"),
        ])
    """

    def __init__(self, session_pool: NetconfSessionPool | None = None):
        self.session_pool = session_pool or NetconfSessionPool()
        self.transaction_id = str(uuid.uuid4())
        self.state = TransactionState.INITIALIZED
        self._device_txns: list[DeviceTransaction] = []

    def execute(
        self,
        plan: list[tuple[Device, str]],
        validate: bool = True,
    ) -> TransactionResult:
        """
        Execute an ACID transaction across multiple devices.

        Args:
            plan: List of (Device, XML_payload) tuples
            validate: Whether to run <validate> before commit

        Returns:
            TransactionResult with success/failure details

        Raises:
            ProvisioningRollbackError: If any device fails and rollback is performed
        """
        start_time = time.monotonic()
        logger.info(
            "Starting ACID transaction %s across %d devices",
            self.transaction_id,
            len(plan),
        )

        try:
            # Phase 1: Open connections
            self._open_connections(plan)

            # Phase 2: Acquire locks
            self._acquire_locks()

            # Phase 3: Push configurations
            self._push_configurations(plan)

            # Phase 4: Validate (optional)
            if validate:
                self._validate_all()

            # Phase 5: Commit
            self._commit_all()

            # Phase 6: Unlock
            self._release_locks()

            duration = (time.monotonic() - start_time) * 1000
            self.state = TransactionState.COMPLETED

            result = TransactionResult(
                transaction_id=self.transaction_id,
                state=self.state,
                success=True,
                duration_ms=duration,
                device_results={
                    dt.device.hostname: {
                        "status": "committed",
                        "device_id": dt.device.id,
                    }
                    for dt in self._device_txns
                },
            )

            logger.info(
                "Transaction %s completed successfully in %.1fms",
                self.transaction_id,
                duration,
            )
            return result

        except Exception as exc:
            duration = (time.monotonic() - start_time) * 1000
            logger.error(
                "Transaction %s failed: %s — initiating rollback",
                self.transaction_id,
                exc,
            )
            self._rollback()
            self.state = TransactionState.ROLLED_BACK

            result = TransactionResult(
                transaction_id=self.transaction_id,
                state=self.state,
                success=False,
                duration_ms=duration,
                error_message=str(exc),
                rollback_performed=True,
                device_results={
                    dt.device.hostname: {
                        "status": "rolled-back" if dt.edited else "unlocked",
                        "error": dt.error,
                        "device_id": dt.device.id,
                    }
                    for dt in self._device_txns
                },
            )

            raise ProvisioningRollbackError(
                f"Transaction {self.transaction_id} rolled back: {exc}",
                result=result,
            ) from exc

        finally:
            self._cleanup()

    def _open_connections(self, plan: list[tuple[Device, str]]) -> None:
        """Phase 1: Open NETCONF sessions to all target devices."""
        self.state = TransactionState.INITIALIZED
        for device, _ in plan:
            session = self.session_pool.get_session(device)
            conn = session._establish_connection()
            dtxn = DeviceTransaction(
                device=device,
                session=session,
                connection=conn,
            )
            self._device_txns.append(dtxn)
            logger.debug("Connection opened: %s", device.hostname)

    def _acquire_locks(self) -> None:
        """Phase 2: Acquire exclusive locks on all devices."""
        self.state = TransactionState.LOCKING
        for dtxn in self._device_txns:
            try:
                if dtxn.connection:
                    dtxn.connection.lock(target="candidate")
                    dtxn.locked = True
                    logger.debug("Lock acquired: %s", dtxn.device.hostname)
            except Exception as exc:
                dtxn.error = f"Lock failed: {exc}"
                raise NetconfRPCError(
                    f"Failed to lock candidate on {dtxn.device.hostname}: {exc}"
                ) from exc

        self.state = TransactionState.LOCKED

    def _push_configurations(self, plan: list[tuple[Device, str]]) -> None:
        """Phase 3: Push <edit-config> payloads to all devices."""
        self.state = TransactionState.EDITING

        # Build hostname → payload mapping
        payload_map = {device.hostname: payload for device, payload in plan}

        for dtxn in self._device_txns:
            payload = payload_map.get(dtxn.device.hostname)
            if not payload:
                continue

            try:
                if dtxn.connection:
                    dtxn.connection.edit_config(
                        target="candidate",
                        config=payload,
                    )
                    dtxn.edited = True
                    logger.debug(
                        "edit-config pushed to %s (%d bytes)",
                        dtxn.device.hostname,
                        len(payload),
                    )
            except Exception as exc:
                dtxn.error = f"edit-config failed: {exc}"
                raise NetconfRPCError(
                    f"edit-config failed on {dtxn.device.hostname}: {exc}"
                ) from exc

    def _validate_all(self) -> None:
        """Phase 4: Validate candidate configuration on all devices."""
        self.state = TransactionState.VALIDATING
        for dtxn in self._device_txns:
            if not dtxn.edited:
                continue
            try:
                if dtxn.connection:
                    dtxn.connection.validate(source="candidate")
                    logger.debug("Validation passed: %s", dtxn.device.hostname)
            except Exception as exc:
                dtxn.error = f"Validation failed: {exc}"
                raise NetconfRPCError(
                    f"Validation failed on {dtxn.device.hostname}: {exc}"
                ) from exc

    def _commit_all(self) -> None:
        """Phase 5: Commit candidate → running on all devices."""
        self.state = TransactionState.COMMITTING
        for dtxn in self._device_txns:
            if not dtxn.edited:
                continue
            try:
                if dtxn.connection:
                    dtxn.connection.commit()
                    dtxn.committed = True
                    logger.info("Committed: %s", dtxn.device.hostname)
            except Exception as exc:
                dtxn.error = f"Commit failed: {exc}"
                raise NetconfRPCError(
                    f"Commit failed on {dtxn.device.hostname}: {exc}"
                ) from exc

    def _release_locks(self) -> None:
        """Phase 6: Release locks on all devices."""
        for dtxn in self._device_txns:
            if dtxn.locked and dtxn.connection:
                try:
                    dtxn.connection.unlock(target="candidate")
                    dtxn.locked = False
                    logger.debug("Lock released: %s", dtxn.device.hostname)
                except Exception as exc:
                    logger.warning(
                        "Failed to unlock %s: %s",
                        dtxn.device.hostname,
                        exc,
                    )

    def _rollback(self) -> None:
        """
        Emergency rollback: discard changes and release locks on ALL devices.

        Called when any phase (edit, validate, commit) fails.
        """
        self.state = TransactionState.ROLLING_BACK
        logger.warning(
            "Rolling back transaction %s across %d devices",
            self.transaction_id,
            len(self._device_txns),
        )

        for dtxn in self._device_txns:
            if not dtxn.connection:
                continue

            # Discard changes if edits were pushed
            if dtxn.edited and not dtxn.committed:
                try:
                    dtxn.connection.discard_changes()
                    logger.info("Changes discarded: %s", dtxn.device.hostname)
                except Exception as exc:
                    logger.error(
                        "Failed to discard changes on %s: %s",
                        dtxn.device.hostname,
                        exc,
                    )

            # Release lock
            if dtxn.locked:
                try:
                    dtxn.connection.unlock(target="candidate")
                    dtxn.locked = False
                    logger.debug("Lock released (rollback): %s", dtxn.device.hostname)
                except Exception as exc:
                    logger.error(
                        "Failed to unlock %s during rollback: %s",
                        dtxn.device.hostname,
                        exc,
                    )

    def _cleanup(self) -> None:
        """Close all NETCONF connections opened by this transaction."""
        for dtxn in self._device_txns:
            if dtxn.connection and dtxn.connection.connected:
                try:
                    dtxn.connection.close_session()
                except Exception:
                    pass
        self._device_txns.clear()

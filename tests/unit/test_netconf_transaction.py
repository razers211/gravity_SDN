"""
Unit tests for the NETCONF Transaction Manager.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from shared.netconf.transaction import (
    NetconfTransaction,
    TransactionState,
    TransactionResult,
    ProvisioningRollbackError,
    DeviceTransaction,
)
from shared.models.device import Device


@pytest.fixture
def mock_device():
    return Device(
        hostname="ce-test-01",
        management_ip="10.255.0.1",
        esn="TEST-001",
    )


@pytest.fixture
def mock_device_2():
    return Device(
        hostname="ce-test-02",
        management_ip="10.255.0.2",
        esn="TEST-002",
    )


class TestTransactionState:
    """Tests for transaction state machine."""

    def test_initial_state(self):
        txn = NetconfTransaction()
        assert txn.state == TransactionState.INITIALIZED

    def test_transaction_id_unique(self):
        txn1 = NetconfTransaction()
        txn2 = NetconfTransaction()
        assert txn1.transaction_id != txn2.transaction_id


class TestTransactionResult:
    """Tests for TransactionResult model."""

    def test_success_result(self):
        result = TransactionResult(
            transaction_id="test-123",
            state=TransactionState.COMPLETED,
            success=True,
            duration_ms=150.5,
        )
        assert result.success
        assert result.state == TransactionState.COMPLETED

    def test_failure_result(self):
        result = TransactionResult(
            transaction_id="test-456",
            state=TransactionState.ROLLED_BACK,
            success=False,
            error_message="Connection refused",
            rollback_performed=True,
        )
        assert not result.success
        assert result.rollback_performed


class TestProvisioningRollbackError:
    """Tests for the rollback error."""

    def test_rollback_error_contains_result(self):
        result = TransactionResult(
            transaction_id="err-001",
            state=TransactionState.ROLLED_BACK,
            success=False,
        )
        error = ProvisioningRollbackError("Test rollback", result=result)
        assert error.result.transaction_id == "err-001"
        assert "Test rollback" in str(error)


class TestDeviceTransaction:
    """Tests for per-device transaction tracking."""

    def test_initial_state(self, mock_device):
        from shared.netconf.transport import NetconfSession
        session = NetconfSession(mock_device)
        dtxn = DeviceTransaction(device=mock_device, session=session)
        assert not dtxn.locked
        assert not dtxn.edited
        assert not dtxn.committed
        assert dtxn.error is None

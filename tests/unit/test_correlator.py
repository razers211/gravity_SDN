"""
Unit tests for the 1-3-5 Troubleshooting Correlator.
"""

from __future__ import annotations

import pytest

from shared.models.telemetry import (
    Alarm,
    AlarmCategory,
    AlarmSeverity,
    TelemetrySource,
    ImpactReport,
    RemediationRecord,
    RemediationStatus,
)
from services.oam_service.correlator import TroubleshootingCorrelator, CorrelationSession


@pytest.fixture
def correlator():
    return TroubleshootingCorrelator()


@pytest.fixture
def critical_alarm():
    return Alarm(
        device_id="device-001",
        severity=AlarmSeverity.CRITICAL,
        category=AlarmCategory.LINK,
        source=TelemetrySource.YANG_PUSH,
        title="Interface 10GE1/0/1 Link Down",
        message="Interface 10GE1/0/1 on device-001 is DOWN",
        interface_name="10GE1/0/1",
    )


@pytest.fixture
def minor_alarm():
    return Alarm(
        device_id="device-002",
        severity=AlarmSeverity.MINOR,
        category=AlarmCategory.QOS,
        source=TelemetrySource.SYSLOG,
        title="QoS queue drop",
        message="Minor QoS drops detected",
    )


class TestAlarmFiltering:
    """Tests for alarm severity filtering."""

    @pytest.mark.asyncio
    async def test_critical_alarm_triggers_pipeline(self, correlator, critical_alarm):
        session = await correlator.on_alarm(critical_alarm)
        assert session is not None
        assert session.trigger_alarm.id == critical_alarm.id

    @pytest.mark.asyncio
    async def test_minor_alarm_skipped(self, correlator, minor_alarm):
        # Minor alarms (below MAJOR) should not trigger 1-3-5
        session = await correlator.on_alarm(minor_alarm)
        assert session is None


class TestCorrelationDeduplication:
    """Tests for alarm correlation and deduplication."""

    @pytest.mark.asyncio
    async def test_same_device_interface_correlates(self, correlator):
        alarm1 = Alarm(
            device_id="device-001",
            severity=AlarmSeverity.MAJOR,
            category=AlarmCategory.LINK,
            source=TelemetrySource.YANG_PUSH,
            title="Link Down",
            interface_name="10GE1/0/1",
        )
        alarm2 = Alarm(
            device_id="device-001",
            severity=AlarmSeverity.MAJOR,
            category=AlarmCategory.LINK,
            source=TelemetrySource.BFD,
            title="BFD Down",
            interface_name="10GE1/0/1",
        )

        session1 = await correlator.on_alarm(alarm1)
        session2 = await correlator.on_alarm(alarm2)

        assert session1 is not None
        assert session2 is not None
        # Second alarm should be correlated to the same session
        assert session2.correlation_id == session1.correlation_id
        assert len(session2.correlated_alarms) == 2


class TestCorrelationSession:
    """Tests for CorrelationSession model."""

    def test_session_creation(self, critical_alarm):
        session = CorrelationSession(
            correlation_id="test-corr-001",
            trigger_alarm=critical_alarm,
        )
        assert session.correlation_id == "test-corr-001"
        assert session.phase == "initialized"
        assert session.sla_met is False

    def test_session_to_dict(self, critical_alarm):
        session = CorrelationSession(
            correlation_id="test-corr-002",
            trigger_alarm=critical_alarm,
        )
        d = session.to_dict()
        assert d["correlation_id"] == "test-corr-002"
        assert d["phase"] == "initialized"
        assert "trigger_alarm" in d


class TestImpactReport:
    """Tests for ImpactReport model."""

    def test_impact_report_creation(self):
        report = ImpactReport(
            alarm_id="alarm-001",
            fault_device_id="device-001",
            fault_interface="10GE1/0/1",
            fault_type="link-down",
            impacted_vms=["vm-1", "vm-2"],
            impacted_services=["svc-1"],
            total_impacted_count=3,
        )
        assert report.fault_type == "link-down"
        assert len(report.impacted_vms) == 2

    def test_empty_impact(self):
        report = ImpactReport(
            alarm_id="alarm-002",
            fault_device_id="device-002",
        )
        assert report.total_impacted_count == 0


class TestRemediationRecord:
    """Tests for RemediationRecord model."""

    def test_pending_remediation(self):
        record = RemediationRecord(
            alarm_id="alarm-001",
            action_type="bypass-path",
        )
        assert record.status == RemediationStatus.PENDING
        assert not record.success

    def test_successful_remediation(self):
        record = RemediationRecord(
            alarm_id="alarm-001",
            status=RemediationStatus.SUCCESS,
            success=True,
            duration_ms=4500.0,
        )
        assert record.success
        assert record.duration_ms == 4500.0


class TestSLAConstants:
    """Tests for SLA thresholds."""

    def test_sla_values(self):
        assert TroubleshootingCorrelator.DETECT_SLA == 60
        assert TroubleshootingCorrelator.LOCATE_SLA == 180
        assert TroubleshootingCorrelator.RECTIFY_SLA == 300

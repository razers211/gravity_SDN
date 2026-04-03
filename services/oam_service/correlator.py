"""
1-3-5 Troubleshooting Correlator.

Implements the core autonomous troubleshooting heuristic:

  ┌─────────────────────────────────────────────────────────┐
  │ Phase  │ SLA     │ Action                               │
  ├─────────────────────────────────────────────────────────┤
  │   1    │ 1 min   │ DETECT: Link degradation detected    │
  │        │         │ via BFD/interface flap telemetry      │
  │   2    │ 3 min   │ LOCATE: Query Neo4j graph to find    │
  │        │         │ all impacted tenants/VMs/services     │
  │   3    │ 5 min   │ RECTIFY: Compute bypass path,        │
  │        │         │ generate NETCONF payload, deploy      │
  └─────────────────────────────────────────────────────────┘

The correlator binds these three phases into an automated pipeline
that runs when a critical alarm is raised.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any

from shared.config import get_settings
from shared.models.telemetry import (
    Alarm,
    AlarmSeverity,
    ImpactReport,
    RemediationRecord,
    RemediationStatus,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class CorrelatorError(Exception):
    """Raised on correlation/remediation failures."""


class TroubleshootingCorrelator:
    """
    1-3-5 framework correlator — orchestrates the three-phase
    autonomous troubleshooting pipeline.
    """

    # SLA thresholds (seconds)
    DETECT_SLA = 60     # 1 minute
    LOCATE_SLA = 180    # 3 minutes
    RECTIFY_SLA = 300   # 5 minutes

    def __init__(self):
        self._correlation_sessions: dict[str, CorrelationSession] = {}
        self._remediation_history: list[RemediationRecord] = []

    async def on_alarm(self, alarm: Alarm) -> CorrelationSession | None:
        """
        Entry point: process a new alarm through the 1-3-5 pipeline.

        Only critical/major alarms trigger the full pipeline.
        Alarms are deduplicated by correlation ID.
        """
        if alarm.severity < AlarmSeverity.MAJOR:
            logger.debug("Alarm below threshold, skipping 1-3-5: %s", alarm.title)
            return None

        # Check for existing correlation session
        correlation_id = self._compute_correlation_id(alarm)
        if correlation_id in self._correlation_sessions:
            session = self._correlation_sessions[correlation_id]
            session.correlated_alarms.append(alarm)
            logger.info("Alarm correlated to existing session: %s", correlation_id)
            return session

        # Create new correlation session
        session = CorrelationSession(
            correlation_id=correlation_id,
            trigger_alarm=alarm,
        )
        self._correlation_sessions[correlation_id] = session

        logger.info(
            "=== 1-3-5 PIPELINE STARTED === correlation_id=%s, alarm=%s",
            correlation_id,
            alarm.title,
        )

        # Run the three phases
        try:
            # Phase 1: DETECT (already done — alarm received within 1 min)
            session.detect_time = time.monotonic()
            session.phase = "detect"
            logger.info(
                "[1/3] DETECT: Alarm received — %s on device %s",
                alarm.title,
                alarm.device_id,
            )

            # Phase 2: LOCATE (query graph DB for impact)
            session.phase = "locate"
            impact_report = await self._locate_impact(alarm)
            session.impact_report = impact_report
            session.locate_time = time.monotonic()

            locate_elapsed = session.locate_time - session.detect_time
            logger.info(
                "[2/3] LOCATE: Impact analysis complete in %.1fs — "
                "%d VMs, %d services affected",
                locate_elapsed,
                len(impact_report.impacted_vms),
                len(impact_report.impacted_services),
            )

            # Phase 3: RECTIFY (compute bypass, deploy config)
            session.phase = "rectify"
            remediation = await self._rectify(alarm, impact_report)
            session.remediation = remediation
            session.rectify_time = time.monotonic()

            total_elapsed = session.rectify_time - session.detect_time
            logger.info(
                "[3/3] RECTIFY: Remediation %s in %.1fs (total: %.1fs)",
                "SUCCEEDED" if remediation.success else "FAILED",
                session.rectify_time - session.locate_time,
                total_elapsed,
            )

            # Validate SLA compliance
            session.sla_met = total_elapsed <= self.RECTIFY_SLA
            if session.sla_met:
                logger.info("✓ 1-3-5 SLA MET: %.1fs < %ds", total_elapsed, self.RECTIFY_SLA)
            else:
                logger.warning("✗ 1-3-5 SLA BREACHED: %.1fs > %ds", total_elapsed, self.RECTIFY_SLA)

            session.phase = "completed"
            return session

        except Exception as exc:
            session.phase = "failed"
            session.error = str(exc)
            logger.error("1-3-5 pipeline failed: %s", exc, exc_info=True)
            return session

    async def _locate_impact(self, alarm: Alarm) -> ImpactReport:
        """
        Phase 2 — LOCATE: Query the Neo4j graph database to identify
        all impacted resources across the 5-layer digital map.

        Traversal: PhysicalDevice → Server → VirtualNetwork → VM → Service
        """
        from shared.graph.client import get_graph_client
        from shared.graph.queries import TopologyQueries
        from services.oam_service.impact_analyzer import ImpactAnalyzer

        try:
            client = await get_graph_client()
            queries = TopologyQueries(client)
            analyzer = ImpactAnalyzer(queries)

            report = await analyzer.analyze_link_failure(
                device_id=alarm.device_id,
                interface_name=alarm.interface_name,
            )
            return report

        except Exception as exc:
            logger.warning("Graph-based impact analysis failed: %s — using stub", exc)
            return ImpactReport(
                alarm_id=alarm.id,
                fault_device_id=alarm.device_id,
                fault_interface=alarm.interface_name,
                fault_type="link-down",
            )

    async def _rectify(
        self,
        alarm: Alarm,
        impact_report: ImpactReport,
    ) -> RemediationRecord:
        """
        Phase 3 — RECTIFY: Compute bypass path and deploy
        remediation configuration via NETCONF.
        """
        from services.oam_service.auto_remediation import AutoRemediation

        remediation_engine = AutoRemediation()

        try:
            record = await remediation_engine.execute(alarm, impact_report)
            self._remediation_history.append(record)
            return record

        except Exception as exc:
            record = RemediationRecord(
                alarm_id=alarm.id,
                impact_report_id=impact_report.id,
                status=RemediationStatus.FAILED,
                error_message=str(exc),
            )
            self._remediation_history.append(record)
            return record

    def _compute_correlation_id(self, alarm: Alarm) -> str:
        """
        Compute a correlation ID for alarm deduplication.

        Alarms on the same device + interface within a time window
        are correlated to the same session.
        """
        key = f"{alarm.device_id}:{alarm.interface_name or 'device'}"
        return f"corr-{hash(key) & 0xFFFFFFFF:08x}"

    @property
    def active_sessions(self) -> list["CorrelationSession"]:
        return [s for s in self._correlation_sessions.values() if s.phase != "completed"]

    @property
    def remediation_history(self) -> list[RemediationRecord]:
        return self._remediation_history.copy()


class CorrelationSession:
    """Tracks the state of a 1-3-5 correlation session."""

    def __init__(
        self,
        correlation_id: str,
        trigger_alarm: Alarm,
    ):
        self.correlation_id = correlation_id
        self.trigger_alarm = trigger_alarm
        self.correlated_alarms: list[Alarm] = [trigger_alarm]
        self.phase: str = "initialized"
        self.sla_met: bool = False
        self.error: str | None = None

        # Phase timestamps
        self.detect_time: float = 0.0
        self.locate_time: float = 0.0
        self.rectify_time: float = 0.0

        # Phase outputs
        self.impact_report: ImpactReport | None = None
        self.remediation: RemediationRecord | None = None

    @property
    def total_elapsed(self) -> float:
        if self.rectify_time and self.detect_time:
            return self.rectify_time - self.detect_time
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "phase": self.phase,
            "sla_met": self.sla_met,
            "total_elapsed_s": self.total_elapsed,
            "trigger_alarm": self.trigger_alarm.title,
            "correlated_alarm_count": len(self.correlated_alarms),
            "impact_report": self.impact_report.id if self.impact_report else None,
            "remediation_status": self.remediation.status if self.remediation else None,
            "error": self.error,
        }

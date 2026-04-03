"""
Telemetry Consumer.

Consumes and parses telemetry events from Kafka topics:
  - telemetry.yang-push  — YANG Push notifications (RFC 8639/8641)
  - telemetry.grpc       — gRPC streaming telemetry
  - telemetry.syslog     — Syslog messages

Converts raw telemetry into Metric and Alarm objects for the
correlation engine (1-3-5 framework).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from shared.config import get_settings
from shared.kafka.consumer import AsyncKafkaConsumer
from shared.models.telemetry import (
    Alarm,
    AlarmCategory,
    AlarmSeverity,
    Metric,
    TelemetryEvent,
    TelemetrySource,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class TelemetryConsumerService:
    """
    Kafka-based telemetry consumer for CloudEngine device events.

    Parses three types of telemetry:
      1. YANG Push — periodic/on-change datastore notifications
      2. gRPC — high-frequency streaming metrics
      3. Syslog — log-based events and traps
    """

    # Patterns for syslog-based alarm detection
    LINK_DOWN_PATTERN = re.compile(
        r"(?i)(interface|link)\s+(\S+)\s+.*(down|failed|degraded)"
    )
    BFD_DOWN_PATTERN = re.compile(
        r"(?i)bfd\s+session\s+(\S+)\s+.*(down|timeout)"
    )
    BGP_PEER_DOWN_PATTERN = re.compile(
        r"(?i)bgp\s+peer\s+(\S+)\s+.*(down|reset|notification)"
    )

    def __init__(self, alarm_callback: Any = None):
        """
        Args:
            alarm_callback: Async function called when a new alarm is raised.
                           Signature: async def callback(alarm: Alarm) -> None
        """
        self._consumer: AsyncKafkaConsumer | None = None
        self._alarm_callback = alarm_callback
        self._metrics_buffer: list[Metric] = []
        self._alarms_raised: list[Alarm] = []

    def initialize(self) -> None:
        """Initialize the Kafka consumer and register topic handlers."""
        topics = [
            settings.kafka_telemetry_topic,
            settings.kafka_grpc_topic,
            settings.kafka_syslog_topic,
        ]
        self._consumer = AsyncKafkaConsumer(
            topics=topics,
            group_id=f"{settings.service_name}-telemetry",
        )
        self._consumer.connect()

        # Register per-topic handlers
        self._consumer.register_handler(
            settings.kafka_telemetry_topic, self._handle_yang_push
        )
        self._consumer.register_handler(
            settings.kafka_grpc_topic, self._handle_grpc
        )
        self._consumer.register_handler(
            settings.kafka_syslog_topic, self._handle_syslog
        )

    async def start(self) -> None:
        """Start consuming telemetry events."""
        if not self._consumer:
            self.initialize()
        await self._consumer.start()

    def stop(self) -> None:
        """Stop the consumer."""
        if self._consumer:
            self._consumer.stop()

    # ── YANG Push Handler ────────────────────────────────────────────────

    async def _handle_yang_push(self, payload: dict[str, Any], topic: str) -> None:
        """
        Parse YANG Push notifications (RFC 8639/8641).

        Notification types:
          - push-update: periodic state snapshot
          - push-change-update: on-change notification (triggers alarms)
        """
        notification_type = payload.get("notification_type", "push-update")
        device_id = payload.get("device_id", "")
        xpath = payload.get("xpath", "")
        data = payload.get("parsed_data", payload.get("data", {}))

        logger.debug(
            "YANG Push: type=%s, device=%s, xpath=%s",
            notification_type,
            device_id,
            xpath,
        )

        # Extract metrics
        metrics = self._extract_metrics(device_id, xpath, data)
        self._metrics_buffer.extend(metrics)

        # Detect alarms from on-change notifications
        if notification_type == "push-change-update":
            alarms = self._detect_alarms_from_yang(device_id, xpath, data)
            for alarm in alarms:
                await self._raise_alarm(alarm)

    # ── gRPC Handler ─────────────────────────────────────────────────────

    async def _handle_grpc(self, payload: dict[str, Any], topic: str) -> None:
        """Parse gRPC streaming telemetry messages."""
        device_id = payload.get("device_id", "")
        sensor_path = payload.get("sensor_path", "")
        data_points = payload.get("data_points", [])

        for point in data_points:
            metric = Metric(
                device_id=device_id,
                metric_path=sensor_path,
                value=float(point.get("value", 0)),
                unit=point.get("unit", ""),
                timestamp=datetime.fromisoformat(point["timestamp"])
                if "timestamp" in point
                else datetime.utcnow(),
                source=TelemetrySource.GRPC,
            )
            self._metrics_buffer.append(metric)

    # ── Syslog Handler ───────────────────────────────────────────────────

    async def _handle_syslog(self, payload: dict[str, Any], topic: str) -> None:
        """Parse syslog messages and detect network events."""
        device_id = payload.get("device_id", "")
        message = payload.get("message", "")
        severity = payload.get("severity", "info")

        # Pattern matching for alarm generation
        alarm = self._parse_syslog_for_alarms(device_id, message, severity)
        if alarm:
            await self._raise_alarm(alarm)

    # ── Metric Extraction ────────────────────────────────────────────────

    def _extract_metrics(
        self,
        device_id: str,
        xpath: str,
        data: dict[str, Any],
    ) -> list[Metric]:
        """Extract metric data points from YANG Push notification data."""
        metrics: list[Metric] = []

        # Interface statistics
        if "ifm" in xpath or "interface" in xpath:
            interfaces = data.get("interfaces", {}).get("interface", [])
            if isinstance(interfaces, dict):
                interfaces = [interfaces]

            for iface in interfaces:
                stats = iface.get("statistics", {})
                iface_name = iface.get("if-name", "")

                for stat_key in ["in-octets", "out-octets", "in-errors", "out-errors",
                                 "in-discards", "out-discards", "in-unicast-pkts"]:
                    if stat_key in stats:
                        metrics.append(Metric(
                            device_id=device_id,
                            interface_name=iface_name,
                            metric_path=f"huawei-ifm:ifm/interfaces/interface/statistics/{stat_key}",
                            value=float(stats[stat_key]),
                            unit="bytes" if "octets" in stat_key else "packets",
                            source=TelemetrySource.YANG_PUSH,
                        ))

        return metrics

    # ── Alarm Detection ──────────────────────────────────────────────────

    def _detect_alarms_from_yang(
        self,
        device_id: str,
        xpath: str,
        data: dict[str, Any],
    ) -> list[Alarm]:
        """Detect alarms from YANG Push on-change notifications."""
        alarms: list[Alarm] = []

        # Interface status change
        if "ifm" in xpath:
            interfaces = data.get("interfaces", {}).get("interface", [])
            if isinstance(interfaces, dict):
                interfaces = [interfaces]

            for iface in interfaces:
                oper_status = iface.get("oper-status", "").lower()
                if_name = iface.get("if-name", "")

                if oper_status == "down":
                    alarms.append(Alarm(
                        device_id=device_id,
                        severity=AlarmSeverity.MAJOR,
                        category=AlarmCategory.LINK,
                        source=TelemetrySource.YANG_PUSH,
                        title=f"Interface {if_name} Link Down",
                        message=f"Interface {if_name} on device {device_id} is operationally DOWN",
                        interface_name=if_name,
                        affected_resource=f"huawei-ifm:ifm/interfaces/interface[if-name='{if_name}']",
                    ))

        return alarms

    def _parse_syslog_for_alarms(
        self,
        device_id: str,
        message: str,
        severity: str,
    ) -> Alarm | None:
        """Parse syslog message for alarm-worthy events."""
        # Link down detection
        match = self.LINK_DOWN_PATTERN.search(message)
        if match:
            interface_name = match.group(2)
            return Alarm(
                device_id=device_id,
                severity=AlarmSeverity.MAJOR,
                category=AlarmCategory.LINK,
                source=TelemetrySource.SYSLOG,
                title=f"Interface {interface_name} Link Down",
                message=message,
                interface_name=interface_name,
            )

        # BFD session down
        match = self.BFD_DOWN_PATTERN.search(message)
        if match:
            return Alarm(
                device_id=device_id,
                severity=AlarmSeverity.CRITICAL,
                category=AlarmCategory.LINK,
                source=TelemetrySource.BFD,
                title=f"BFD Session Down: {match.group(1)}",
                message=message,
            )

        # BGP peer down
        match = self.BGP_PEER_DOWN_PATTERN.search(message)
        if match:
            return Alarm(
                device_id=device_id,
                severity=AlarmSeverity.MAJOR,
                category=AlarmCategory.BGP,
                source=TelemetrySource.SYSLOG,
                title=f"BGP Peer Down: {match.group(1)}",
                message=message,
            )

        return None

    async def _raise_alarm(self, alarm: Alarm) -> None:
        """Raise an alarm and notify the correlation engine."""
        self._alarms_raised.append(alarm)
        logger.warning(
            "ALARM RAISED: [%s] %s on device %s",
            alarm.severity.name,
            alarm.title,
            alarm.device_id,
        )

        if self._alarm_callback:
            await self._alarm_callback(alarm)

    @property
    def metrics_buffer(self) -> list[Metric]:
        return self._metrics_buffer.copy()

    @property
    def active_alarms(self) -> list[Alarm]:
        return [a for a in self._alarms_raised if a.is_active]

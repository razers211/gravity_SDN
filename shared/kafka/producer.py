"""
Kafka Producer — Async wrapper for publishing events to Apache Kafka.

Used by all services for:
  - Telemetry event ingestion (gRPC → Kafka)
  - Provisioning audit trail
  - Alarm notifications
  - Inter-service event-driven communication
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from confluent_kafka import Producer, KafkaError, KafkaException

from shared.config import Settings, get_settings

logger = logging.getLogger(__name__)


class KafkaProducerError(Exception):
    """Raised on Kafka producer failures."""


class AsyncKafkaProducer:
    """
    Async-compatible Kafka producer.

    Wraps confluent_kafka.Producer with JSON serialization,
    delivery callbacks, and graceful shutdown.

    Usage:
        producer = AsyncKafkaProducer()
        await producer.send("telemetry.yang-push", {
            "device_id": "...",
            "metric_path": "...",
            "value": 42.0,
        })
        producer.flush()
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._producer: Producer | None = None
        self._delivery_count = 0
        self._error_count = 0

    def connect(self) -> None:
        """Initialize the Kafka producer."""
        config = {
            "bootstrap.servers": self.settings.kafka_bootstrap_servers,
            "client.id": f"{self.settings.service_name}-producer",
            "acks": "all",
            "retries": 3,
            "retry.backoff.ms": 500,
            "linger.ms": 10,
            "batch.size": 65536,
            "compression.type": "lz4",
            "enable.idempotence": True,
        }
        self._producer = Producer(config)
        logger.info(
            "Kafka producer initialized: %s",
            self.settings.kafka_bootstrap_servers,
        )

    def _delivery_callback(self, err: KafkaError | None, msg: Any) -> None:
        """Callback invoked on message delivery or failure."""
        if err:
            self._error_count += 1
            logger.error(
                "Kafka delivery failed: topic=%s, error=%s",
                msg.topic() if msg else "unknown",
                err,
            )
        else:
            self._delivery_count += 1
            logger.debug(
                "Kafka message delivered: topic=%s, partition=%s, offset=%s",
                msg.topic(),
                msg.partition(),
                msg.offset(),
            )

    def send(
        self,
        topic: str,
        value: dict[str, Any],
        key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """
        Publish a JSON message to a Kafka topic.

        Args:
            topic: Kafka topic name
            value: Message payload (will be JSON-serialized)
            key: Optional partition key
            headers: Optional message headers
        """
        if not self._producer:
            raise KafkaProducerError("Producer not initialized — call connect() first")

        # Add metadata
        enriched_value = {
            **value,
            "_event_id": str(uuid4()),
            "_timestamp": datetime.utcnow().isoformat(),
            "_source_service": self.settings.service_name,
        }

        serialized = json.dumps(enriched_value, default=str).encode("utf-8")
        kwargs: dict[str, Any] = {
            "topic": topic,
            "value": serialized,
            "callback": self._delivery_callback,
        }

        if key:
            kwargs["key"] = key.encode("utf-8")

        if headers:
            kwargs["headers"] = [(k, v.encode("utf-8")) for k, v in headers.items()]

        try:
            self._producer.produce(**kwargs)
            self._producer.poll(0)  # Trigger delivery callbacks
        except KafkaException as exc:
            raise KafkaProducerError(f"Failed to produce to {topic}: {exc}") from exc

    def send_alarm(self, alarm_data: dict[str, Any]) -> None:
        """Publish an alarm event to the alarms topic."""
        self.send(
            topic=self.settings.kafka_alarm_topic,
            value=alarm_data,
            key=alarm_data.get("device_id"),
        )

    def send_audit(self, audit_data: dict[str, Any]) -> None:
        """Publish a provisioning audit event."""
        self.send(
            topic=self.settings.kafka_audit_topic,
            value=audit_data,
            key=audit_data.get("transaction_id"),
        )

    def send_telemetry(self, telemetry_data: dict[str, Any], source: str = "yang-push") -> None:
        """Publish a telemetry event to the appropriate topic."""
        topic_map = {
            "yang-push": self.settings.kafka_telemetry_topic,
            "grpc": self.settings.kafka_grpc_topic,
            "syslog": self.settings.kafka_syslog_topic,
        }
        topic = topic_map.get(source, self.settings.kafka_telemetry_topic)
        self.send(
            topic=topic,
            value=telemetry_data,
            key=telemetry_data.get("device_id"),
        )

    def flush(self, timeout: float = 10.0) -> int:
        """Flush all pending messages. Returns number of messages still in queue."""
        if self._producer:
            remaining = self._producer.flush(timeout)
            if remaining > 0:
                logger.warning("%d messages still in queue after flush", remaining)
            return remaining
        return 0

    def close(self) -> None:
        """Flush and close the producer."""
        if self._producer:
            self.flush()
            logger.info(
                "Kafka producer closed: delivered=%d, errors=%d",
                self._delivery_count,
                self._error_count,
            )
            self._producer = None

    @property
    def stats(self) -> dict[str, int]:
        return {
            "delivered": self._delivery_count,
            "errors": self._error_count,
        }

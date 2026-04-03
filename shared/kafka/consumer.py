"""
Kafka Consumer — Async wrapper for consuming events from Apache Kafka.

Used primarily by:
  - O&M Service: telemetry event consumption and alarm processing
  - Provisioning Engine: audit event tracking
  - Resource Manager: allocation event processing
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Awaitable

from confluent_kafka import Consumer, KafkaError, KafkaException, TopicPartition

from shared.config import Settings, get_settings

logger = logging.getLogger(__name__)


class KafkaConsumerError(Exception):
    """Raised on Kafka consumer failures."""


MessageHandler = Callable[[dict[str, Any], str], Awaitable[None]]


class AsyncKafkaConsumer:
    """
    Async-compatible Kafka consumer with message handler registration.

    Supports multi-topic subscription with per-topic handler routing
    and graceful shutdown.

    Usage:
        consumer = AsyncKafkaConsumer(topics=["telemetry.yang-push"])
        consumer.register_handler("telemetry.yang-push", handle_telemetry)
        await consumer.start()   # Blocks, consuming messages
        consumer.stop()
    """

    def __init__(
        self,
        topics: list[str],
        group_id: str | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        self.topics = topics
        self.group_id = group_id or self.settings.kafka_group_id
        self._consumer: Consumer | None = None
        self._running = False
        self._handlers: dict[str, MessageHandler] = {}
        self._messages_processed = 0
        self._errors = 0

    def connect(self) -> None:
        """Initialize the Kafka consumer and subscribe to topics."""
        config = {
            "bootstrap.servers": self.settings.kafka_bootstrap_servers,
            "group.id": self.group_id,
            "client.id": f"{self.settings.service_name}-consumer",
            "auto.offset.reset": self.settings.kafka_auto_offset_reset,
            "enable.auto.commit": True,
            "auto.commit.interval.ms": 5000,
            "session.timeout.ms": 30000,
            "max.poll.interval.ms": 300000,
        }
        self._consumer = Consumer(config)
        self._consumer.subscribe(self.topics)
        logger.info(
            "Kafka consumer subscribed: topics=%s, group=%s",
            self.topics,
            self.group_id,
        )

    def register_handler(self, topic: str, handler: MessageHandler) -> None:
        """Register an async message handler for a specific topic."""
        self._handlers[topic] = handler
        logger.debug("Handler registered for topic: %s", topic)

    async def start(self, poll_timeout: float = 1.0) -> None:
        """
        Start consuming messages in an async loop.

        Runs indefinitely until stop() is called. For each message:
          1. Deserialize JSON payload
          2. Route to the appropriate topic handler
          3. Handle/log any processing errors
        """
        if not self._consumer:
            raise KafkaConsumerError("Consumer not initialized — call connect() first")

        self._running = True
        logger.info("Kafka consumer started — polling topics: %s", self.topics)

        loop = asyncio.get_event_loop()

        while self._running:
            try:
                # Poll in a thread to avoid blocking the event loop
                msg = await loop.run_in_executor(
                    None,
                    lambda: self._consumer.poll(poll_timeout),
                )

                if msg is None:
                    continue

                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        logger.debug(
                            "Reached end of partition: %s[%d]@%d",
                            msg.topic(),
                            msg.partition(),
                            msg.offset(),
                        )
                        continue
                    logger.error("Kafka consumer error: %s", msg.error())
                    self._errors += 1
                    continue

                # Deserialize
                topic = msg.topic()
                try:
                    payload = json.loads(msg.value().decode("utf-8"))
                except json.JSONDecodeError as exc:
                    logger.error("Failed to deserialize message from %s: %s", topic, exc)
                    self._errors += 1
                    continue

                # Route to handler
                handler = self._handlers.get(topic)
                if handler:
                    try:
                        await handler(payload, topic)
                        self._messages_processed += 1
                    except Exception as exc:
                        logger.error(
                            "Handler error for topic %s: %s",
                            topic,
                            exc,
                            exc_info=True,
                        )
                        self._errors += 1
                else:
                    logger.warning("No handler registered for topic: %s", topic)

            except KafkaException as exc:
                logger.error("Kafka exception during poll: %s", exc)
                self._errors += 1
                await asyncio.sleep(1.0)

    def stop(self) -> None:
        """Signal the consumer loop to stop."""
        self._running = False
        logger.info(
            "Kafka consumer stopping: processed=%d, errors=%d",
            self._messages_processed,
            self._errors,
        )

    def close(self) -> None:
        """Close the consumer and release resources."""
        self.stop()
        if self._consumer:
            self._consumer.close()
            self._consumer = None
            logger.info("Kafka consumer closed")

    @property
    def stats(self) -> dict[str, int]:
        return {
            "messages_processed": self._messages_processed,
            "errors": self._errors,
        }

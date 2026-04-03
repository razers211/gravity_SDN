"""
Multi-Layer Health Evaluation Engine.

Computes health scores across the 5-layer digital map using
weighted metrics from telemetry, alarm state, and resource utilization.

Health Dimensions:
  - Device Health: CPU, memory, temperature, fan status
  - Link Health: utilization, error rate, CRC errors, flaps
  - Service Health: SLA compliance, packet loss, latency
  - Tenant Health: aggregate of all VPC/subnet health
  - Fabric Health: overall weighted score across all layers
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class HealthScore(BaseModel):
    """Health score for a single entity."""
    entity_id: str
    entity_type: str = Field(examples=["device", "link", "service", "tenant", "fabric"])
    entity_name: str = ""
    score: float = Field(ge=0.0, le=100.0, default=100.0)
    status: str = Field(default="healthy", examples=["healthy", "degraded", "critical", "unknown"])
    dimensions: dict[str, float] = Field(default_factory=dict)
    risk_factors: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)

    @property
    def status_from_score(self) -> str:
        if self.score >= 90:
            return "healthy"
        elif self.score >= 70:
            return "degraded"
        elif self.score >= 50:
            return "warning"
        return "critical"


class HealthReport(BaseModel):
    """Comprehensive network health report."""
    overall_score: float = Field(ge=0.0, le=100.0, default=100.0)
    overall_status: str = "healthy"
    device_health: list[HealthScore] = Field(default_factory=list)
    link_health: list[HealthScore] = Field(default_factory=list)
    service_health: list[HealthScore] = Field(default_factory=list)
    tenant_health: list[HealthScore] = Field(default_factory=list)
    fabric_score: float = 100.0
    total_devices: int = 0
    healthy_devices: int = 0
    degraded_devices: int = 0
    critical_devices: int = 0
    active_alarms: int = 0
    evaluation_time_ms: float = 0.0


class HealthEvaluator:
    """
    Multi-layer network health evaluation engine.

    Weights:
      - Device layer: 30%
      - Link layer: 25%
      - Service layer: 25%
      - Tenant layer: 20%
    """

    DEVICE_WEIGHT = 0.30
    LINK_WEIGHT = 0.25
    SERVICE_WEIGHT = 0.25
    TENANT_WEIGHT = 0.20

    # Thresholds
    CPU_WARNING = 70.0
    CPU_CRITICAL = 90.0
    MEMORY_WARNING = 75.0
    MEMORY_CRITICAL = 90.0
    LINK_UTIL_WARNING = 70.0
    LINK_UTIL_CRITICAL = 90.0
    TEMP_WARNING = 65.0
    TEMP_CRITICAL = 75.0

    def __init__(self, graph_client=None):
        self._graph = graph_client

    async def evaluate(self) -> HealthReport:
        """Run full health evaluation across all layers."""
        start = time.monotonic()

        report = HealthReport()

        if self._graph:
            report.device_health = await self._evaluate_devices()
            report.link_health = await self._evaluate_links()
            report.service_health = await self._evaluate_services()
            report.tenant_health = await self._evaluate_tenants()

            # Compute aggregate scores
            device_avg = self._average_scores(report.device_health)
            link_avg = self._average_scores(report.link_health)
            service_avg = self._average_scores(report.service_health)
            tenant_avg = self._average_scores(report.tenant_health)

            report.fabric_score = (
                device_avg * self.DEVICE_WEIGHT
                + link_avg * self.LINK_WEIGHT
                + service_avg * self.SERVICE_WEIGHT
                + tenant_avg * self.TENANT_WEIGHT
            )
            report.overall_score = report.fabric_score

            # Counters
            report.total_devices = len(report.device_health)
            report.healthy_devices = sum(1 for d in report.device_health if d.score >= 90)
            report.degraded_devices = sum(1 for d in report.device_health if 50 <= d.score < 90)
            report.critical_devices = sum(1 for d in report.device_health if d.score < 50)

        if report.overall_score >= 90:
            report.overall_status = "healthy"
        elif report.overall_score >= 70:
            report.overall_status = "degraded"
        else:
            report.overall_status = "critical"

        report.evaluation_time_ms = (time.monotonic() - start) * 1000
        return report

    def evaluate_device_metrics(
        self,
        cpu_util: float = 0.0,
        memory_util: float = 0.0,
        temperature: float = 25.0,
        active_alarms: int = 0,
        interface_down_count: int = 0,
    ) -> HealthScore:
        """Evaluate a single device's health from its metrics."""
        score = 100.0
        risks = []
        recommendations = []
        dimensions = {}

        # CPU
        cpu_score = max(0, 100 - cpu_util)
        dimensions["cpu"] = cpu_score
        if cpu_util > self.CPU_CRITICAL:
            score -= 30
            risks.append(f"CPU critically high: {cpu_util:.1f}%")
            recommendations.append("Investigate high CPU processes, consider load redistribution")
        elif cpu_util > self.CPU_WARNING:
            score -= 15
            risks.append(f"CPU elevated: {cpu_util:.1f}%")

        # Memory
        mem_score = max(0, 100 - memory_util)
        dimensions["memory"] = mem_score
        if memory_util > self.MEMORY_CRITICAL:
            score -= 25
            risks.append(f"Memory critically high: {memory_util:.1f}%")
            recommendations.append("Check for memory leaks, optimize table sizes")
        elif memory_util > self.MEMORY_WARNING:
            score -= 10
            risks.append(f"Memory elevated: {memory_util:.1f}%")

        # Temperature
        temp_score = max(0, 100 - (temperature - 25))
        dimensions["temperature"] = min(100, temp_score)
        if temperature > self.TEMP_CRITICAL:
            score -= 20
            risks.append(f"Temperature critical: {temperature:.1f}°C")
            recommendations.append("Check fan status and airflow, consider maintenance window")
        elif temperature > self.TEMP_WARNING:
            score -= 10
            risks.append(f"Temperature elevated: {temperature:.1f}°C")

        # Alarms
        alarm_penalty = min(30, active_alarms * 5)
        score -= alarm_penalty
        dimensions["alarms"] = max(0, 100 - alarm_penalty * 3)
        if active_alarms > 0:
            risks.append(f"{active_alarms} active alarm(s)")

        # Interface downs
        if interface_down_count > 0:
            iface_penalty = min(20, interface_down_count * 5)
            score -= iface_penalty
            risks.append(f"{interface_down_count} interface(s) down")
            dimensions["interfaces"] = max(0, 100 - iface_penalty * 5)

        return HealthScore(
            entity_id="",
            entity_type="device",
            score=max(0, min(100, score)),
            status="healthy" if score >= 90 else ("degraded" if score >= 70 else "critical"),
            dimensions=dimensions,
            risk_factors=risks,
            recommendations=recommendations,
        )

    async def _evaluate_devices(self) -> list[HealthScore]:
        """Evaluate health of all physical devices via graph."""
        query = """
        MATCH (d:PhysicalDevice)
        OPTIONAL MATCH (d)<-[:ON_DEVICE]-(a:Alarm {cleared: false})
        RETURN d.device_id AS id, d.hostname AS name,
               d.cpu_util AS cpu, d.memory_util AS memory,
               d.temperature AS temp, count(a) AS alarms
        """
        scores = []
        async with self._graph.session() as session:
            result = await session.run(query)
            async for record in result:
                hs = self.evaluate_device_metrics(
                    cpu_util=record["cpu"] or 0,
                    memory_util=record["memory"] or 0,
                    temperature=record["temp"] or 25,
                    active_alarms=record["alarms"],
                )
                hs.entity_id = record["id"]
                hs.entity_name = record["name"]
                scores.append(hs)
        return scores

    async def _evaluate_links(self) -> list[HealthScore]:
        """Evaluate health of all physical links."""
        query = """
        MATCH (i:Interface)-[:CONNECTED_TO]->(j:Interface)
        RETURN i.name AS src, j.name AS dst,
               i.utilization AS util, i.error_rate AS errors,
               i.status AS status
        """
        scores = []
        async with self._graph.session() as session:
            result = await session.run(query)
            async for record in result:
                score = 100.0
                util = record["util"] or 0
                if util > self.LINK_UTIL_CRITICAL:
                    score -= 30
                elif util > self.LINK_UTIL_WARNING:
                    score -= 15
                if record["status"] == "down":
                    score = 0

                scores.append(HealthScore(
                    entity_id=f"{record['src']}-{record['dst']}",
                    entity_type="link",
                    entity_name=f"{record['src']} → {record['dst']}",
                    score=max(0, score),
                ))
        return scores

    async def _evaluate_services(self) -> list[HealthScore]:
        """Evaluate health of all services."""
        query = """
        MATCH (s:Service)
        OPTIONAL MATCH (s)-[:DEPLOYED_ON]->(vm:VM)-[:RUNS_ON]->(sv:Server)
                        -[:CONNECTED_TO_SWITCH]->(d:PhysicalDevice)
        RETURN s.name AS name, s.service_id AS id,
               collect(d.status) AS device_statuses
        """
        scores = []
        async with self._graph.session() as session:
            result = await session.run(query)
            async for record in result:
                statuses = record["device_statuses"] or []
                down = sum(1 for s in statuses if s == "offline")
                score = 100.0 - (down / max(1, len(statuses))) * 100
                scores.append(HealthScore(
                    entity_id=record["id"] or "",
                    entity_type="service",
                    entity_name=record["name"] or "",
                    score=max(0, score),
                ))
        return scores

    async def _evaluate_tenants(self) -> list[HealthScore]:
        """Evaluate per-tenant health."""
        query = """
        MATCH (t:Tenant)-[:OWNS]->(vn:VirtualNetwork)-[:HOSTED_ON]->(d:PhysicalDevice)
        RETURN t.name AS name, t.tenant_id AS id,
               collect(d.status) AS statuses
        """
        scores = []
        async with self._graph.session() as session:
            result = await session.run(query)
            async for record in result:
                statuses = record["statuses"] or []
                down = sum(1 for s in statuses if s in ("offline", "degraded"))
                score = 100.0 - (down / max(1, len(statuses))) * 50
                scores.append(HealthScore(
                    entity_id=record["id"] or "",
                    entity_type="tenant",
                    entity_name=record["name"] or "",
                    score=max(0, score),
                ))
        return scores

    @staticmethod
    def _average_scores(scores: list[HealthScore]) -> float:
        if not scores:
            return 100.0
        return sum(s.score for s in scores) / len(scores)

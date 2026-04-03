"""
Graph-based Impact Analyzer.

Given a network fault (link down, device failure), traverses the
5-layer digital map in Neo4j to identify ALL impacted resources:
  Layer 1: PhysicalDevice → directly connected devices
  Layer 2: Server → compute nodes behind the fault
  Layer 3: VirtualNetwork → BDs, VRFs, VNIs affected
  Layer 4: VM → virtual machines losing connectivity
  Layer 5: Service → tenant applications impacted
"""

from __future__ import annotations

import logging
import time
from typing import Any

from shared.graph.queries import TopologyQueries
from shared.models.telemetry import AlarmSeverity, ImpactReport

logger = logging.getLogger(__name__)


class ImpactAnalyzer:
    """
    Performs graph-based impact analysis using Neo4j Cypher queries
    against the 5-layer Network Digital Map.
    """

    def __init__(self, topology_queries: TopologyQueries):
        self.queries = topology_queries

    async def analyze_link_failure(
        self,
        device_id: str,
        interface_name: str | None = None,
    ) -> ImpactReport:
        """
        Analyze the impact of a link failure on the entire service chain.

        If interface_name is provided, queries for specific link failure.
        Otherwise, queries for full device failure impact.
        """
        start_time = time.monotonic()

        if interface_name:
            impact_data = await self.queries.get_impacted_by_link_failure(
                device_id=device_id,
                interface_name=interface_name,
            )
        else:
            impact_data = await self.queries.get_impacted_by_device_failure(
                device_id=device_id,
            )

        duration_ms = (time.monotonic() - start_time) * 1000

        # Build impact report
        impacted_devices = impact_data.get("impacted_devices", [])
        impacted_servers = impact_data.get("impacted_servers", [])
        impacted_vns = impact_data.get("impacted_virtual_networks", [])
        impacted_vms = impact_data.get("impacted_vms", [])
        impacted_services = impact_data.get("impacted_services", [])

        total_impacted = (
            len(impacted_devices)
            + len(impacted_servers)
            + len(impacted_vns)
            + len(impacted_vms)
            + len(impacted_services)
        )

        # Compute severity based on impact scope
        max_severity = self._compute_severity(
            vm_count=len(impacted_vms),
            service_count=len(impacted_services),
        )

        report = ImpactReport(
            alarm_id="",  # Set by caller
            fault_device_id=device_id,
            fault_interface=interface_name,
            fault_type="link-down" if interface_name else "device-unreachable",
            analysis_duration_ms=duration_ms,
            impacted_physical_devices=[d.get("id", "") for d in impacted_devices if isinstance(d, dict)],
            impacted_servers=[s.get("id", "") for s in impacted_servers if isinstance(s, dict)],
            impacted_virtual_networks=[v.get("id", "") for v in impacted_vns if isinstance(v, dict)],
            impacted_vms=[v.get("id", "") for v in impacted_vms if isinstance(v, dict)],
            impacted_services=[s.get("id", "") for s in impacted_services if isinstance(s, dict)],
            total_impacted_count=total_impacted,
            max_severity=max_severity,
            recommended_action=self._recommend_action(total_impacted, max_severity),
        )

        logger.info(
            "Impact analysis: device=%s, interface=%s → "
            "%d devices, %d servers, %d VNs, %d VMs, %d services (%.1fms)",
            device_id,
            interface_name,
            len(impacted_devices),
            len(impacted_servers),
            len(impacted_vns),
            len(impacted_vms),
            len(impacted_services),
            duration_ms,
        )

        return report

    def _compute_severity(self, vm_count: int, service_count: int) -> AlarmSeverity:
        """Compute overall severity based on impact scope."""
        if service_count > 10 or vm_count > 100:
            return AlarmSeverity.CRITICAL
        elif service_count > 5 or vm_count > 50:
            return AlarmSeverity.MAJOR
        elif service_count > 0 or vm_count > 10:
            return AlarmSeverity.MINOR
        elif vm_count > 0:
            return AlarmSeverity.WARNING
        return AlarmSeverity.INDETERMINATE

    def _recommend_action(
        self,
        total_impacted: int,
        severity: AlarmSeverity,
    ) -> str:
        """Generate a recommended remediation action based on impact severity."""
        if severity >= AlarmSeverity.CRITICAL:
            return "IMMEDIATE: Deploy bypass path via ECMP rehash and notify NOC"
        elif severity >= AlarmSeverity.MAJOR:
            return "HIGH: Configure alternate path and schedule maintenance window"
        elif severity >= AlarmSeverity.MINOR:
            return "MEDIUM: Monitor and prepare fallback configuration"
        return "LOW: Log event and continue monitoring"

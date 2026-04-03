"""
Autonomous Remediation Engine.

Generates and deploys bypass path configurations when the 1-3-5
correlator identifies a network fault requiring autonomous rectification.

Remediation strategies:
  1. ECMP Rehash — adjust link weights to shift traffic
  2. Explicit Bypass — configure static route or policy-based forwarding
  3. VXLAN Re-convergence — trigger BGP EVPN route withdrawal and re-advertisement
"""

from __future__ import annotations

import logging
import time
from typing import Any

from shared.config import get_settings
from shared.models.telemetry import (
    Alarm,
    ImpactReport,
    RemediationRecord,
    RemediationStatus,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class AutoRemediation:
    """
    Autonomous remediation engine for the 1-3-5 framework.

    When invoked by the correlator, this engine:
      1. Queries the graph DB for alternate paths
      2. Generates NETCONF bypass configuration payloads
      3. Deploys configuration via the Provisioning Engine
      4. Returns an audit record of the remediation action
    """

    async def execute(
        self,
        alarm: Alarm,
        impact_report: ImpactReport,
    ) -> RemediationRecord:
        """
        Execute autonomous remediation for a detected fault.

        Returns:
            RemediationRecord with full audit trail
        """
        start_time = time.monotonic()

        record = RemediationRecord(
            alarm_id=alarm.id,
            impact_report_id=impact_report.id,
            status=RemediationStatus.IN_PROGRESS,
            target_devices=[impact_report.fault_device_id],
        )

        try:
            # Step 1: Find alternate paths
            alternate_paths = await self._find_bypass_paths(
                device_id=impact_report.fault_device_id,
                interface=impact_report.fault_interface,
            )

            if not alternate_paths:
                record.status = RemediationStatus.SKIPPED
                record.description = "No alternate paths available — manual intervention required"
                record.completed_at = _now()
                record.duration_ms = (time.monotonic() - start_time) * 1000
                logger.warning("No bypass paths found — remediation skipped")
                return record

            # Step 2: Generate bypass configuration
            bypass_payloads = self._generate_bypass_config(
                alarm=alarm,
                paths=alternate_paths,
            )
            record.netconf_payloads = bypass_payloads

            # Step 3: Deploy via Provisioning Engine
            deployment_result = await self._deploy_bypass(bypass_payloads)

            if deployment_result.get("success"):
                record.status = RemediationStatus.SUCCESS
                record.success = True
                record.description = (
                    f"Bypass path deployed: {len(bypass_payloads)} payloads "
                    f"across {len(record.target_devices)} devices"
                )
                record.action_type = "bypass-path"
            else:
                record.status = RemediationStatus.FAILED
                record.error_message = deployment_result.get("error", "Unknown deployment failure")
                record.rollback_performed = True

        except Exception as exc:
            record.status = RemediationStatus.FAILED
            record.error_message = str(exc)
            logger.error("Remediation failed: %s", exc, exc_info=True)

        record.completed_at = _now()
        record.duration_ms = (time.monotonic() - start_time) * 1000

        logger.info(
            "Remediation %s: status=%s, duration=%.1fms",
            record.id,
            record.status,
            record.duration_ms,
        )
        return record

    async def _find_bypass_paths(
        self,
        device_id: str,
        interface: str | None,
    ) -> list[dict[str, Any]]:
        """
        Query the graph database for alternate paths around the fault.

        Uses ECMP-aware path computation considering:
          - Existing link utilisation
          - Available bandwidth on alternate paths
          - Hop count preference
        """
        try:
            from shared.graph.client import get_graph_client
            from shared.graph.queries import TopologyQueries

            client = await get_graph_client()
            queries = TopologyQueries(client)

            # Update the failed link status in the graph
            if interface:
                await queries.update_link_status(device_id, interface, "down")

            # Find alternate paths (simplified — would use weighted shortest path)
            # In production, this would compute ECMP groups excluding the failed link
            return [
                {
                    "type": "ecmp-rehash",
                    "description": "ECMP rehash: redistribute traffic across remaining uplinks",
                    "cost_delta": 0,
                }
            ]

        except Exception as exc:
            logger.warning("Bypass path computation failed: %s", exc)
            return []

    def _generate_bypass_config(
        self,
        alarm: Alarm,
        paths: list[dict[str, Any]],
    ) -> list[str]:
        """
        Generate NETCONF XML payloads for bypass path configuration.

        Strategies:
          - ECMP rehash: adjust OSPF/IS-IS costs on remaining links
          - Explicit bypass: add static route through alternate path
          - BGP re-convergence: withdraw routes from failed link, re-advertise via alternate
        """
        payloads: list[str] = []

        for path in paths:
            if path["type"] == "ecmp-rehash":
                # Adjust OSPF cost on failed interface to max (divert traffic)
                payload = f"""
                <config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
                  <ospf xmlns="urn:huawei:params:xml:ns:yang:huawei-ospf">
                    <ospf-instances>
                      <ospf-instance>
                        <process-id>1</process-id>
                        <areas>
                          <area>
                            <area-id>0.0.0.0</area-id>
                            <interfaces>
                              <interface>
                                <if-name>{alarm.interface_name or 'unknown'}</if-name>
                                <cost>65535</cost>
                              </interface>
                            </interfaces>
                          </area>
                        </areas>
                      </ospf-instance>
                    </ospf-instances>
                  </ospf>
                </config>
                """
                payloads.append(payload.strip())

            elif path["type"] == "explicit-bypass":
                # Static route through alternate next-hop
                next_hop = path.get("next_hop", "10.0.0.254")
                prefix = path.get("prefix", "0.0.0.0/0")
                payload = f"""
                <config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
                  <staticrt xmlns="urn:huawei:params:xml:ns:yang:huawei-staticrt">
                    <static-routes>
                      <static-route>
                        <prefix>{prefix}</prefix>
                        <next-hop>{next_hop}</next-hop>
                        <preference>10</preference>
                        <description>Auto-remediation bypass ({alarm.id})</description>
                      </static-route>
                    </static-routes>
                  </staticrt>
                </config>
                """
                payloads.append(payload.strip())

        return payloads

    async def _deploy_bypass(
        self,
        payloads: list[str],
    ) -> dict[str, Any]:
        """
        Deploy bypass configuration via the Provisioning Engine.

        In production, this calls the provisioning engine's ACID transaction
        pipeline. For now, returns a simulated success.
        """
        try:
            # Would call provisioning engine via HTTP
            # response = await httpx.AsyncClient().post(
            #     f"{settings.provisioning_engine_url}/api/v1/provision",
            #     json={...}
            # )
            logger.info(
                "Deploying %d bypass payloads via provisioning engine",
                len(payloads),
            )
            return {"success": True, "payloads_deployed": len(payloads)}

        except Exception as exc:
            return {"success": False, "error": str(exc)}


def _now():
    from datetime import datetime
    return datetime.utcnow()

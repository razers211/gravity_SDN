"""
Provisioning Orchestrator.

Coordinates multi-device ACID NETCONF transactions for complete
fabric provisioning. Executes provisioning plan steps in dependency
order, manages transaction lifecycle, and publishes audit events.
"""

from __future__ import annotations

import logging
from typing import Any

from shared.config import get_settings
from shared.kafka.producer import AsyncKafkaProducer
from shared.models.device import Device
from shared.netconf.transaction import (
    NetconfTransaction,
    NetconfSessionPool,
    TransactionResult,
    ProvisioningRollbackError,
)
from services.provisioning_engine.payload_builder import PayloadBuilder
from services.provisioning_engine.evpn_provisioner import EVPNProvisioner
from services.provisioning_engine.vxlan_provisioner import VXLANProvisioner

logger = logging.getLogger(__name__)
settings = get_settings()


class ProvisioningOrchestrator:
    """
    Multi-device ACID orchestration engine.

    Workflow:
      1. Resolve target devices from inventory
      2. Generate XML payloads per device from the provisioning plan
      3. Open NetconfTransaction across all target switches
      4. Execute: lock → edit-config → validate → commit
      5. On failure: discard-changes → unlock → raise ProvisioningRollbackError
      6. Publish success/failure audit events to Kafka
    """

    def __init__(self):
        self.session_pool = NetconfSessionPool()
        self.payload_builder = PayloadBuilder()
        self.evpn = EVPNProvisioner()
        self.vxlan = VXLANProvisioner()
        self._kafka: AsyncKafkaProducer | None = None

    def _get_kafka(self) -> AsyncKafkaProducer:
        if not self._kafka:
            self._kafka = AsyncKafkaProducer()
            self._kafka.connect()
        return self._kafka

    async def execute_plan(self, request: Any) -> TransactionResult:
        """
        Execute a provisioning plan with ACID guarantees.

        Args:
            request: ProvisioningRequest from the API

        Returns:
            TransactionResult with success/failure + per-device details
        """
        # Phase 1: Resolve target devices
        devices = await self._resolve_devices(request.target_device_ids)
        if not devices:
            raise ValueError("No valid target devices found")

        # Phase 2: Generate payloads per device
        device_payloads: list[tuple[Device, str]] = []

        for device in devices:
            payload = self._build_device_payload(device, request.plan_steps)
            if payload:
                device_payloads.append((device, payload))

        if not device_payloads:
            raise ValueError("No payloads generated for target devices")

        logger.info(
            "Provisioning plan: %d devices, %d payloads",
            len(devices),
            len(device_payloads),
        )

        # Phase 3: Execute ACID transaction
        if request.dry_run:
            return TransactionResult(
                transaction_id="dry-run",
                state="completed",
                success=True,
                device_results={
                    d.hostname: {"status": "dry-run"} for d, _ in device_payloads
                },
            )

        txn = NetconfTransaction(self.session_pool)

        try:
            result = txn.execute(plan=device_payloads, validate=True)

            # Publish success audit event
            self._publish_audit(
                transaction_id=result.transaction_id,
                intent_id=request.intent_id,
                success=True,
                device_count=len(device_payloads),
            )

            return result

        except ProvisioningRollbackError as exc:
            logger.error("Provisioning rolled back: %s", exc)

            # Publish failure audit event
            self._publish_audit(
                transaction_id=exc.result.transaction_id,
                intent_id=request.intent_id,
                success=False,
                error=str(exc),
                device_count=len(device_payloads),
            )

            raise

    def _build_device_payload(
        self,
        device: Device,
        steps: list[dict],
    ) -> str | None:
        """
        Build a composite XML payload for a single device from plan steps.

        Aggregates multiple configuration sections (BGP, BD, VBDIF, NVE)
        into a single <config> envelope for atomic delivery.
        """
        payload_parts: list[str] = []

        for step in steps:
            action = step.get("action", "")

            if action == "create_vrf":
                xml = self.payload_builder.build_vrf_payload(
                    vrf_name=step["vrf_name"],
                    rd=step["rd"],
                    import_rts=step["import_rts"],
                    export_rts=step["export_rts"],
                    l3_vni=step.get("l3_vni"),
                )
                payload_parts.append(xml)

            elif action == "create_bridge_domain":
                xml = self.payload_builder.build_bridge_domain_payload(
                    bd_id=step["bd_id"],
                    vni=step["vni"],
                )
                payload_parts.append(xml)

            elif action == "create_anycast_gateway":
                xml = self.payload_builder.build_vbdif_payload(
                    bd_id=step["bd_id"],
                    ip_address=step["gateway_ip"],
                    subnet_cidr=step["subnet_cidr"],
                    vrf_name=step.get("vrf_name"),
                )
                payload_parts.append(xml)

            elif action == "configure_bgp_evpn":
                xml = self.evpn.generate_payload(device, step)
                payload_parts.append(xml)

            elif action == "register_vni_on_nve":
                xml = self.vxlan.generate_nve_vni_payload(
                    vni=step["vni"],
                    source_interface=device.vtep_source_interface,
                )
                payload_parts.append(xml)

        if not payload_parts:
            return None

        # Combine into single config envelope
        return self.payload_builder.combine_payloads(payload_parts)

    async def _resolve_devices(self, device_ids: list[str]) -> list[Device]:
        """
        Resolve device IDs to Device objects.

        In production, this queries the inventory database. Here we
        provide a stub that can be replaced with actual DB lookup.
        """
        # TODO: Replace with actual inventory query
        # For now, return empty list — caller must provide devices
        logger.warning("Device resolution stub — provide actual inventory lookup")
        return []

    def _publish_audit(
        self,
        transaction_id: str,
        intent_id: str,
        success: bool,
        device_count: int,
        error: str | None = None,
    ) -> None:
        """Publish provisioning audit event to Kafka."""
        try:
            kafka = self._get_kafka()
            kafka.send_audit({
                "transaction_id": transaction_id,
                "intent_id": intent_id,
                "success": success,
                "device_count": device_count,
                "error": error,
            })
        except Exception as exc:
            logger.warning("Failed to publish audit event: %s", exc)

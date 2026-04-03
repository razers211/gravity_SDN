"""
VXLAN Provisioner.

Automates VXLAN data plane configuration including:
  - Bridge Domain creation and VNI binding
  - NVO3 VTEP (NVE) interface configuration
  - VBDIF anycast gateway provisioning
  - VRF instance (L3VPN) with import/export RT for symmetric IRB
"""

from __future__ import annotations

import logging
from typing import Any

from shared.models.device import Device
from shared.models.fabric import BridgeDomain, VPNInstance
from services.provisioning_engine.payload_builder import PayloadBuilder

logger = logging.getLogger(__name__)


class VXLANProvisioner:
    """Generates VXLAN data plane configuration payloads for CloudEngine switches."""

    def __init__(self):
        self.payload_builder = PayloadBuilder()

    def generate_full_distributed_gateway(
        self,
        device: Device,
        bridge_domains: list[BridgeDomain],
        vpn_instance: VPNInstance,
    ) -> str:
        """
        Generate complete distributed VXLAN gateway configuration for a leaf switch.

        Produces a composite payload covering:
          1. VRF instance with L3 VNI binding
          2. Bridge Domains with L2 VNI binding and EVPN instances
          3. VBDIF anycast gateway interfaces
          4. NVE interface with all VNI members
        """
        payloads: list[str] = []

        # Step 1: VRF / VPN Instance
        import_rts = [rt.value for rt in vpn_instance.import_route_targets]
        export_rts = [rt.value for rt in vpn_instance.export_route_targets]

        vrf_payload = self.payload_builder.build_vrf_payload(
            vrf_name=vpn_instance.name,
            rd=vpn_instance.route_distinguisher,
            import_rts=import_rts,
            export_rts=export_rts,
            l3_vni=vpn_instance.l3_vni,
        )
        payloads.append(vrf_payload)

        # Step 2: Bridge Domains with EVPN instances
        for bd in bridge_domains:
            evpn_instance = None
            if bd.evpn_instance_name:
                evpn_instance = {
                    "name": bd.evpn_instance_name,
                    "rd": bd.route_distinguisher,
                    "import_rts": [rt.value for rt in bd.route_targets if rt.type in ("import", "both")],
                    "export_rts": [rt.value for rt in bd.route_targets if rt.type in ("export", "both")],
                }

            bd_payload = self.payload_builder.build_bridge_domain_payload(
                bd_id=bd.bd_id,
                vni=bd.vni,
                description=bd.description or f"BD-{bd.bd_id}",
                evpn_instance=evpn_instance,
            )
            payloads.append(bd_payload)

        # Step 3: VBDIF Anycast Gateways
        for bd in bridge_domains:
            if bd.vbdif_ip:
                ip_parts = bd.vbdif_ip.split("/")
                ip_address = ip_parts[0]
                prefix_len = ip_parts[1] if len(ip_parts) > 1 else "24"

                vbdif_payload = self.payload_builder.build_vbdif_payload(
                    bd_id=bd.bd_id,
                    ip_address=ip_address,
                    subnet_cidr=bd.vbdif_ip,
                    vrf_name=vpn_instance.name,
                    anycast_mac=bd.vbdif_mac or "00:00:5e:00:01:01",
                )
                payloads.append(vbdif_payload)

        # Step 4: NVE Interface with VNI members
        vni_list: list[dict[str, Any]] = []
        for bd in bridge_domains:
            if bd.vni:
                vni_list.append({
                    "vni": bd.vni,
                    "type": "l2",
                    "protocol": "bgp",
                })

        # Add L3 VNI for symmetric IRB
        if vpn_instance.l3_vni:
            vni_list.append({
                "vni": vpn_instance.l3_vni,
                "type": "l3",
            })

        nve_payload = self.payload_builder.build_vxlan_nvo3_payload(
            source_interface=device.vtep_source_interface,
            vni_list=vni_list,
        )
        payloads.append(nve_payload)

        # Combine all payloads
        return self.payload_builder.combine_payloads(payloads)

    def generate_nve_vni_payload(
        self,
        vni: int,
        source_interface: str = "LoopBack1",
        vni_type: str = "l2",
    ) -> str:
        """Generate a payload to add a single VNI to the NVE interface."""
        return self.payload_builder.build_vxlan_nvo3_payload(
            source_interface=source_interface,
            vni_list=[{"vni": vni, "type": vni_type, "protocol": "bgp"}],
        )

    def generate_bd_vni_binding(self, bd_id: int, vni: int) -> str:
        """Generate a payload to bind a VNI to a Bridge Domain."""
        return self.payload_builder.build_bridge_domain_payload(
            bd_id=bd_id,
            vni=vni,
        )

    def generate_anycast_gateway(
        self,
        bd_id: int,
        gateway_ip: str,
        subnet_cidr: str,
        vrf_name: str,
        anycast_mac: str = "00:00:5e:00:01:01",
    ) -> str:
        """Generate VBDIF anycast gateway configuration."""
        return self.payload_builder.build_vbdif_payload(
            bd_id=bd_id,
            ip_address=gateway_ip,
            subnet_cidr=subnet_cidr,
            vrf_name=vrf_name,
            anycast_mac=anycast_mac,
        )

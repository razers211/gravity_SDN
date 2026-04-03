"""
BGP EVPN Provisioner.

Automates BGP EVPN overlay configuration including:
  - BGP peer construction (iBGP full-mesh or RR client designation)
  - EVPN instance creation with RD/RT
  - L2VPN EVPN address-family activation
  - Route Reflector role assignment
"""

from __future__ import annotations

import logging
from typing import Any

from shared.models.device import Device, DeviceRole
from services.provisioning_engine.payload_builder import PayloadBuilder

logger = logging.getLogger(__name__)


class EVPNProvisioner:
    """Generates BGP EVPN configuration payloads for CloudEngine switches."""

    def __init__(self):
        self.payload_builder = PayloadBuilder()

    def generate_payload(self, device: Device, config: dict[str, Any]) -> str:
        """
        Generate BGP EVPN payload for a specific device based on its role.

        Spine/RR devices:
          - Act as Route Reflectors
          - Peer with all leaf switches as RR clients

        Leaf devices:
          - Peer with spine/RR switches
          - Enable L2VPN EVPN address-family
        """
        bgp_asn = config.get("bgp_asn", device.bgp_asn or 65000)
        router_id = config.get("router_id", device.router_id or str(device.management_ip))

        # Build peer list based on device role
        peers = config.get("peers", [])
        bgp_peers = [
            {
                "address": peer["address"],
                "as_number": peer.get("as_number", bgp_asn),
                "connect_interface": peer.get("connect_interface", "LoopBack0"),
                "is_rr_client": peer.get("is_rr_client", False),
            }
            for peer in peers
        ]

        return self.payload_builder.build_bgp_evpn_payload(
            bgp_asn=bgp_asn,
            router_id=router_id,
            bgp_peers=bgp_peers,
            peer_group_name=config.get("peer_group_name", "EVPN-OVERLAY"),
            connect_interface=config.get("connect_interface", "LoopBack0"),
            is_route_reflector=device.is_route_reflector or device.role == DeviceRole.ROUTE_REFLECTOR,
        )

    def generate_rr_config(
        self,
        rr_device: Device,
        client_devices: list[Device],
        bgp_asn: int = 65000,
    ) -> str:
        """
        Generate Route Reflector configuration.

        The RR peers with all client devices and reflects EVPN routes.
        """
        peers = [
            {
                "address": str(client.router_id or client.management_ip),
                "as_number": bgp_asn,
                "connect_interface": "LoopBack0",
                "is_rr_client": True,
            }
            for client in client_devices
        ]

        return self.payload_builder.build_bgp_evpn_payload(
            bgp_asn=bgp_asn,
            router_id=str(rr_device.router_id or rr_device.management_ip),
            bgp_peers=peers,
            peer_group_name="EVPN-OVERLAY",
            is_route_reflector=True,
        )

    def generate_leaf_config(
        self,
        leaf_device: Device,
        rr_addresses: list[str],
        bgp_asn: int = 65000,
    ) -> str:
        """
        Generate leaf switch BGP EVPN configuration.

        The leaf peers with all Route Reflectors.
        """
        peers = [
            {
                "address": rr_addr,
                "as_number": bgp_asn,
                "connect_interface": "LoopBack0",
                "is_rr_client": False,
            }
            for rr_addr in rr_addresses
        ]

        return self.payload_builder.build_bgp_evpn_payload(
            bgp_asn=bgp_asn,
            router_id=str(leaf_device.router_id or leaf_device.management_ip),
            bgp_peers=peers,
            peer_group_name="EVPN-OVERLAY",
            is_route_reflector=False,
        )

    def generate_evpn_instance(
        self,
        instance_name: str,
        bd_id: int,
        rd: str,
        import_rts: list[str],
        export_rts: list[str],
    ) -> str:
        """
        Generate EVPN instance XML payload for a Bridge Domain.

        This creates the EVPN instance that controls MAC/IP route
        distribution for the associated Bridge Domain.
        """
        return self.payload_builder.build_bridge_domain_payload(
            bd_id=bd_id,
            evpn_instance={
                "name": instance_name,
                "rd": rd,
                "import_rts": import_rts,
                "export_rts": export_rts,
            },
        )

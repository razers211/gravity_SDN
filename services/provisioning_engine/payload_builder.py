"""
XML Payload Builder.

Assembles NETCONF <edit-config> XML payloads from Jinja2 templates
and domain model values. Supports merge, replace, and delete operations.

All payloads target Huawei CloudEngine proprietary YANG models.
"""

from __future__ import annotations

import logging
import os
from ipaddress import IPv4Network
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from lxml import etree

logger = logging.getLogger(__name__)

# Template directory
TEMPLATE_DIR = Path(__file__).parent.parent.parent / "shared" / "netconf" / "xml_templates"


class PayloadBuilder:
    """
    Builds XML payloads for NETCONF edit-config operations using Jinja2 templates.
    """

    def __init__(self, template_dir: str | Path | None = None):
        self._template_dir = Path(template_dir) if template_dir else TEMPLATE_DIR
        self._env = Environment(
            loader=FileSystemLoader(str(self._template_dir)),
            autoescape=select_autoescape(["xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        logger.debug("Payload builder initialized with templates from: %s", self._template_dir)

    def render_template(self, template_name: str, **kwargs: Any) -> str:
        """Render a Jinja2 XML template with the provided context."""
        template = self._env.get_template(template_name)
        rendered = template.render(**kwargs)
        logger.debug("Rendered template '%s' (%d bytes)", template_name, len(rendered))
        return rendered

    def build_bgp_evpn_payload(
        self,
        bgp_asn: int,
        router_id: str,
        bgp_peers: list[dict[str, Any]],
        peer_group_name: str = "EVPN-OVERLAY",
        connect_interface: str = "LoopBack0",
        is_route_reflector: bool = False,
    ) -> str:
        """Build BGP EVPN configuration payload."""
        return self.render_template(
            "bgp_evpn.xml.j2",
            bgp_asn=bgp_asn,
            router_id=router_id,
            bgp_peers=bgp_peers,
            peer_group_name=peer_group_name,
            connect_interface=connect_interface,
            is_route_reflector=is_route_reflector,
        )

    def build_vxlan_nvo3_payload(
        self,
        source_interface: str,
        vni_list: list[dict[str, Any]],
        nve_interface: str = "Nve1",
        protocol_bgp: bool = True,
    ) -> str:
        """Build VXLAN NVO3 (NVE) configuration payload."""
        return self.render_template(
            "vxlan_nvo3.xml.j2",
            nve_interface=nve_interface,
            source_interface=source_interface,
            vni_list=vni_list,
            protocol_bgp=protocol_bgp,
        )

    def build_bridge_domain_payload(
        self,
        bd_id: int,
        vni: int | None = None,
        description: str = "",
        evpn_instance: dict[str, Any] | None = None,
        member_interfaces: list[dict[str, Any]] | None = None,
    ) -> str:
        """Build Bridge Domain configuration payload."""
        bd_data = {
            "bd_id": bd_id,
            "vni": vni,
            "description": description or f"BD-{bd_id}",
        }

        if evpn_instance:
            bd_data["evpn_instance"] = evpn_instance
        if member_interfaces:
            bd_data["member_interfaces"] = member_interfaces

        return self.render_template(
            "bridge_domain.xml.j2",
            bridge_domains=[bd_data],
        )

    def build_vrf_payload(
        self,
        vrf_name: str,
        rd: str,
        import_rts: list[str],
        export_rts: list[str],
        l3_vni: int | None = None,
        ipv4_unicast: bool = True,
        evpn: bool = True,
    ) -> str:
        """Build VRF / VPN Instance configuration payload."""
        vrf_data = {
            "name": vrf_name,
            "route_distinguisher": rd,
            "import_route_targets": import_rts,
            "export_route_targets": export_rts,
            "l3_vni": l3_vni,
            "ipv4_unicast": ipv4_unicast,
            "evpn": evpn,
            "evpn_import_rts": import_rts,
            "evpn_export_rts": export_rts,
        }
        return self.render_template(
            "vrf_instance.xml.j2",
            vrf_instances=[vrf_data],
        )

    def build_vbdif_payload(
        self,
        bd_id: int,
        ip_address: str,
        subnet_cidr: str,
        vrf_name: str | None = None,
        anycast_mac: str = "00:00:5e:00:01:01",
        arp_proxy: bool = True,
    ) -> str:
        """Build VBDIF anycast gateway configuration payload."""
        network = IPv4Network(subnet_cidr, strict=False)
        gw_data = {
            "bd_id": bd_id,
            "ip_address": ip_address,
            "subnet_mask": str(network.netmask),
            "anycast_mac": anycast_mac,
            "arp_proxy": arp_proxy,
            "vrf_name": vrf_name,
        }
        return self.render_template(
            "vbdif_gateway.xml.j2",
            anycast_gateways=[gw_data],
        )

    def build_route_targets_payload(
        self,
        vrf_route_targets: list[dict[str, Any]] | None = None,
        evpn_route_targets: list[dict[str, Any]] | None = None,
    ) -> str:
        """Build Route Target configuration payload."""
        return self.render_template(
            "route_targets.xml.j2",
            vrf_route_targets=vrf_route_targets,
            evpn_route_targets=evpn_route_targets,
        )

    def combine_payloads(self, payloads: list[str]) -> str:
        """
        Combine multiple XML payload fragments into a single <config> envelope.

        Merges child elements from each payload's <config> element into
        a unified configuration block for atomic edit-config delivery.
        """
        combined_root = etree.Element(
            "config",
            nsmap={None: "urn:ietf:params:xml:ns:netconf:base:1.0"},
        )

        for payload_xml in payloads:
            try:
                root = etree.fromstring(payload_xml.encode("utf-8"))
                # If the root is <config>, merge its children
                if root.tag.endswith("config") or root.tag == "config":
                    for child in root:
                        combined_root.append(child)
                else:
                    combined_root.append(root)
            except etree.XMLSyntaxError as exc:
                logger.error("Invalid XML payload: %s", exc)
                raise ValueError(f"Invalid XML payload: {exc}") from exc

        result = etree.tostring(
            combined_root,
            pretty_print=True,
            xml_declaration=False,
            encoding="unicode",
        )
        logger.debug("Combined payload: %d fragments → %d bytes", len(payloads), len(result))
        return result

    def validate_payload(self, xml_payload: str) -> bool:
        """Validate that an XML payload is well-formed."""
        try:
            etree.fromstring(xml_payload.encode("utf-8"))
            return True
        except etree.XMLSyntaxError as exc:
            logger.error("XML validation failed: %s", exc)
            return False

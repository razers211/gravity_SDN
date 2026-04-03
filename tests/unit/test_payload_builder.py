"""
Unit tests for the XML Payload Builder.
"""

from __future__ import annotations

import pytest
from lxml import etree

from services.provisioning_engine.payload_builder import PayloadBuilder


@pytest.fixture
def builder():
    return PayloadBuilder()


class TestBGPEVPNPayload:
    """Tests for BGP EVPN payload generation."""

    def test_generates_valid_xml(self, builder):
        xml = builder.build_bgp_evpn_payload(
            bgp_asn=65000,
            router_id="10.0.0.1",
            bgp_peers=[
                {"address": "10.0.0.101", "as_number": 65000, "connect_interface": "LoopBack0"},
            ],
        )
        assert xml is not None
        # Should be valid XML
        root = etree.fromstring(xml.encode("utf-8"))
        assert root is not None

    def test_contains_asn(self, builder):
        xml = builder.build_bgp_evpn_payload(
            bgp_asn=65000,
            router_id="10.0.0.1",
            bgp_peers=[],
        )
        assert "65000" in xml

    def test_contains_peer_address(self, builder):
        xml = builder.build_bgp_evpn_payload(
            bgp_asn=65000,
            router_id="10.0.0.1",
            bgp_peers=[
                {"address": "10.0.0.101", "as_number": 65000, "connect_interface": "LoopBack0"},
            ],
        )
        assert "10.0.0.101" in xml


class TestBridgeDomainPayload:
    """Tests for Bridge Domain payload generation."""

    def test_generates_bd_with_vni(self, builder):
        xml = builder.build_bridge_domain_payload(bd_id=100, vni=10100)
        assert "100" in xml
        assert "10100" in xml

    def test_valid_xml(self, builder):
        xml = builder.build_bridge_domain_payload(bd_id=200, vni=10200)
        root = etree.fromstring(xml.encode("utf-8"))
        assert root is not None


class TestVRFPayload:
    """Tests for VRF payload generation."""

    def test_generates_vrf(self, builder):
        xml = builder.build_vrf_payload(
            vrf_name="vrf-test",
            rd="65000:100",
            import_rts=["65000:100"],
            export_rts=["65000:100"],
            l3_vni=50000,
        )
        assert "vrf-test" in xml
        assert "65000:100" in xml
        assert "50000" in xml

    def test_valid_xml(self, builder):
        xml = builder.build_vrf_payload(
            vrf_name="vrf-a",
            rd="65000:1",
            import_rts=["65000:1"],
            export_rts=["65000:1"],
        )
        root = etree.fromstring(xml.encode("utf-8"))
        assert root is not None


class TestVBDIFPayload:
    """Tests for VBDIF anycast gateway payload generation."""

    def test_generates_gateway(self, builder):
        xml = builder.build_vbdif_payload(
            bd_id=100,
            ip_address="10.100.1.1",
            subnet_cidr="10.100.1.0/24",
            vrf_name="vrf-test",
        )
        assert "Vbdif100" in xml
        assert "10.100.1.1" in xml
        assert "vrf-test" in xml

    def test_contains_anycast_mac(self, builder):
        xml = builder.build_vbdif_payload(
            bd_id=100,
            ip_address="10.100.1.1",
            subnet_cidr="10.100.1.0/24",
            anycast_mac="00:00:5e:00:01:01",
        )
        assert "00:00:5e:00:01:01" in xml


class TestPayloadCombination:
    """Tests for combining multiple payloads."""

    def test_combines_two_payloads(self, builder):
        p1 = builder.build_bridge_domain_payload(bd_id=100, vni=10100)
        p2 = builder.build_vrf_payload(
            vrf_name="vrf-a", rd="65000:1",
            import_rts=["65000:1"], export_rts=["65000:1"],
        )
        combined = builder.combine_payloads([p1, p2])
        assert combined is not None
        root = etree.fromstring(combined.encode("utf-8"))
        assert len(root) >= 2  # At least 2 child elements

    def test_validate_payload(self, builder):
        xml = "<config><test>hello</test></config>"
        assert builder.validate_payload(xml) is True

    def test_invalid_payload_fails_validation(self, builder):
        xml = "<config><unclosed>"
        assert builder.validate_payload(xml) is False

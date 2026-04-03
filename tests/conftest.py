"""
Pytest configuration and shared fixtures.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_intent_payload() -> dict:
    """Sample intent payload for testing."""
    return {
        "tenant": {"name": "Test-Tenant"},
        "vpcs": [
            {
                "name": "vpc-test",
                "subnets": [
                    {"name": "subnet-web", "cidr": "10.100.1.0/24"},
                    {"name": "subnet-db", "cidr": "10.100.2.0/24"},
                ],
                "firewall_policies": [
                    {
                        "name": "microseg-test",
                        "source_subnets": ["subnet-web"],
                        "destination_subnets": ["subnet-db"],
                        "rules": [
                            {
                                "name": "deny-web-to-db",
                                "source_subnet": "subnet-web",
                                "destination_subnet": "subnet-db",
                                "action": "deny",
                            }
                        ],
                    }
                ],
            }
        ],
        "dry_run": True,
    }


@pytest.fixture
def sample_device_data() -> dict:
    """Sample device data for testing."""
    return {
        "hostname": "ce-leaf-test-01",
        "management_ip": "10.255.0.100",
        "esn": "TEST-ESN-001",
        "model": "CE6800",
        "role": "leaf",
        "bgp_asn": 65000,
        "router_id": "10.0.0.100",
        "vtep_ip": "10.0.0.100",
        "site": "dc-test",
        "pod": "pod-test",
    }

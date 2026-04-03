"""
Security Policy Engine.

Evaluates microsegmentation rules to generate:
  - ACL configurations for inter-subnet traffic control
  - Firewall insertion points (service function chaining)
  - Policy enforcement matrices
"""

from __future__ import annotations

import logging
from typing import Any

from shared.models.intent import (
    FirewallPolicy,
    IntentPayload,
    MicrosegmentationRule,
    PolicyAction,
)
from services.intent_engine.translator import NetworkState

logger = logging.getLogger(__name__)


class PolicyEngine:
    """
    Evaluates and compiles microsegmentation policies into
    enforceable network configurations.
    """

    def evaluate(
        self,
        intent: IntentPayload,
        state: NetworkState,
    ) -> PolicyEvaluationResult:
        """
        Evaluate all firewall policies and generate enforcement actions.

        Returns:
            PolicyEvaluationResult with ACL rules and SFC paths.
        """
        result = PolicyEvaluationResult()

        for vpc in intent.vpcs:
            for policy in vpc.firewall_policies:
                if not policy.enabled:
                    continue

                acl_rules = self._compile_policy_to_acl(policy, state)
                result.acl_rules.extend(acl_rules)

                # Determine firewall insertion points
                if policy.firewall_type == "virtual":
                    sfc_path = self._compute_sfc_path(policy, state)
                    if sfc_path:
                        result.sfc_paths.append(sfc_path)

        logger.info(
            "Policy evaluation: %d ACL rules, %d SFC paths",
            len(result.acl_rules),
            len(result.sfc_paths),
        )
        return result

    def _compile_policy_to_acl(
        self,
        policy: FirewallPolicy,
        state: NetworkState,
    ) -> list[dict[str, Any]]:
        """Compile firewall policy rules into ACL entries."""
        acl_rules: list[dict[str, Any]] = []

        for rule in policy.rules:
            src_subnet = state.subnets.get(rule.source_subnet, {})
            dst_subnet = state.subnets.get(rule.destination_subnet, {})

            acl_entry = {
                "rule_name": rule.name,
                "acl_number": 3000 + rule.priority,
                "action": "permit" if rule.action == PolicyAction.PERMIT else "deny",
                "protocol": rule.protocol.value,
                "source_cidr": src_subnet.get("cidr", "any"),
                "destination_cidr": dst_subnet.get("cidr", "any"),
                "source_port": rule.source_port,
                "destination_port": rule.destination_port,
                "priority": rule.priority,
            }
            acl_rules.append(acl_entry)

        # Sort by priority (lower number = higher priority)
        acl_rules.sort(key=lambda r: r["priority"])
        return acl_rules

    def _compute_sfc_path(
        self,
        policy: FirewallPolicy,
        state: NetworkState,
    ) -> dict[str, Any] | None:
        """
        Compute service function chain path for firewall insertion.

        Returns the chain: source_subnet → firewall → destination_subnet
        """
        if not policy.source_subnets or not policy.destination_subnets:
            return None

        return {
            "policy_name": policy.name,
            "chain": [
                {"type": "source", "subnets": policy.source_subnets},
                {"type": "firewall", "firewall_type": policy.firewall_type},
                {"type": "destination", "subnets": policy.destination_subnets},
            ],
            "redirect_mode": "traffic-policy",
        }


class PolicyEvaluationResult:
    """Result of policy evaluation."""

    def __init__(self):
        self.acl_rules: list[dict[str, Any]] = []
        self.sfc_paths: list[dict[str, Any]] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "acl_rule_count": len(self.acl_rules),
            "sfc_path_count": len(self.sfc_paths),
            "acl_rules": self.acl_rules,
            "sfc_paths": self.sfc_paths,
        }

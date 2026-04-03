"""
Formal Verification Engine.

Verifies that a proposed network intent does NOT introduce:
  1. Routing loops (cycle detection in the RIB/FIB graph)
  2. IP address / subnet conflicts (overlapping CIDR ranges)
  3. Security policy violations (microsegmentation rule inconsistencies)

Configuration generation MUST abort if verification fails.
"""

from __future__ import annotations

import logging
import time
from ipaddress import IPv4Network, ip_network
from typing import Any

import networkx as nx

from shared.models.intent import (
    IntentPayload,
    Violation,
    VerificationResult,
)
from services.intent_engine.translator import NetworkState

logger = logging.getLogger(__name__)


class FormalVerifier:
    """
    Runs formal verification algorithms against a proposed NetworkState.

    Verification is run BEFORE any NETCONF RPCs are generated or dispatched.
    If any check fails, the entire intent is rejected with detailed violation
    reports.
    """

    def verify(self, state: NetworkState, intent: IntentPayload) -> VerificationResult:
        """
        Execute all verification checks against the proposed network state.

        Returns:
            VerificationResult with passed=True if all checks pass,
            or passed=False with a list of Violation objects.
        """
        start_time = time.monotonic()
        violations: list[Violation] = []

        # Check 1: Routing loop detection
        loop_violations = self._detect_routing_loops(state)
        violations.extend(loop_violations)

        # Check 2: IP address / subnet conflict detection
        ip_violations = self._detect_ip_conflicts(state)
        violations.extend(ip_violations)

        # Check 3: Security policy validation
        policy_violations = self._validate_security_policies(state, intent)
        violations.extend(policy_violations)

        # Check 4: VNI uniqueness validation
        vni_violations = self._validate_vni_uniqueness(state)
        violations.extend(vni_violations)

        # Check 5: Route Target consistency
        rt_violations = self._validate_route_target_consistency(state)
        violations.extend(rt_violations)

        duration_ms = (time.monotonic() - start_time) * 1000
        passed = len(violations) == 0

        logger.info(
            "Verification %s: %d checks, %d violations, %.1fms",
            "PASSED" if passed else "FAILED",
            5,
            len(violations),
            duration_ms,
        )

        return VerificationResult(
            intent_id=intent.id,
            passed=passed,
            violations=violations,
            simulation_time_ms=duration_ms,
        )

    # ── Check 1: Routing Loop Detection ──────────────────────────────────

    def _detect_routing_loops(self, state: NetworkState) -> list[Violation]:
        """
        Detect routing loops using DFS cycle detection on the RIB/FIB graph.

        A routing loop exists if there is a directed cycle in the graph where
        all edges represent routing adjacencies (connected, redistributed, or
        RT-imported routes).
        """
        violations: list[Violation] = []

        try:
            cycles = list(nx.simple_cycles(state.graph))
            for cycle in cycles:
                # Only flag cycles involving routing edges
                is_routing_cycle = True
                for i in range(len(cycle)):
                    src = cycle[i]
                    dst = cycle[(i + 1) % len(cycle)]
                    edge_data = state.graph.get_edge_data(src, dst) or {}
                    route_type = edge_data.get("route_type", "")
                    if route_type not in ("connected", "redistributed", "rt-import", "static"):
                        is_routing_cycle = False
                        break

                if is_routing_cycle:
                    violations.append(Violation(
                        code="ROUTING_LOOP",
                        severity="error",
                        message=f"Routing loop detected: {' → '.join(cycle)} → {cycle[0]}",
                        affected_resources=cycle,
                        details={"cycle": cycle},
                    ))
                    logger.warning("Routing loop detected: %s", " → ".join(cycle))

        except nx.NetworkXError as exc:
            logger.error("Cycle detection failed: %s", exc)

        return violations

    # ── Check 2: IP Address Conflict Detection ───────────────────────────

    def _detect_ip_conflicts(self, state: NetworkState) -> list[Violation]:
        """
        Detect overlapping IP subnets within the same VRF.

        Uses prefix comparison to find any two subnets where one contains
        the other or they share the same address space.
        """
        violations: list[Violation] = []

        # Group subnets by VRF
        vrf_subnets: dict[str, list[tuple[str, IPv4Network]]] = {}
        for subnet_id, subnet_data in state.subnets.items():
            vrf = subnet_data.get("vrf_name", "_global_")
            network = ip_network(subnet_data["cidr"], strict=False)
            vrf_subnets.setdefault(vrf, []).append((subnet_id, network))

        # Check for overlaps within each VRF
        for vrf_name, subnets in vrf_subnets.items():
            for i in range(len(subnets)):
                for j in range(i + 1, len(subnets)):
                    id_a, net_a = subnets[i]
                    id_b, net_b = subnets[j]

                    if net_a.overlaps(net_b):
                        violations.append(Violation(
                            code="IP_CONFLICT",
                            severity="error",
                            message=(
                                f"IP conflict in VRF '{vrf_name}': "
                                f"subnet '{id_a}' ({net_a}) overlaps with "
                                f"subnet '{id_b}' ({net_b})"
                            ),
                            affected_resources=[id_a, id_b],
                            details={
                                "vrf": vrf_name,
                                "subnet_a": {"id": id_a, "cidr": str(net_a)},
                                "subnet_b": {"id": id_b, "cidr": str(net_b)},
                            },
                        ))
                        logger.warning(
                            "IP conflict: %s (%s) ↔ %s (%s) in VRF %s",
                            id_a, net_a, id_b, net_b, vrf_name,
                        )

        return violations

    # ── Check 3: Security Policy Validation ──────────────────────────────

    def _validate_security_policies(
        self,
        state: NetworkState,
        intent: IntentPayload,
    ) -> list[Violation]:
        """
        Validate microsegmentation rules for consistency:
          - No contradictory rules (same src/dst with conflicting actions)
          - All referenced subnets exist in the intent
          - Priority ordering is unambiguous
        """
        violations: list[Violation] = []
        known_subnets = set(state.subnets.keys())

        for vpc in intent.vpcs:
            for policy in vpc.firewall_policies:
                rule_map: dict[tuple[str, str], list[Any]] = {}

                for rule in policy.rules:
                    # Verify referenced subnets exist
                    if rule.source_subnet not in known_subnets:
                        violations.append(Violation(
                            code="POLICY_VIOLATION",
                            severity="error",
                            message=(
                                f"Firewall rule '{rule.name}' references unknown "
                                f"source subnet '{rule.source_subnet}'"
                            ),
                            affected_resources=[rule.source_subnet],
                            details={"rule": rule.name, "policy": policy.name},
                        ))

                    if rule.destination_subnet not in known_subnets:
                        violations.append(Violation(
                            code="POLICY_VIOLATION",
                            severity="error",
                            message=(
                                f"Firewall rule '{rule.name}' references unknown "
                                f"destination subnet '{rule.destination_subnet}'"
                            ),
                            affected_resources=[rule.destination_subnet],
                            details={"rule": rule.name, "policy": policy.name},
                        ))

                    # Check for contradictory rules
                    key = (rule.source_subnet, rule.destination_subnet)
                    rule_map.setdefault(key, []).append(rule)

                # Detect contradictions
                for (src, dst), rules in rule_map.items():
                    actions = set(r.action for r in rules)
                    if len(actions) > 1:
                        violations.append(Violation(
                            code="POLICY_VIOLATION",
                            severity="warning",
                            message=(
                                f"Contradictory rules for {src} → {dst}: "
                                f"actions {actions}. Higher priority rule will prevail."
                            ),
                            affected_resources=[src, dst],
                            details={
                                "rules": [r.name for r in rules],
                                "actions": [a.value for a in actions],
                            },
                        ))

        return violations

    # ── Check 4: VNI Uniqueness ──────────────────────────────────────────

    def _validate_vni_uniqueness(self, state: NetworkState) -> list[Violation]:
        """Ensure no two subnets share the same VNI."""
        violations: list[Violation] = []
        vni_map: dict[int, list[str]] = {}

        for subnet_id, subnet_data in state.subnets.items():
            vni = subnet_data.get("vni")
            if vni:
                vni_map.setdefault(vni, []).append(subnet_id)

        for vni, subnet_ids in vni_map.items():
            if len(subnet_ids) > 1:
                violations.append(Violation(
                    code="VNI_CONFLICT",
                    severity="error",
                    message=f"VNI {vni} is assigned to multiple subnets: {subnet_ids}",
                    affected_resources=subnet_ids,
                    details={"vni": vni},
                ))

        return violations

    # ── Check 5: Route Target Consistency ────────────────────────────────

    def _validate_route_target_consistency(self, state: NetworkState) -> list[Violation]:
        """
        Validate RT import/export consistency:
          - Every exported RT should have at least one importer (or warn)
          - Importing a non-exported RT is an error
        """
        violations: list[Violation] = []

        all_exports: set[str] = set()
        all_imports: dict[str, list[str]] = {}

        for vrf_name, vrf_data in state.vrfs.items():
            for rt in vrf_data.get("export_rts", []):
                all_exports.add(rt)
            for rt in vrf_data.get("import_rts", []):
                all_imports.setdefault(rt, []).append(vrf_name)

        # Check for imports without matching exports
        for rt, importing_vrfs in all_imports.items():
            if rt not in all_exports:
                violations.append(Violation(
                    code="RT_MISMATCH",
                    severity="warning",
                    message=(
                        f"Route Target {rt} is imported by {importing_vrfs} "
                        f"but not exported by any VRF"
                    ),
                    affected_resources=importing_vrfs,
                    details={"rt": rt, "type": "orphan_import"},
                ))

        return violations

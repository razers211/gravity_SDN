"""
Cypher Query Library for the Network Digital Map.

Provides pre-built Cypher queries for the 5-layer topology model:
  Layer 1: PhysicalDevice (switches, routers)
  Layer 2: Server (compute nodes)
  Layer 3: VirtualNetwork (Bridge Domains, VRFs, VNIs)
  Layer 4: VM (virtual machines)
  Layer 5: Service (tenant applications)

Used by all services needing graph-based topology intelligence:
  - Intent Engine: topology awareness for verification
  - O&M Service: impact analysis for 1-3-5 framework
  - API Gateway: topology visualization endpoints
"""

from __future__ import annotations

from typing import Any

from shared.graph.client import Neo4jClient


class TopologyQueries:
    """Cypher query methods for the Network Digital Map."""

    def __init__(self, client: Neo4jClient):
        self.client = client

    # ── Layer 1: Physical Device Management ──────────────────────────────

    async def upsert_device(self, device_data: dict[str, Any]) -> dict[str, Any]:
        """Create or update a PhysicalDevice node."""
        query = """
        MERGE (d:PhysicalDevice {id: $id})
        SET d += {
            hostname: $hostname,
            management_ip: $management_ip,
            esn: $esn,
            model: $model,
            software_version: $software_version,
            role: $role,
            status: $status,
            site: $site,
            pod: $pod,
            rack: $rack,
            router_id: $router_id,
            vtep_ip: $vtep_ip,
            bgp_asn: $bgp_asn,
            is_route_reflector: $is_route_reflector,
            updated_at: datetime()
        }
        RETURN d
        """
        results = await self.client.execute_write(query, device_data)
        return results[0] if results else {}

    async def create_link(
        self,
        src_device_id: str,
        src_interface: str,
        dst_device_id: str,
        dst_interface: str,
        link_speed_mbps: int = 10000,
    ) -> dict[str, Any]:
        """Create a bidirectional physical link between two device interfaces."""
        query = """
        MATCH (src:PhysicalDevice {id: $src_device_id})
        MATCH (dst:PhysicalDevice {id: $dst_device_id})
        MERGE (src_if:Interface {name: $src_interface, device_id: $src_device_id})
        MERGE (dst_if:Interface {name: $dst_interface, device_id: $dst_device_id})
        MERGE (src)-[:HAS_INTERFACE]->(src_if)
        MERGE (dst)-[:HAS_INTERFACE]->(dst_if)
        MERGE (src_if)-[l:CONNECTED_TO]->(dst_if)
        SET l.speed_mbps = $link_speed_mbps,
            l.status = 'up',
            l.updated_at = datetime()
        RETURN src.hostname AS source, dst.hostname AS destination, l.status AS link_status
        """
        results = await self.client.execute_write(query, {
            "src_device_id": src_device_id,
            "src_interface": src_interface,
            "dst_device_id": dst_device_id,
            "dst_interface": dst_interface,
            "link_speed_mbps": link_speed_mbps,
        })
        return results[0] if results else {}

    async def get_device_by_hostname(self, hostname: str) -> dict[str, Any] | None:
        """Find a device by hostname."""
        query = "MATCH (d:PhysicalDevice {hostname: $hostname}) RETURN d"
        results = await self.client.execute_read(query, {"hostname": hostname})
        return results[0] if results else None

    async def get_all_devices(self, role: str | None = None) -> list[dict[str, Any]]:
        """List all devices, optionally filtered by role."""
        if role:
            query = "MATCH (d:PhysicalDevice {role: $role}) RETURN d ORDER BY d.hostname"
            return await self.client.execute_read(query, {"role": role})
        query = "MATCH (d:PhysicalDevice) RETURN d ORDER BY d.hostname"
        return await self.client.execute_read(query)

    # ── Layer 2: Server Management ───────────────────────────────────────

    async def upsert_server(self, server_data: dict[str, Any]) -> dict[str, Any]:
        """Create or update a Server node and link to its leaf switch."""
        query = """
        MERGE (s:Server {id: $id})
        SET s += {
            hostname: $hostname,
            ip_address: $ip_address,
            hypervisor: $hypervisor,
            status: $status,
            updated_at: datetime()
        }
        WITH s
        OPTIONAL MATCH (d:PhysicalDevice {id: $connected_device_id})
        FOREACH (_ IN CASE WHEN d IS NOT NULL THEN [1] ELSE [] END |
            MERGE (s)-[:CONNECTED_TO_SWITCH]->(d)
        )
        RETURN s
        """
        results = await self.client.execute_write(query, server_data)
        return results[0] if results else {}

    # ── Layer 3: Virtual Network Management ──────────────────────────────

    async def upsert_virtual_network(self, vn_data: dict[str, Any]) -> dict[str, Any]:
        """Create or update a VirtualNetwork node (BD, VRF, or VNI)."""
        query = """
        MERGE (vn:VirtualNetwork {id: $id})
        SET vn += {
            name: $name,
            type: $type,
            vni: $vni,
            bd_id: $bd_id,
            vrf_name: $vrf_name,
            cidr: $cidr,
            tenant_id: $tenant_id,
            status: $status,
            updated_at: datetime()
        }
        RETURN vn
        """
        results = await self.client.execute_write(query, vn_data)
        return results[0] if results else {}

    async def link_vn_to_device(self, vn_id: str, device_id: str) -> None:
        """Create a HOSTED_ON relationship between VirtualNetwork and PhysicalDevice."""
        query = """
        MATCH (vn:VirtualNetwork {id: $vn_id})
        MATCH (d:PhysicalDevice {id: $device_id})
        MERGE (vn)-[:HOSTED_ON]->(d)
        """
        await self.client.execute_write(query, {"vn_id": vn_id, "device_id": device_id})

    # ── Layer 4: VM Management ───────────────────────────────────────────

    async def upsert_vm(self, vm_data: dict[str, Any]) -> dict[str, Any]:
        """Create or update a VM node and link to server and virtual network."""
        query = """
        MERGE (vm:VM {id: $id})
        SET vm += {
            name: $name,
            ip_address: $ip_address,
            mac_address: $mac_address,
            status: $status,
            tenant_id: $tenant_id,
            updated_at: datetime()
        }
        WITH vm
        OPTIONAL MATCH (s:Server {id: $server_id})
        FOREACH (_ IN CASE WHEN s IS NOT NULL THEN [1] ELSE [] END |
            MERGE (vm)-[:RUNS_ON]->(s)
        )
        WITH vm
        OPTIONAL MATCH (vn:VirtualNetwork {id: $virtual_network_id})
        FOREACH (_ IN CASE WHEN vn IS NOT NULL THEN [1] ELSE [] END |
            MERGE (vm)-[:MEMBER_OF]->(vn)
        )
        RETURN vm
        """
        results = await self.client.execute_write(query, vm_data)
        return results[0] if results else {}

    # ── Layer 5: Service Management ──────────────────────────────────────

    async def upsert_service(self, service_data: dict[str, Any]) -> dict[str, Any]:
        """Create or update a Service node and link to VMs."""
        query = """
        MERGE (svc:Service {id: $id})
        SET svc += {
            name: $name,
            type: $type,
            tenant_id: $tenant_id,
            status: $status,
            updated_at: datetime()
        }
        RETURN svc
        """
        results = await self.client.execute_write(query, service_data)
        return results[0] if results else {}

    async def link_service_to_vm(self, service_id: str, vm_id: str) -> None:
        """Link a Service to a VM."""
        query = """
        MATCH (svc:Service {id: $service_id})
        MATCH (vm:VM {id: $vm_id})
        MERGE (svc)-[:DEPLOYED_ON]->(vm)
        """
        await self.client.execute_write(query, {"service_id": service_id, "vm_id": vm_id})

    # ── Impact Analysis (1-3-5 Framework) ────────────────────────────────

    async def get_impacted_by_link_failure(
        self,
        device_id: str,
        interface_name: str,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Given a failed link (device + interface), traverse the 5-layer graph
        to find ALL impacted resources:
          PhysicalDevice → Server → VirtualNetwork → VM → Service

        This is the core query for the "3 minute — Locate" phase of the
        1-3-5 troubleshooting framework.
        """
        query = """
        // Find the failed interface and connected devices
        MATCH (src:PhysicalDevice {id: $device_id})
              -[:HAS_INTERFACE]->(iface:Interface {name: $interface_name})
              -[:CONNECTED_TO]-(remote_iface:Interface)
              <-[:HAS_INTERFACE]-(remote:PhysicalDevice)

        // Find impacted servers connected to remote device
        OPTIONAL MATCH (server:Server)-[:CONNECTED_TO_SWITCH]->(remote)

        // Find impacted virtual networks hosted on remote device
        OPTIONAL MATCH (vn:VirtualNetwork)-[:HOSTED_ON]->(remote)

        // Find impacted VMs in those virtual networks
        OPTIONAL MATCH (vm:VM)-[:MEMBER_OF]->(vn)

        // Find impacted services on those VMs
        OPTIONAL MATCH (svc:Service)-[:DEPLOYED_ON]->(vm)

        RETURN
            collect(DISTINCT remote {.id, .hostname, .role, .status}) AS impacted_devices,
            collect(DISTINCT server {.id, .hostname, .ip_address}) AS impacted_servers,
            collect(DISTINCT vn {.id, .name, .vni, .bd_id, .tenant_id}) AS impacted_virtual_networks,
            collect(DISTINCT vm {.id, .name, .ip_address, .tenant_id}) AS impacted_vms,
            collect(DISTINCT svc {.id, .name, .tenant_id}) AS impacted_services
        """
        results = await self.client.execute_read(query, {
            "device_id": device_id,
            "interface_name": interface_name,
        })
        if results:
            return results[0]
        return {
            "impacted_devices": [],
            "impacted_servers": [],
            "impacted_virtual_networks": [],
            "impacted_vms": [],
            "impacted_services": [],
        }

    async def get_impacted_by_device_failure(
        self,
        device_id: str,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Given a failed device, find all impacted resources across all 5 layers.
        """
        query = """
        MATCH (d:PhysicalDevice {id: $device_id})

        // All servers connected to this device
        OPTIONAL MATCH (server:Server)-[:CONNECTED_TO_SWITCH]->(d)

        // All virtual networks hosted on this device
        OPTIONAL MATCH (vn:VirtualNetwork)-[:HOSTED_ON]->(d)

        // All VMs in those virtual networks
        OPTIONAL MATCH (vm:VM)-[:MEMBER_OF]->(vn)

        // All services on those VMs
        OPTIONAL MATCH (svc:Service)-[:DEPLOYED_ON]->(vm)

        RETURN
            d {.id, .hostname, .role} AS failed_device,
            collect(DISTINCT server {.id, .hostname}) AS impacted_servers,
            collect(DISTINCT vn {.id, .name, .vni, .tenant_id}) AS impacted_virtual_networks,
            collect(DISTINCT vm {.id, .name, .tenant_id}) AS impacted_vms,
            collect(DISTINCT svc {.id, .name, .tenant_id}) AS impacted_services
        """
        results = await self.client.execute_read(query, {"device_id": device_id})
        return results[0] if results else {}

    # ── Topology Queries ─────────────────────────────────────────────────

    async def get_full_topology(self) -> dict[str, Any]:
        """Return the complete topology graph for visualization."""
        query = """
        MATCH (d:PhysicalDevice)
        OPTIONAL MATCH (d)-[:HAS_INTERFACE]->(i:Interface)-[l:CONNECTED_TO]-(i2:Interface)<-[:HAS_INTERFACE]-(d2:PhysicalDevice)
        WHERE id(d) < id(d2)
        RETURN
            collect(DISTINCT d {.id, .hostname, .role, .status, .management_ip, .vtep_ip}) AS devices,
            collect(DISTINCT {
                source: d.hostname,
                target: d2.hostname,
                source_if: i.name,
                target_if: i2.name,
                status: l.status
            }) AS links
        """
        results = await self.client.execute_read(query)
        return results[0] if results else {"devices": [], "links": []}

    async def find_alternate_paths(
        self,
        src_device_id: str,
        dst_device_id: str,
        excluded_interfaces: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Find alternate paths between two devices, excluding failed interfaces.

        Used by the "5 minute — Rectify" phase for bypass path computation.
        """
        excluded = excluded_interfaces or []
        query = """
        MATCH (src:PhysicalDevice {id: $src_id})
        MATCH (dst:PhysicalDevice {id: $dst_id})
        MATCH path = allShortestPaths(
            (src)-[:HAS_INTERFACE|CONNECTED_TO*..10]-(dst)
        )
        WHERE NONE(
            r IN relationships(path)
            WHERE r:CONNECTED_TO AND
                  (startNode(r).name IN $excluded OR endNode(r).name IN $excluded)
        )
        RETURN [n IN nodes(path) WHERE n:PhysicalDevice | n.hostname] AS hops,
               length(path) AS path_length
        ORDER BY path_length
        LIMIT 5
        """
        return await self.client.execute_read(query, {
            "src_id": src_device_id,
            "dst_id": dst_device_id,
            "excluded": excluded,
        })

    async def update_link_status(
        self,
        device_id: str,
        interface_name: str,
        status: str,
    ) -> None:
        """Update link status in the graph (used by telemetry consumer)."""
        query = """
        MATCH (d:PhysicalDevice {id: $device_id})
              -[:HAS_INTERFACE]->(i:Interface {name: $interface_name})
              -[l:CONNECTED_TO]-()
        SET l.status = $status, l.updated_at = datetime()
        SET i.status = $status
        """
        await self.client.execute_write(query, {
            "device_id": device_id,
            "interface_name": interface_name,
            "status": status,
        })

    # ── Tenant Topology ──────────────────────────────────────────────────

    async def get_tenant_topology(self, tenant_id: str) -> dict[str, Any]:
        """Get all resources belonging to a specific tenant."""
        query = """
        MATCH (vn:VirtualNetwork {tenant_id: $tenant_id})
        OPTIONAL MATCH (vn)-[:HOSTED_ON]->(d:PhysicalDevice)
        OPTIONAL MATCH (vm:VM {tenant_id: $tenant_id})-[:MEMBER_OF]->(vn)
        OPTIONAL MATCH (svc:Service {tenant_id: $tenant_id})-[:DEPLOYED_ON]->(vm)
        RETURN
            collect(DISTINCT vn {.id, .name, .vni, .bd_id}) AS virtual_networks,
            collect(DISTINCT d {.id, .hostname, .role}) AS devices,
            collect(DISTINCT vm {.id, .name, .ip_address}) AS vms,
            collect(DISTINCT svc {.id, .name}) AS services
        """
        results = await self.client.execute_read(query, {"tenant_id": tenant_id})
        return results[0] if results else {}

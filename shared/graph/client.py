"""
Neo4j Graph Database Client.

Provides an async-compatible wrapper around the Neo4j Python driver for the
5-layer Network Digital Map: Physical Device → Server → Virtual Network → VM → Service.

Supports connection pooling, health checks, and transaction functions.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession, AsyncTransaction
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from shared.config import Settings, get_settings

logger = logging.getLogger(__name__)


class GraphDBError(Exception):
    """Raised on graph database operation failures."""


class Neo4jClient:
    """
    Async Neo4j client for the Network Digital Map.

    Manages driver lifecycle, session creation, and provides convenience
    methods for common graph operations.

    Usage:
        client = Neo4jClient()
        await client.connect()

        async with client.session() as session:
            result = await session.run("MATCH (n) RETURN count(n)")
            record = await result.single()

        await client.close()
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        """Initialize the Neo4j async driver with connection pooling."""
        try:
            self._driver = AsyncGraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(
                    self.settings.neo4j_user,
                    self.settings.neo4j_password.get_secret_value(),
                ),
                max_connection_pool_size=self.settings.neo4j_max_connection_pool_size,
                connection_timeout=10,
                max_transaction_retry_time=30,
            )
            # Verify connectivity
            await self._driver.verify_connectivity()
            logger.info("Neo4j connection established: %s", self.settings.neo4j_uri)
        except ServiceUnavailable as exc:
            raise GraphDBError(f"Cannot connect to Neo4j: {exc}") from exc

    async def close(self) -> None:
        """Close the Neo4j driver and release all connections."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("Neo4j connection closed")

    @asynccontextmanager
    async def session(self, database: str | None = None) -> AsyncGenerator[AsyncSession, None]:
        """Provide an async Neo4j session within a context manager."""
        if not self._driver:
            raise GraphDBError("Neo4j driver not initialized — call connect() first")

        db = database or self.settings.neo4j_database
        session = self._driver.session(database=db)
        try:
            yield session
        finally:
            await session.close()

    async def health_check(self) -> bool:
        """Check if Neo4j is reachable and responsive."""
        try:
            if self._driver:
                await self._driver.verify_connectivity()
                return True
        except (ServiceUnavailable, SessionExpired):
            pass
        return False

    # ── Convenience Query Methods ────────────────────────────────────────

    async def execute_read(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a read transaction and return results as dicts."""
        async with self.session() as session:
            result = await session.run(query, parameters or {})
            records = await result.data()
            return records

    async def execute_write(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a write transaction and return results as dicts."""
        async with self.session() as session:

            async def _write_tx(tx: AsyncTransaction) -> list[dict[str, Any]]:
                result = await tx.run(query, parameters or {})
                return await result.data()

            return await session.execute_write(_write_tx)

    async def execute_batch(
        self,
        queries: list[tuple[str, dict[str, Any] | None]],
    ) -> list[list[dict[str, Any]]]:
        """Execute multiple queries in a single write transaction."""
        results: list[list[dict[str, Any]]] = []

        async with self.session() as session:

            async def _batch_tx(tx: AsyncTransaction) -> None:
                for query, params in queries:
                    result = await tx.run(query, params or {})
                    records = await result.data()
                    results.append(records)

            await session.execute_write(_batch_tx)

        return results

    # ── Schema Initialization ────────────────────────────────────────────

    async def initialize_schema(self) -> None:
        """
        Create indexes and constraints for the 5-layer Network Digital Map.

        Layers:
          1. PhysicalDevice — switches, routers
          2. Server — compute servers connected to leaf switches
          3. VirtualNetwork — Bridge Domains, VRFs, VNIs
          4. VM — virtual machines
          5. Service — application services / tenants
        """
        constraints_and_indexes = [
            # Layer 1: Physical Device
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:PhysicalDevice) REQUIRE d.id IS UNIQUE",
            "CREATE INDEX IF NOT EXISTS FOR (d:PhysicalDevice) ON (d.hostname)",
            "CREATE INDEX IF NOT EXISTS FOR (d:PhysicalDevice) ON (d.management_ip)",
            "CREATE INDEX IF NOT EXISTS FOR (d:PhysicalDevice) ON (d.esn)",
            "CREATE INDEX IF NOT EXISTS FOR (d:PhysicalDevice) ON (d.role)",

            # Layer 1: Interface
            "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Interface) REQUIRE i.id IS UNIQUE",
            "CREATE INDEX IF NOT EXISTS FOR (i:Interface) ON (i.name)",

            # Layer 1: Link
            "CREATE INDEX IF NOT EXISTS FOR ()-[l:CONNECTED_TO]-() ON (l.status)",

            # Layer 2: Server
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Server) REQUIRE s.id IS UNIQUE",
            "CREATE INDEX IF NOT EXISTS FOR (s:Server) ON (s.hostname)",

            # Layer 3: Virtual Network
            "CREATE CONSTRAINT IF NOT EXISTS FOR (vn:VirtualNetwork) REQUIRE vn.id IS UNIQUE",
            "CREATE INDEX IF NOT EXISTS FOR (vn:VirtualNetwork) ON (vn.vni)",
            "CREATE INDEX IF NOT EXISTS FOR (vn:VirtualNetwork) ON (vn.bd_id)",
            "CREATE INDEX IF NOT EXISTS FOR (vn:VirtualNetwork) ON (vn.vrf_name)",

            # Layer 4: VM
            "CREATE CONSTRAINT IF NOT EXISTS FOR (vm:VM) REQUIRE vm.id IS UNIQUE",
            "CREATE INDEX IF NOT EXISTS FOR (vm:VM) ON (vm.name)",

            # Layer 5: Service
            "CREATE CONSTRAINT IF NOT EXISTS FOR (svc:Service) REQUIRE svc.id IS UNIQUE",
            "CREATE INDEX IF NOT EXISTS FOR (svc:Service) ON (svc.name)",
            "CREATE INDEX IF NOT EXISTS FOR (svc:Service) ON (svc.tenant_id)",

            # Tenant
            "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Tenant) REQUIRE t.id IS UNIQUE",
        ]

        async with self.session() as session:
            for statement in constraints_and_indexes:
                try:
                    await session.run(statement)
                except Exception as exc:
                    logger.warning("Schema statement failed (may already exist): %s — %s", statement, exc)

        logger.info("Neo4j schema initialized with %d constraints/indexes", len(constraints_and_indexes))


# ── Module-level singleton ───────────────────────────────────────────────────

_client: Neo4jClient | None = None


async def get_graph_client() -> Neo4jClient:
    """Get or create the global Neo4j client singleton."""
    global _client
    if _client is None:
        _client = Neo4jClient()
        await _client.connect()
        await _client.initialize_schema()
    return _client


async def close_graph_client() -> None:
    """Close the global Neo4j client."""
    global _client
    if _client:
        await _client.close()
        _client = None

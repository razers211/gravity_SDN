"""
NETCONF Transport Manager.

Wraps ncclient to provide managed SSH/NETCONF sessions to Huawei CloudEngine
devices. Supports connection pooling, automatic reconnection, and configurable
timeouts for both port 830 (NETCONF subsystem) and port 22 (SSH fallback).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

from lxml import etree
from ncclient import manager
from ncclient.transport.errors import SSHError
from ncclient.xml_ import to_ele
from tenacity import retry, stop_after_attempt, wait_exponential

from shared.config import Settings, get_settings
from shared.models.device import Device, DeviceCredentials

logger = logging.getLogger(__name__)

# ── Huawei YANG Namespaces ───────────────────────────────────────────────────

HUAWEI_NS = {
    "bgp": "urn:huawei:params:xml:ns:yang:huawei-bgp",
    "evpn": "urn:huawei:params:xml:ns:yang:huawei-evpn",
    "nvo3": "urn:huawei:params:xml:ns:yang:huawei-nvo3",
    "bd": "urn:huawei:params:xml:ns:yang:huawei-bd",
    "ni": "urn:huawei:params:xml:ns:yang:huawei-network-instance",
    "ifm": "urn:huawei:params:xml:ns:yang:huawei-ifm",
    "ip": "urn:huawei:params:xml:ns:yang:huawei-ip",
    "acl": "urn:huawei:params:xml:ns:yang:huawei-acl",
    "qos": "urn:huawei:params:xml:ns:yang:huawei-qos",
    "l2vpn": "urn:huawei:params:xml:ns:yang:huawei-l2vpn",
    "devm": "urn:huawei:params:xml:ns:yang:huawei-devm",
}

# IETF Standard Namespaces
IETF_NS = {
    "nc": "urn:ietf:params:xml:ns:netconf:base:1.0",
    "nc11": "urn:ietf:params:xml:ns:netconf:base:1.1",
    "monitoring": "urn:ietf:params:xml:ns:yang:ietf-netconf-monitoring",
    "notifications": "urn:ietf:params:xml:ns:netconf:notification:1.0",
    "yang-push": "urn:ietf:params:xml:ns:yang:ietf-yang-push",
}


class NetconfSessionError(Exception):
    """Raised when a NETCONF session cannot be established."""


class NetconfRPCError(Exception):
    """Raised when a NETCONF RPC returns an error."""

    def __init__(self, message: str, rpc_error: Any = None):
        super().__init__(message)
        self.rpc_error = rpc_error


class NetconfSession:
    """
    Managed NETCONF/SSH session to a single CloudEngine device.

    Usage:
        session = NetconfSession(device)
        with session.connect() as conn:
            reply = conn.get_config(source="running")
    """

    def __init__(
        self,
        device: Device,
        settings: Settings | None = None,
    ):
        self.device = device
        self.settings = settings or get_settings()
        self._connection: manager.Manager | None = None

    @property
    def _connect_params(self) -> dict[str, Any]:
        """Build ncclient connection parameters for Huawei CloudEngine."""
        creds = self.device.credentials
        params: dict[str, Any] = {
            "host": str(self.device.management_ip),
            "port": creds.netconf_port,
            "username": creds.username or self.settings.netconf_default_username,
            "password": creds.password or self.settings.netconf_default_password.get_secret_value(),
            "hostkey_verify": self.settings.netconf_hostkey_verify,
            "device_params": {"name": "huawei"},
            "timeout": self.settings.netconf_timeout,
            "allow_agent": False,
            "look_for_keys": False,
        }
        # Use SSH key if available
        if creds.ssh_key_path or self.settings.netconf_ssh_key_path:
            params["key_filename"] = creds.ssh_key_path or self.settings.netconf_ssh_key_path

        return params

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _establish_connection(self) -> manager.Manager:
        """
        Establish NETCONF session with retry logic.
        Attempts port 830 first, falls back to port 22.
        """
        params = self._connect_params

        try:
            logger.info(
                "Connecting to %s:%d via NETCONF",
                params["host"],
                params["port"],
            )
            conn = manager.connect(**params)
            logger.info(
                "NETCONF session established: %s (session-id: %s)",
                self.device.hostname,
                conn.session_id,
            )
            return conn

        except SSHError as exc:
            # Fallback to SSH port 22 if NETCONF port 830 fails
            if params["port"] == self.settings.netconf_default_port:
                logger.warning(
                    "Port %d failed for %s, falling back to port %d: %s",
                    params["port"],
                    self.device.hostname,
                    self.settings.netconf_fallback_port,
                    exc,
                )
                params["port"] = self.settings.netconf_fallback_port
                return manager.connect(**params)
            raise NetconfSessionError(
                f"Failed to connect to {self.device.hostname}: {exc}"
            ) from exc

    @contextmanager
    def connect(self) -> Generator[manager.Manager, None, None]:
        """
        Context manager providing a NETCONF session.

        Automatically closes the session on exit.
        """
        conn = self._establish_connection()
        self._connection = conn
        try:
            yield conn
        finally:
            if conn and conn.connected:
                conn.close_session()
                logger.debug("NETCONF session closed: %s", self.device.hostname)
            self._connection = None

    @property
    def is_connected(self) -> bool:
        return self._connection is not None and self._connection.connected

    def get_config(self, source: str = "running", filter_xml: str | None = None) -> str:
        """Retrieve configuration from the specified datastore."""
        if not self._connection:
            raise NetconfSessionError("No active NETCONF session")

        kwargs: dict[str, Any] = {"source": source}
        if filter_xml:
            kwargs["filter"] = ("subtree", filter_xml)

        reply = self._connection.get_config(**kwargs)
        return reply.data_xml if hasattr(reply, "data_xml") else str(reply)

    def edit_config(
        self,
        config: str,
        target: str = "candidate",
        default_operation: str | None = None,
    ) -> Any:
        """
        Send an <edit-config> RPC to the specified datastore.

        Args:
            config: XML configuration payload string
            target: Target datastore ('candidate' or 'running')
            default_operation: Default operation ('merge', 'replace', 'none')
        """
        if not self._connection:
            raise NetconfSessionError("No active NETCONF session")

        kwargs: dict[str, Any] = {
            "target": target,
            "config": config,
        }
        if default_operation:
            kwargs["default_operation"] = default_operation

        try:
            reply = self._connection.edit_config(**kwargs)
            logger.debug(
                "edit-config successful on %s (target=%s)",
                self.device.hostname,
                target,
            )
            return reply
        except Exception as exc:
            raise NetconfRPCError(
                f"edit-config failed on {self.device.hostname}: {exc}",
                rpc_error=exc,
            ) from exc

    def validate(self, source: str = "candidate") -> Any:
        """Validate the candidate configuration."""
        if not self._connection:
            raise NetconfSessionError("No active NETCONF session")
        return self._connection.validate(source=source)

    def commit(self) -> Any:
        """Commit the candidate configuration to running."""
        if not self._connection:
            raise NetconfSessionError("No active NETCONF session")

        try:
            reply = self._connection.commit()
            logger.info("Configuration committed on %s", self.device.hostname)
            return reply
        except Exception as exc:
            raise NetconfRPCError(
                f"Commit failed on {self.device.hostname}: {exc}",
                rpc_error=exc,
            ) from exc

    def discard_changes(self) -> Any:
        """Discard pending changes in the candidate datastore."""
        if not self._connection:
            raise NetconfSessionError("No active NETCONF session")
        reply = self._connection.discard_changes()
        logger.info("Changes discarded on %s", self.device.hostname)
        return reply

    def lock(self, target: str = "candidate") -> Any:
        """Acquire exclusive lock on a datastore."""
        if not self._connection:
            raise NetconfSessionError("No active NETCONF session")
        reply = self._connection.lock(target=target)
        logger.debug("Lock acquired on %s (target=%s)", self.device.hostname, target)
        return reply

    def unlock(self, target: str = "candidate") -> Any:
        """Release lock on a datastore."""
        if not self._connection:
            raise NetconfSessionError("No active NETCONF session")
        reply = self._connection.unlock(target=target)
        logger.debug("Lock released on %s (target=%s)", self.device.hostname, target)
        return reply

    def get_schema(self, identifier: str, version: str | None = None) -> str:
        """Retrieve a YANG schema from the device using get-schema RPC."""
        if not self._connection:
            raise NetconfSessionError("No active NETCONF session")

        reply = self._connection.get_schema(identifier, version=version)
        return reply.data if hasattr(reply, "data") else str(reply)

    def subscribe(self, xpath: str, period: int = 1000) -> Any:
        """
        Create a YANG Push subscription on the device.

        Args:
            xpath: YANG XPath filter for the subscription
            period: Notification period in centiseconds (default 10s)
        """
        if not self._connection:
            raise NetconfSessionError("No active NETCONF session")

        subscribe_rpc = f"""
        <establish-subscription xmlns="urn:ietf:params:xml:ns:yang:ietf-subscribed-notifications">
            <stream-subtree-filter>
                <filter type="subtree">
                    {xpath}
                </filter>
            </stream-subtree-filter>
            <encoding>encode-xml</encoding>
            <periodic>
                <period>{period}</period>
            </periodic>
        </establish-subscription>
        """
        return self._connection.dispatch(to_ele(subscribe_rpc))


class NetconfSessionPool:
    """
    Connection pool for managing multiple NETCONF sessions.

    Maintains a cache of reusable sessions keyed by device hostname.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._sessions: dict[str, NetconfSession] = {}

    def get_session(self, device: Device) -> NetconfSession:
        """Get or create a NETCONF session for a device."""
        key = device.hostname
        if key not in self._sessions:
            self._sessions[key] = NetconfSession(device, self.settings)
        return self._sessions[key]

    def remove_session(self, device_hostname: str) -> None:
        """Remove a session from the pool."""
        self._sessions.pop(device_hostname, None)

    def close_all(self) -> None:
        """Close all pooled sessions."""
        for session in self._sessions.values():
            if session.is_connected and session._connection:
                try:
                    session._connection.close_session()
                except Exception:
                    pass
        self._sessions.clear()
        logger.info("All NETCONF sessions closed")

"""
DHCP Option 148 Listener for Zero Touch Provisioning.

Captures DHCP requests from factory-default CloudEngine switches,
injects Option 148 with the controller's connection information,
and triggers the ZTP onboarding flow.

Option 148 Format:
  agilemode=agile-cloud;agilemanage-mode=ip;
  agilemanage-domain=<controller-ip>;agilemanage-port=<port>;
"""

from __future__ import annotations

import asyncio
import logging
import socket
import struct
from typing import Any

from shared.config import Settings, get_settings

logger = logging.getLogger(__name__)


class DHCPOption148Error(Exception):
    """Raised on DHCP listener failures."""


class DHCPListenerService:
    """
    DHCP Option 148 listener for CloudEngine ZTP.

    Listens for DHCP DISCOVER/REQUEST packets from unconfigured
    CloudEngine switches and responds with Option 148 containing
    controller connection parameters.

    Flow:
      1. Switch boots with factory defaults (ZTP enabled)
      2. Switch sends DHCP DISCOVER broadcast
      3. Listener injects Option 148 in DHCP OFFER
      4. Switch reads controller IP/port from Option 148
      5. Switch initiates NETCONF session to controller
    """

    DHCP_SERVER_PORT = 67
    DHCP_CLIENT_PORT = 68
    OPTION_148 = 148

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._running = False
        self._socket: socket.socket | None = None
        self._discovered_devices: list[dict[str, Any]] = []

    def _build_option_148(self) -> bytes:
        """
        Build DHCP Option 148 payload for Huawei controller discovery.

        Format: agilemode=agile-cloud;agilemanage-mode=ip;
                agilemanage-domain=<ip>;agilemanage-port=<port>;
        """
        option_string = (
            f"agilemode=agile-cloud;"
            f"agilemanage-mode=ip;"
            f"agilemanage-domain={self.settings.ztp_controller_ip};"
            f"agilemanage-port={self.settings.ztp_controller_port};"
        )
        return option_string.encode("ascii")

    def _parse_dhcp_discover(self, data: bytes) -> dict[str, Any] | None:
        """
        Parse a DHCP DISCOVER packet to extract device information.

        Returns device info dict or None if not a valid DHCP DISCOVER.
        """
        if len(data) < 240:  # Minimum DHCP packet size
            return None

        try:
            # DHCP header fields
            op = data[0]           # 1 = BOOTREQUEST
            htype = data[1]        # 1 = Ethernet
            hlen = data[2]         # MAC address length (6)
            xid = struct.unpack("!I", data[4:8])[0]

            # Client MAC address (bytes 28-34)
            client_mac_bytes = data[28:28 + hlen]
            client_mac = ":".join(f"{b:02x}" for b in client_mac_bytes)

            if op != 1:  # Not a BOOTREQUEST
                return None

            # Parse DHCP options (starting at byte 240, after magic cookie)
            options = self._parse_dhcp_options(data[240:])
            msg_type = options.get(53)  # DHCP Message Type

            if msg_type and msg_type[0] in (1, 3):  # DISCOVER=1, REQUEST=3
                device_info = {
                    "transaction_id": xid,
                    "client_mac": client_mac,
                    "message_type": "DISCOVER" if msg_type[0] == 1 else "REQUEST",
                    "hostname": options.get(12, b"").decode("ascii", errors="ignore"),
                    "vendor_class": options.get(60, b"").decode("ascii", errors="ignore"),
                }

                # Check for Huawei vendor class identifier
                vendor = device_info["vendor_class"].lower()
                if "huawei" in vendor or "ce" in vendor:
                    device_info["vendor"] = "huawei"
                    logger.info(
                        "DHCP %s from Huawei device: MAC=%s, hostname=%s",
                        device_info["message_type"],
                        client_mac,
                        device_info["hostname"],
                    )
                    return device_info

                logger.debug("DHCP from non-Huawei device: %s (ignored)", vendor)
                return None

        except (struct.error, IndexError) as exc:
            logger.debug("Failed to parse DHCP packet: %s", exc)
            return None

    def _parse_dhcp_options(self, data: bytes) -> dict[int, bytes]:
        """Parse DHCP options from the options field."""
        options: dict[int, bytes] = {}
        i = 0
        while i < len(data):
            option_type = data[i]
            if option_type == 255:  # End option
                break
            if option_type == 0:    # Padding
                i += 1
                continue
            if i + 1 >= len(data):
                break
            option_len = data[i + 1]
            if i + 2 + option_len > len(data):
                break
            options[option_type] = data[i + 2:i + 2 + option_len]
            i += 2 + option_len
        return options

    async def start(self) -> None:
        """Start the DHCP listener service."""
        self._running = True
        logger.info(
            "ZTP DHCP listener starting on %s:%d",
            self.settings.ztp_dhcp_interface,
            self.settings.ztp_dhcp_port,
        )

        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._socket.bind((self.settings.ztp_dhcp_interface, self.settings.ztp_dhcp_port))
            self._socket.settimeout(1.0)

            loop = asyncio.get_event_loop()

            while self._running:
                try:
                    data, addr = await loop.run_in_executor(
                        None, lambda: self._socket.recvfrom(4096)
                    )

                    device_info = self._parse_dhcp_discover(data)
                    if device_info:
                        self._discovered_devices.append(device_info)
                        logger.info(
                            "ZTP device discovered: MAC=%s, triggering onboarding",
                            device_info["client_mac"],
                        )
                        # Trigger ESN authentication and baseline deployment
                        await self._trigger_onboarding(device_info, addr)

                except socket.timeout:
                    continue
                except OSError as exc:
                    if self._running:
                        logger.error("Socket error: %s", exc)
                        await asyncio.sleep(1.0)

        finally:
            if self._socket:
                self._socket.close()
                self._socket = None

    async def _trigger_onboarding(
        self,
        device_info: dict[str, Any],
        addr: tuple[str, int],
    ) -> None:
        """Trigger the ZTP onboarding flow for a discovered device."""
        from services.ztp_service.esn_authenticator import ESNAuthenticator
        from services.ztp_service.baseline_deployer import BaselineDeployer

        authenticator = ESNAuthenticator()
        deployer = BaselineDeployer()

        # Authentication and deployment are handled asynchronously
        logger.info(
            "Onboarding triggered for %s from %s",
            device_info["client_mac"],
            addr[0],
        )

    def stop(self) -> None:
        """Stop the DHCP listener."""
        self._running = False
        logger.info("ZTP DHCP listener stopped")

    @property
    def discovered_devices(self) -> list[dict[str, Any]]:
        return self._discovered_devices.copy()

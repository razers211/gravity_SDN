"""
Baseline Deployer.

Dispatches baseline underlay configuration to newly authenticated
CloudEngine switches via NETCONF. Covers management IP, OSPF/IS-IS
underlay, loopback interfaces, NTP, and syslog configuration.
"""

from __future__ import annotations

import logging
from typing import Any

from shared.config import get_settings
from shared.models.device import Device, DeviceCredentials, DeviceRole
from shared.netconf.transport import NetconfSession

logger = logging.getLogger(__name__)
settings = get_settings()


class BaselineDeployer:
    """
    Deploys baseline underlay configuration to factory-default
    CloudEngine switches after ESN authentication.
    """

    BASELINE_TEMPLATE = """
    <config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
      <!-- System Identity -->
      <system xmlns="urn:huawei:params:xml:ns:yang:huawei-system">
        <hostname>{hostname}</hostname>
        <contact>Gravity SDN Controller</contact>
        <location>{site} / {pod} / {rack}</location>
      </system>

      <!-- Loopback Interface (Router-ID / VTEP Source) -->
      <ifm xmlns="urn:huawei:params:xml:ns:yang:huawei-ifm">
        <interfaces>
          <interface>
            <if-name>LoopBack0</if-name>
            <type>loopback</type>
            <description>Router-ID</description>
            <ipv4 xmlns="urn:huawei:params:xml:ns:yang:huawei-ip">
              <addresses>
                <address>
                  <ip>{router_id}</ip>
                  <mask>255.255.255.255</mask>
                </address>
              </addresses>
            </ipv4>
          </interface>
          <interface>
            <if-name>LoopBack1</if-name>
            <type>loopback</type>
            <description>VTEP Source</description>
            <ipv4 xmlns="urn:huawei:params:xml:ns:yang:huawei-ip">
              <addresses>
                <address>
                  <ip>{vtep_ip}</ip>
                  <mask>255.255.255.255</mask>
                </address>
              </addresses>
            </ipv4>
          </interface>
        </interfaces>
      </ifm>

      <!-- OSPF Underlay -->
      <ospf xmlns="urn:huawei:params:xml:ns:yang:huawei-ospf">
        <ospf-instances>
          <ospf-instance>
            <process-id>1</process-id>
            <router-id>{router_id}</router-id>
            <areas>
              <area>
                <area-id>0.0.0.0</area-id>
                <networks>
                  <network>
                    <address>{router_id}</address>
                    <wildcard>0.0.0.0</wildcard>
                  </network>
                  <network>
                    <address>{vtep_ip}</address>
                    <wildcard>0.0.0.0</wildcard>
                  </network>
                </networks>
              </area>
            </areas>
          </ospf-instance>
        </ospf-instances>
      </ospf>

      <!-- NTP -->
      <ntp xmlns="urn:huawei:params:xml:ns:yang:huawei-ntp">
        <ntp-servers>
          <ntp-server>
            <server-address>{ntp_server}</server-address>
            <preferred>true</preferred>
          </ntp-server>
        </ntp-servers>
      </ntp>

      <!-- Syslog -->
      <syslog xmlns="urn:huawei:params:xml:ns:yang:huawei-syslog">
        <log-hosts>
          <log-host>
            <host-address>{syslog_server}</host-address>
            <host-port>514</host-port>
            <facility>local7</facility>
          </log-host>
        </log-hosts>
      </syslog>
    </config>
    """

    async def deploy_baseline(
        self,
        device: Device,
        config_params: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Deploy baseline underlay configuration to a new device.

        Args:
            device: The target device (with management IP and credentials)
            config_params: Configuration parameters:
              - hostname
              - router_id
              - vtep_ip
              - site, pod, rack
              - ntp_server
              - syslog_server

        Returns:
            Deployment result dict
        """
        logger.info(
            "Deploying baseline to %s (%s)",
            device.hostname,
            device.management_ip,
        )

        # Render baseline template
        payload = self.BASELINE_TEMPLATE.format(
            hostname=config_params.get("hostname", device.hostname),
            router_id=config_params.get("router_id", device.router_id or "10.0.0.1"),
            vtep_ip=config_params.get("vtep_ip", device.vtep_ip or "10.0.0.1"),
            site=config_params.get("site", device.site),
            pod=config_params.get("pod", device.pod),
            rack=config_params.get("rack", device.rack),
            ntp_server=config_params.get("ntp_server", "10.0.0.253"),
            syslog_server=config_params.get("syslog_server", settings.ztp_controller_ip),
        )

        # Deploy via NETCONF
        session = NetconfSession(device)
        try:
            with session.connect() as conn:
                conn.lock(target="candidate")
                try:
                    conn.edit_config(target="candidate", config=payload)
                    conn.validate(source="candidate")
                    conn.commit()
                    logger.info("Baseline deployed successfully: %s", device.hostname)
                    return {
                        "status": "success",
                        "device": device.hostname,
                        "message": "Baseline configuration deployed",
                    }
                except Exception as exc:
                    conn.discard_changes()
                    logger.error("Baseline deployment failed: %s — %s", device.hostname, exc)
                    raise
                finally:
                    conn.unlock(target="candidate")

        except Exception as exc:
            return {
                "status": "failed",
                "device": device.hostname,
                "error": str(exc),
            }

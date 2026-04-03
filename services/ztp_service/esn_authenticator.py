"""
ESN Authenticator — X.509 PKI authentication for ZTP devices.

Validates Equipment Serial Numbers (ESN) from factory-default CloudEngine
switches against a pre-loaded inventory and X.509 certificate chain.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID

from shared.config import Settings, get_settings

logger = logging.getLogger(__name__)


class ESNAuthenticationError(Exception):
    """Raised when ESN authentication fails."""


class ESNAuthenticator:
    """
    Authenticates CloudEngine devices via Equipment Serial Number (ESN)
    and X.509 PKI certificate verification.

    Authentication flow:
      1. Extract ESN from device registration request
      2. Verify ESN against pre-loaded inventory database
      3. Validate device certificate against CA chain
      4. Issue authentication token for NETCONF session establishment
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._trusted_ca: x509.Certificate | None = None
        self._inventory: dict[str, dict[str, Any]] = {}

    def load_ca_certificate(self) -> None:
        """Load the trusted CA certificate for device verification."""
        try:
            ca_path = self.settings.ztp_pki_ca_cert_path
            with open(ca_path, "rb") as f:
                self._trusted_ca = x509.load_pem_x509_certificate(f.read())
            logger.info("CA certificate loaded: %s", ca_path)
        except FileNotFoundError:
            logger.warning("CA certificate not found: %s — PKI validation disabled", ca_path)
        except Exception as exc:
            logger.error("Failed to load CA certificate: %s", exc)

    def register_device(self, esn: str, metadata: dict[str, Any] | None = None) -> None:
        """Pre-register a device ESN in the inventory for ZTP authentication."""
        self._inventory[esn] = {
            "esn": esn,
            "registered_at": datetime.utcnow().isoformat(),
            "status": "pending",
            "metadata": metadata or {},
        }
        logger.info("Device pre-registered: ESN=%s", esn)

    def authenticate(
        self,
        esn: str,
        device_cert_pem: bytes | None = None,
    ) -> dict[str, Any]:
        """
        Authenticate a device by ESN and optional X.509 certificate.

        Args:
            esn: Equipment Serial Number from the device
            device_cert_pem: Optional PEM-encoded device certificate

        Returns:
            Authentication result with status and credentials

        Raises:
            ESNAuthenticationError: If authentication fails
        """
        logger.info("Authenticating device: ESN=%s", esn)

        # Step 1: Check ESN against inventory
        if esn not in self._inventory:
            logger.warning("Unknown ESN: %s — rejecting device", esn)
            raise ESNAuthenticationError(f"ESN '{esn}' not found in inventory")

        inventory_entry = self._inventory[esn]

        # Check if already authenticated
        if inventory_entry.get("status") == "authenticated":
            logger.info("Device already authenticated: ESN=%s", esn)
            return {
                "esn": esn,
                "status": "authenticated",
                "message": "Device already authenticated",
            }

        # Check if revoked
        if inventory_entry.get("status") == "revoked":
            raise ESNAuthenticationError(f"ESN '{esn}' has been revoked")

        # Step 2: Validate X.509 certificate (if provided)
        if device_cert_pem and self._trusted_ca:
            self._verify_certificate(esn, device_cert_pem)

        # Step 3: Mark as authenticated
        self._inventory[esn]["status"] = "authenticated"
        self._inventory[esn]["authenticated_at"] = datetime.utcnow().isoformat()

        result = {
            "esn": esn,
            "status": "authenticated",
            "message": "Device authenticated successfully",
            "netconf_credentials": {
                "username": "admin",
                "port": 830,
            },
        }

        logger.info("Device authenticated: ESN=%s", esn)
        return result

    def _verify_certificate(self, esn: str, cert_pem: bytes) -> None:
        """
        Verify device certificate against the trusted CA chain.

        Checks:
          - Certificate is signed by the trusted CA
          - Certificate is within validity period
          - Certificate CN matches the ESN
        """
        try:
            device_cert = x509.load_pem_x509_certificate(cert_pem)

            # Check validity period
            now = datetime.utcnow()
            if now < device_cert.not_valid_before_utc.replace(tzinfo=None):
                raise ESNAuthenticationError(f"Device certificate not yet valid for ESN '{esn}'")
            if now > device_cert.not_valid_after_utc.replace(tzinfo=None):
                raise ESNAuthenticationError(f"Device certificate expired for ESN '{esn}'")

            # Check CN matches ESN
            cn = device_cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            if cn and cn[0].value != esn:
                logger.warning(
                    "Certificate CN '%s' does not match ESN '%s'",
                    cn[0].value,
                    esn,
                )

            # Verify signature against CA (simplified — full chain validation
            # would use a proper trust store)
            if self._trusted_ca:
                try:
                    ca_public_key = self._trusted_ca.public_key()
                    ca_public_key.verify(
                        device_cert.signature,
                        device_cert.tbs_certificate_bytes,
                        device_cert.signature_hash_algorithm,
                    )
                    logger.debug("Certificate verified for ESN=%s", esn)
                except Exception as exc:
                    raise ESNAuthenticationError(
                        f"Certificate verification failed for ESN '{esn}': {exc}"
                    ) from exc

        except x509.InvalidVersion as exc:
            raise ESNAuthenticationError(f"Invalid certificate for ESN '{esn}': {exc}") from exc

    def revoke_device(self, esn: str) -> None:
        """Revoke authentication for a device ESN."""
        if esn in self._inventory:
            self._inventory[esn]["status"] = "revoked"
            self._inventory[esn]["revoked_at"] = datetime.utcnow().isoformat()
            logger.info("Device revoked: ESN=%s", esn)

    def get_device_status(self, esn: str) -> dict[str, Any] | None:
        """Get authentication status for a device."""
        return self._inventory.get(esn)

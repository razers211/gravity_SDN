"""
Gravity SDN — Centralized Configuration via Pydantic Settings.

All configuration is loaded from environment variables with sensible defaults
for local development. In production, inject via Kubernetes ConfigMaps/Secrets.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Service Identity ─────────────────────────────────────────────────────
    service_name: str = Field(default="gravity-sdn", description="Microservice identifier")
    service_port: int = Field(default=8000, description="HTTP listen port")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    environment: Literal["development", "staging", "production"] = "development"

    # ── Neo4j Graph Database ─────────────────────────────────────────────────
    neo4j_uri: str = Field(default="bolt://localhost:7687", description="Neo4j Bolt URI")
    neo4j_user: str = Field(default="neo4j")
    neo4j_password: SecretStr = Field(default=SecretStr("gravity_sdn_dev"))
    neo4j_database: str = Field(default="neo4j")
    neo4j_max_connection_pool_size: int = Field(default=50)

    # ── Apache Kafka ─────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str = Field(default="localhost:9092")
    kafka_group_id: str = Field(default="gravity-sdn")
    kafka_auto_offset_reset: Literal["earliest", "latest"] = "latest"
    kafka_telemetry_topic: str = Field(default="telemetry.yang-push")
    kafka_grpc_topic: str = Field(default="telemetry.grpc")
    kafka_syslog_topic: str = Field(default="telemetry.syslog")
    kafka_audit_topic: str = Field(default="audit.provisioning")
    kafka_alarm_topic: str = Field(default="alarms.active")

    # ── PostgreSQL ───────────────────────────────────────────────────────────
    postgres_dsn: str = Field(
        default="postgresql+asyncpg://gravity:gravity_sdn_dev@localhost:5432/gravity_sdn",
        description="SQLAlchemy async DSN",
    )
    postgres_pool_size: int = Field(default=20)
    postgres_max_overflow: int = Field(default=10)

    # ── Redis ────────────────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_lock_timeout: int = Field(default=30, description="Distributed lock TTL in seconds")

    # ── JWT Authentication ───────────────────────────────────────────────────
    jwt_secret_key: SecretStr = Field(default=SecretStr("dev-secret-change-in-production"))
    jwt_algorithm: str = Field(default="HS256")
    jwt_expiry_minutes: int = Field(default=60)

    # ── NETCONF / SSH ────────────────────────────────────────────────────────
    netconf_default_port: int = Field(default=830, description="NETCONF over SSH primary port")
    netconf_fallback_port: int = Field(default=22, description="SSH fallback port")
    netconf_timeout: int = Field(default=30, description="RPC timeout in seconds")
    netconf_ssh_key_path: str | None = Field(default=None, description="Path to SSH private key")
    netconf_default_username: str = Field(default="admin")
    netconf_default_password: SecretStr = Field(default=SecretStr("Admin@123"))
    netconf_hostkey_verify: bool = Field(default=False, description="Verify SSH host keys")

    # ── ZTP Service ──────────────────────────────────────────────────────────
    ztp_dhcp_interface: str = Field(default="0.0.0.0", description="DHCP listener bind address")
    ztp_dhcp_port: int = Field(default=67)
    ztp_controller_ip: str = Field(default="10.0.0.1", description="Controller IP for Option 148")
    ztp_controller_port: int = Field(default=10020)
    ztp_pki_ca_cert_path: str = Field(default="certs/ca.pem")
    ztp_pki_cert_path: str = Field(default="certs/server.pem")
    ztp_pki_key_path: str = Field(default="certs/server.key")

    # ── gRPC Telemetry Collector ─────────────────────────────────────────────
    grpc_listen_address: str = Field(default="0.0.0.0:57400")
    grpc_max_workers: int = Field(default=10)

    # ── Inter-Service URLs ───────────────────────────────────────────────────
    intent_engine_url: str = Field(default="http://localhost:8001")
    provisioning_engine_url: str = Field(default="http://localhost:8002")
    ztp_service_url: str = Field(default="http://localhost:8003")
    oam_service_url: str = Field(default="http://localhost:8004")
    resource_manager_url: str = Field(default="http://localhost:8005")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton Settings instance."""
    return Settings()

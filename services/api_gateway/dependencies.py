"""
FastAPI dependency injection for the API Gateway.
"""

from __future__ import annotations

import httpx

from shared.config import get_settings

settings = get_settings()


async def get_intent_client() -> httpx.AsyncClient:
    """HTTP client for the Intent Engine service."""
    return httpx.AsyncClient(base_url=settings.intent_engine_url, timeout=30.0)


async def get_provisioning_client() -> httpx.AsyncClient:
    """HTTP client for the Provisioning Engine service."""
    return httpx.AsyncClient(base_url=settings.provisioning_engine_url, timeout=60.0)


async def get_ztp_client() -> httpx.AsyncClient:
    """HTTP client for the ZTP service."""
    return httpx.AsyncClient(base_url=settings.ztp_service_url, timeout=30.0)


async def get_oam_client() -> httpx.AsyncClient:
    """HTTP client for the O&M service."""
    return httpx.AsyncClient(base_url=settings.oam_service_url, timeout=30.0)


async def get_resource_client() -> httpx.AsyncClient:
    """HTTP client for the Resource Manager service."""
    return httpx.AsyncClient(base_url=settings.resource_manager_url, timeout=10.0)

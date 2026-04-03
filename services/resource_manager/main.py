"""
Resource Manager Service — Service Entry.

Manages network resource allocation:
  - IPAM (IP Address Management)
  - VNI Pool Allocation
  - Route Target / Route Distinguisher Management
"""

from __future__ import annotations

import logging

import structlog
import uvicorn
from fastapi import FastAPI

from shared.config import get_settings

settings = get_settings()
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(settings.log_level)))

app = FastAPI(
    title="Gravity SDN — Resource Manager",
    description="Network Resource Dictionary (IPAM, VNI, RT/RD)",
    version="1.0.0",
)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "resource-manager"}


if __name__ == "__main__":
    uvicorn.run(
        "services.resource_manager.main:app",
        host="0.0.0.0",
        port=int(settings.service_port),
        reload=settings.environment == "development",
    )

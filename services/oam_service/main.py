"""
Intelligent O&M Service — Service Entry.

Implements the "1-3-5" AI Troubleshooting Framework:
  1 minute:  Detect link degradation via telemetry
  3 minutes: Locate impacted tenants/VMs via graph DB
  5 minutes: Rectify via autonomous NETCONF remediation
"""

from __future__ import annotations

import logging

import structlog
import uvicorn
from fastapi import FastAPI

from shared.config import get_settings

settings = get_settings()
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(settings.log_level)))
log = structlog.get_logger()

app = FastAPI(title="Gravity SDN — O&M Service", description="Intelligent Operations & Maintenance (1-3-5 Framework)", version="1.0.0")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "oam-service"}


@app.on_event("startup")
async def startup():
    """Start telemetry consumer and correlation engine on service boot."""
    log.info("O&M service starting — initializing telemetry consumer")


if __name__ == "__main__":
    uvicorn.run("services.oam_service.main:app", host="0.0.0.0", port=int(settings.service_port), reload=settings.environment == "development")

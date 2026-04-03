"""
ZTP & Runbook Orchestration Service — Service Entry.
"""

from __future__ import annotations

import logging

import structlog
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from shared.config import get_settings

settings = get_settings()
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(settings.log_level)))
log = structlog.get_logger()

app = FastAPI(title="Gravity SDN — ZTP Service", description="Zero Touch Provisioning & Runbook Orchestration", version="1.0.0")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "ztp-service"}


if __name__ == "__main__":
    uvicorn.run("services.ztp_service.main:app", host="0.0.0.0", port=int(settings.service_port), reload=settings.environment == "development")

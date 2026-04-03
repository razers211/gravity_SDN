"""
API Gateway — Northbound REST Interface.

Central FastAPI application serving as the unified NBI for external
cloud orchestrators (VMware vCenter, OpenStack Neutron, Kubernetes CNI).

Features:
  - JWT/OAuth2 token authentication
  - Versioned API routing (/api/v1/)
  - CORS middleware for multi-cloud integration
  - Global exception handling and structured logging
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.config import get_settings
from services.api_gateway.routers import (
    intents,
    devices,
    fabrics,
    ztp,
    runbooks,
    telemetry,
    topology,
)

settings = get_settings()

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.getLevelName(settings.log_level)
    ),
)
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown hooks."""
    log.info("api_gateway.startup", service="api-gateway", port=settings.service_port)
    yield
    log.info("api_gateway.shutdown")


app = FastAPI(
    title="Gravity SDN — CloudEngine IDN Automation Platform",
    description=(
        "Northbound REST API for the Level 3+ Autonomous Driving Network controller. "
        "Orchestrates Intent-Driven Networking, NETCONF provisioning, Zero Touch "
        "Provisioning, and AI-driven O&M for Huawei CloudEngine data center fabrics."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {"name": "Intents", "description": "Intent translation, verification, and provisioning"},
        {"name": "Devices", "description": "Device inventory and lifecycle management"},
        {"name": "Fabrics", "description": "Fabric topology and VXLAN overlay management"},
        {"name": "ZTP", "description": "Zero Touch Provisioning and device onboarding"},
        {"name": "Runbooks", "description": "Runbook orchestration and execution"},
        {"name": "Telemetry", "description": "Telemetry monitoring, alarms, and metrics"},
        {"name": "Topology", "description": "Network Digital Map and topology visualization"},
    ],
)

# ── CORS Middleware ──────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global Exception Handler ────────────────────────────────────────────────


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", path=request.url.path, error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred",
            "detail": str(exc) if settings.environment == "development" else None,
        },
    )


# ── Health Check ─────────────────────────────────────────────────────────────


@app.get("/health", tags=["System"])
async def health_check():
    """System health check endpoint."""
    return {
        "status": "healthy",
        "service": "api-gateway",
        "version": "1.0.0",
        "environment": settings.environment,
    }


# ── Register Routers ────────────────────────────────────────────────────────

app.include_router(intents.router, prefix="/api/v1", tags=["Intents"])
app.include_router(devices.router, prefix="/api/v1", tags=["Devices"])
app.include_router(fabrics.router, prefix="/api/v1", tags=["Fabrics"])
app.include_router(ztp.router, prefix="/api/v1", tags=["ZTP"])
app.include_router(runbooks.router, prefix="/api/v1", tags=["Runbooks"])
app.include_router(telemetry.router, prefix="/api/v1", tags=["Telemetry"])
app.include_router(topology.router, prefix="/api/v1", tags=["Topology"])

# ── Static File Integration ─────────────────────────────────────────────────

import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

# Mount the static directory
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'frontend')
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/", tags=["System"])
async def root():
    """Serve the Web GUI."""
    index_path = os.path.join(frontend_dir, 'index.html')
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    # Fallback if frontend is missing
    return {
        "platform": "Gravity SDN — CloudEngine IDN Automation Platform",
        "version": "1.0.0",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


if __name__ == "__main__":
    uvicorn.run(
        "services.api_gateway.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.environment == "development",
    )

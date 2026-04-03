# Gravity SDN — CloudEngine IDN Automation Platform

> **Level 3+ Autonomous Driving Network Controller** for Huawei CloudEngine data center fabrics.

---

## Architecture

```
┌─────────────────────────────┐
│   Cloud Orchestrators       │
│  (vCenter / Neutron / K8s)  │
└─────────────┬───────────────┘
              │ REST (JWT/OAuth2)
┌─────────────▼───────────────┐
│      API Gateway (:8000)    │
│   FastAPI + OpenAPI 3.1     │
└─────────────┬───────────────┘
              │
  ┌───────────┼───────────────┐
  │           │               │
  ▼           ▼               ▼
┌──────┐  ┌──────────┐  ┌─────┐  ┌─────┐  ┌──────────┐
│Intent│  │Provision │  │ ZTP │  │ O&M │  │ Resource │
│Engine│  │ Engine   │  │Svc  │  │ Svc │  │ Manager  │
│:8001 │  │ :8002    │  │:8003│  │:8004│  │ :8005    │
└──┬───┘  └────┬─────┘  └──┬──┘  └──┬──┘  └────┬─────┘
   │          │            │        │           │
   ▼          ▼            ▼        ▼           ▼
┌──────┐  ┌───────┐  ┌────────┐  ┌──────┐  ┌──────┐
│Neo4j │  │Kafka  │  │NETCONF │  │Redis │  │Postgres│
│Graph │  │Bus    │  │SSH/830 │  │Cache │  │Store   │
└──────┘  └───────┘  └────────┘  └──────┘  └──────┘
```

## Quick Start

```bash
# 1. Install dependencies (requires Python 3.11+)
pip install -e ".[dev]"

# 2. Start infrastructure
docker compose up -d

# 3. Run unit tests
pytest tests/ -v

# 4. Start the API Gateway
python -m services.api_gateway.main
# → Swagger UI: http://localhost:8000/docs
```

## Project Structure

```
gravity_SDN/
├── shared/                     # Shared libraries
│   ├── config.py               # Pydantic Settings (env-based)
│   ├── models/                 # Pydantic v2 domain models
│   │   ├── intent.py           #   Tenant, VPC, Subnet, Policy
│   │   ├── device.py           #   Device, Interface, Credentials
│   │   ├── fabric.py           #   BridgeDomain, VRF, VNI
│   │   └── telemetry.py        #   Alarm, Metric, ImpactReport
│   ├── graph/                  # Neo4j client & Cypher queries
│   │   ├── client.py           #   Async Neo4j driver wrapper
│   │   └── queries.py          #   5-layer digital map queries
│   ├── kafka/                  # Kafka producer & consumer
│   │   ├── producer.py         #   JSON message publishing
│   │   └── consumer.py         #   Async multi-topic consumer
│   └── netconf/                # NETCONF/SSH transport
│       ├── transport.py        #   ncclient session wrapper
│       ├── transaction.py      #   ACID multi-device transactions
│       └── xml_templates/      #   Jinja2 XML templates
│           ├── bgp_evpn.xml.j2
│           ├── vxlan_nvo3.xml.j2
│           ├── bridge_domain.xml.j2
│           ├── vrf_instance.xml.j2
│           ├── vbdif_gateway.xml.j2
│           └── route_targets.xml.j2
├── services/                   # Microservices
│   ├── intent_engine/          # Intent Translation & Verification
│   │   ├── main.py             #   FastAPI service
│   │   ├── translator.py       #   Intent → NetworkState graph
│   │   ├── verifier.py         #   Formal verification (5 checks)
│   │   ├── rib_simulator.py    #   Offline RIB/FIB simulator
│   │   └── policy_engine.py    #   Security policy compiler
│   ├── provisioning_engine/    # ACID NETCONF Deployment
│   │   ├── main.py
│   │   ├── orchestrator.py     #   Multi-device transaction orchestration
│   │   ├── payload_builder.py  #   XML assembly from Jinja2 templates
│   │   ├── evpn_provisioner.py #   BGP EVPN automation
│   │   └── vxlan_provisioner.py#   VXLAN distributed gateway
│   ├── ztp_service/            # Zero Touch Provisioning
│   │   ├── main.py
│   │   ├── dhcp_listener.py    #   DHCP Option 148 listener
│   │   ├── esn_authenticator.py#   X.509 PKI device authentication
│   │   ├── baseline_deployer.py#   Underlay baseline config
│   │   └── runbook_engine.py   #   YAML runbook orchestrator
│   ├── oam_service/            # Intelligent O&M (1-3-5)
│   │   ├── main.py
│   │   ├── telemetry_consumer.py#  YANG Push/gRPC/Syslog consumer
│   │   ├── correlator.py       #   1-3-5 troubleshooting pipeline
│   │   ├── impact_analyzer.py  #   Graph-based 5-layer impact analysis
│   │   └── auto_remediation.py #   Autonomous bypass path deployment
│   ├── resource_manager/       # Network Resource Dictionary
│   │   ├── main.py
│   │   ├── ipam.py             #   IP Address Management
│   │   ├── vni_allocator.py    #   VNI pool allocation
│   │   └── rt_rd_manager.py    #   Route Target / Route Distinguisher
│   └── api_gateway/            # Northbound REST API
│       ├── main.py             #   FastAPI + CORS + OpenAPI
│       ├── auth.py             #   JWT/OAuth2 authentication
│       ├── dependencies.py     #   Dependency injection
│       └── routers/            #   Versioned API endpoints
│           ├── intents.py
│           ├── devices.py
│           ├── fabrics.py
│           ├── ztp.py
│           ├── runbooks.py
│           ├── telemetry.py
│           └── topology.py
├── docs/                       # Documentation
│   ├── architecture.md         #   HLA with Mermaid diagrams
│   ├── openapi.yaml            #   OpenAPI 3.1 specification
│   └── yang_payloads/          #   Reference XML payloads
│       ├── bgp_evpn_instance.xml
│       └── distributed_gateway.xml
├── tests/                      # Unit & integration tests
│   ├── conftest.py
│   └── unit/
│       ├── test_intent_translator.py
│       ├── test_verifier.py
│       ├── test_netconf_transaction.py
│       ├── test_payload_builder.py
│       ├── test_correlator.py
│       └── test_resource_manager.py
├── docker-compose.yml          # Infrastructure stack
└── pyproject.toml              # Python project configuration
```

## Key Features

| Feature | Implementation |
|---------|---------------|
| **Intent-Based Networking** | Translate tenant intents → formal verification → NETCONF provisioning |
| **Formal Verification** | Routing loop detection, IP conflict check, VNI uniqueness, RT consistency |
| **ACID NETCONF Transactions** | lock → edit-config → validate → commit across multi-device fabrics |
| **Zero Touch Provisioning** | DHCP Option 148, ESN/X.509 authentication, baseline underlay deployment |
| **1-3-5 Troubleshooting** | 1min detect, 3min locate (graph analysis), 5min rectify (auto-bypass) |
| **5-Layer Digital Map** | Neo4j graph: Physical → Server → VirtualNetwork → VM → Service |
| **Resource Management** | IPAM, VNI pools, RT/RD auto-allocation |
| **YAML Runbooks** | Sequential task execution with retry/skip/abort and variable interpolation |
| **JWT/OAuth2 Security** | Role-based access control (admin, operator, viewer) |

# High-Level Architecture — Gravity SDN

## CloudEngine IDN Automation Platform

> **Level 3+ Autonomous Driving Network Controller** for Huawei CloudEngine data-center fabrics.

---

## Architecture Overview

```mermaid
graph TB
    subgraph "External Orchestrators"
        VC["VMware vCenter"]
        OS["OpenStack Neutron"]
        K8["Kubernetes CNI"]
    end

    subgraph "Northbound Interface (NBI)"
        GW["REST API Gateway<br/>FastAPI + JWT/OAuth2<br/>:8000"]
        SWAGGER["OpenAPI 3.1 Spec"]
    end

    subgraph "Core Controller Services"
        direction LR
        IE["Intent Engine<br/>:8001"]
        PE["Provisioning Engine<br/>:8002"]
        ZTP["ZTP Service<br/>:8003"]
        OAM["O&M Service<br/>:8004"]
        RM["Resource Manager<br/>:8005"]
    end

    subgraph "Data & Messaging Layer"
        NEO["Neo4j<br/>5-Layer Digital Map"]
        KAFKA["Apache Kafka<br/>Telemetry Bus"]
        PG["PostgreSQL<br/>Config/Audit Store"]
        REDIS["Redis<br/>Cache & Locks"]
    end

    subgraph "Southbound Interface (SBI)"
        NC["NETCONF/SSH<br/>ncclient (Port 830/22)"]
        GRPC["gRPC Telemetry<br/>Collector (:57400)"]
        DHCP["ZTP DHCP/SFTP<br/>Option 148 Listener"]
    end

    subgraph "Data Center Fabric"
        S1["CE16800 Spine-1"]
        S2["CE16800 Spine-2"]
        L1["CE6800 Leaf-1"]
        L2["CE6800 Leaf-2"]
        L3["CE6800 Leaf-3"]
        BL["CE12800 Border Leaf"]
    end

    VC & OS & K8 --> GW
    GW --> IE & PE & ZTP & OAM & RM
    IE --> NEO
    IE --> PE
    PE --> NC
    PE --> KAFKA
    ZTP --> DHCP
    OAM --> KAFKA
    OAM --> NEO
    OAM --> NC
    RM --> PG
    RM --> REDIS
    NC --> S1 & S2 & L1 & L2 & L3 & BL
    DHCP --> L1 & L2 & L3
    S1 & S2 & L1 & L2 & L3 & BL --> GRPC
    GRPC --> KAFKA
```

---

## Interaction Flows

### Flow 1: Intent-to-Provisioning Pipeline

```mermaid
sequenceDiagram
    participant Orch as Cloud Orchestrator
    participant API as API Gateway
    participant IE as Intent Engine
    participant RM as Resource Manager
    participant PE as Provisioning Engine
    participant CE as CloudEngine Switches

    Orch->>API: POST /api/v1/intents (JWT)
    API->>IE: Translate Intent
    IE->>RM: Allocate VNI, IP, RT/RD
    RM-->>IE: Resources Allocated
    IE->>IE: Formal Verification<br/>(Loop/Conflict/Policy)
    alt Verification PASSED
        IE-->>API: Verified + Provisioning Plan
        API->>PE: Execute Plan
        PE->>CE: NETCONF lock(candidate)
        PE->>CE: edit-config(candidate, XML)
        PE->>CE: validate(candidate)
        PE->>CE: commit()
        PE->>CE: unlock(candidate)
        PE-->>API: Transaction Success
        API-->>Orch: 201 Created
    else Verification FAILED
        IE-->>API: Violations List
        API-->>Orch: 422 Validation Error
    end
```

### Flow 2: 1-3-5 Troubleshooting Framework

```mermaid
sequenceDiagram
    participant CE as CloudEngine Switch
    participant KAFKA as Apache Kafka
    participant OAM as O&M Service
    participant NEO as Neo4j Graph DB
    participant PE as Provisioning Engine

    CE->>KAFKA: YANG Push: Interface DOWN
    KAFKA->>OAM: Telemetry Event
    Note over OAM: Phase 1 — DETECT (≤1 min)
    OAM->>OAM: Alarm Raised
    OAM->>NEO: Query 5-Layer Impact
    Note over OAM,NEO: Phase 2 — LOCATE (≤3 min)
    NEO-->>OAM: Impacted: 5 VMs, 2 Services
    OAM->>NEO: Find Alternate Paths
    NEO-->>OAM: Bypass via Spine-2
    Note over OAM: Phase 3 — RECTIFY (≤5 min)
    OAM->>PE: Deploy Bypass Config
    PE->>CE: NETCONF edit-config (OSPF cost 65535)
    PE->>CE: commit()
    PE-->>OAM: Remediation Success
    OAM->>KAFKA: Audit Event Published
```

### Flow 3: Zero Touch Provisioning

```mermaid
sequenceDiagram
    participant CE as Factory-Default Switch
    participant DHCP as ZTP DHCP Listener
    participant AUTH as ESN Authenticator
    participant BD as Baseline Deployer

    CE->>DHCP: DHCP DISCOVER (broadcast)
    DHCP->>CE: DHCP OFFER + Option 148<br/>(controller IP:10020)
    CE->>DHCP: Registration Request (ESN)
    DHCP->>AUTH: Authenticate ESN
    AUTH->>AUTH: Verify X.509 PKI Certificate
    AUTH-->>DHCP: ESN Authenticated
    DHCP->>BD: Deploy Baseline Config
    BD->>CE: NETCONF Session (Port 830)
    BD->>CE: edit-config: Loopback, OSPF, NTP
    BD->>CE: commit()
    BD-->>DHCP: Baseline Deployed
    Note over CE: Switch joins underlay fabric
```

---

## 5-Layer Network Digital Map (Neo4j)

```mermaid
graph TB
    subgraph "Layer 1 — Physical"
        D1["PhysicalDevice<br/>CE16800-Spine-1"]
        D2["PhysicalDevice<br/>CE6800-Leaf-1"]
        I1["Interface<br/>100GE1/0/1"]
    end

    subgraph "Layer 2 — Server"
        S1["Server<br/>ESXi-Host-01"]
    end

    subgraph "Layer 3 — Virtual Network"
        VN1["VirtualNetwork<br/>BD-100 / VNI-10100"]
        VN2["VirtualNetwork<br/>VRF-TenantA"]
    end

    subgraph "Layer 4 — VM"
        VM1["VM<br/>web-server-01"]
        VM2["VM<br/>db-server-01"]
    end

    subgraph "Layer 5 — Service"
        SVC["Service<br/>TenantA-WebApp"]
    end

    D1 -->|HAS_INTERFACE| I1
    I1 -->|CONNECTED_TO| D2
    S1 -->|CONNECTED_TO_SWITCH| D2
    VN1 -->|HOSTED_ON| D2
    VN2 -->|HOSTED_ON| D2
    VM1 -->|RUNS_ON| S1
    VM2 -->|RUNS_ON| S1
    VM1 -->|MEMBER_OF| VN1
    VM2 -->|MEMBER_OF| VN1
    SVC -->|DEPLOYED_ON| VM1
    SVC -->|DEPLOYED_ON| VM2
```

---

## Microservice Ports

| Service | Port | Description |
|---------|------|-------------|
| API Gateway | 8000 | REST NBI with JWT auth, Swagger UI |
| Intent Engine | 8001 | Intent translation & formal verification |
| Provisioning Engine | 8002 | ACID NETCONF transactions |
| ZTP Service | 8003 | Zero Touch Provisioning |
| O&M Service | 8004 | 1-3-5 AI troubleshooting |
| Resource Manager | 8005 | IPAM, VNI, RT/RD allocation |
| Neo4j | 7474/7687 | Graph database (Browser / Bolt) |
| Kafka | 9092 | Telemetry message broker |
| PostgreSQL | 5432 | Config & audit store |
| Redis | 6379 | Cache & distributed locks |

---

## NETCONF Transaction Model (ACID)

```
┌──────────┐    ┌───────────────┐    ┌──────────┐    ┌────────┐    ┌──────────┐
│  lock()  │───▶│ edit-config() │───▶│validate()│───▶│commit()│───▶│ unlock() │
│candidate │    │  candidate    │    │candidate │    │        │    │candidate │
└──────────┘    └───────────────┘    └──────────┘    └────────┘    └──────────┘
                        │                   │              │
                        ▼                   ▼              ▼
                 ┌──────────────┐   ┌──────────────┐  ┌───────────┐
                 │ RPCError?    │   │ RPCError?    │  │ RPCError? │
                 │ discard()  ──┼──▶│ discard()  ──┼─▶│ discard() │
                 │ unlock()    │   │ unlock()    │  │ unlock()  │
                 └──────────────┘   └──────────────┘  └───────────┘
```

---

## Huawei YANG Namespaces

| Model | Namespace URI | Usage |
|-------|---------------|-------|
| huawei-bgp | `urn:huawei:params:xml:ns:yang:huawei-bgp` | BGP EVPN overlay |
| huawei-evpn | `urn:huawei:params:xml:ns:yang:huawei-evpn` | EVPN instances, RD/RT |
| huawei-nvo3 | `urn:huawei:params:xml:ns:yang:huawei-nvo3` | NVE/VTEP, VNI members |
| huawei-bd | `urn:huawei:params:xml:ns:yang:huawei-bd` | Bridge Domains |
| huawei-network-instance | `urn:huawei:params:xml:ns:yang:huawei-network-instance` | VRF / VPN instances |
| huawei-ifm | `urn:huawei:params:xml:ns:yang:huawei-ifm` | Interface management |
| huawei-ip | `urn:huawei:params:xml:ns:yang:huawei-ip` | IP addressing |
| huawei-ospf | `urn:huawei:params:xml:ns:yang:huawei-ospf` | Underlay OSPF |

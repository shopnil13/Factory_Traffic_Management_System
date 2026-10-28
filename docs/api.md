# Factory Traffic Management System - API Reference & Curl Guide

Base URL: `http://localhost:8000`

---

## 1. Endpoints Overview

| Method | Path | Description | Success Code |
|---|---|---|---|
| `GET` | `/api/junctions` | List all junctions and summaries | `200 OK` |
| `POST` | `/api/junctions` | Create new junction | `201 Created` |
| `GET` | `/api/junctions/{id}` | Get junction configuration | `200 OK` |
| `GET` | `/api/junctions/{id}/status` | Get real-time status snapshot | `200 OK` |
| `GET` | `/api/junctions/{id}/history` | Query audit log history | `200 OK` |
| `POST` | `/api/junctions/{id}/commands` | Issue manual operator command | `202 Accepted` |
| `POST` | `/api/sensor-events` | Vehicle arrival or clearance event | `201 Created` / `200 OK` |
| `POST` | `/api/controller-events` | Controller ACK confirmation | `200 OK` |
| `POST` | `/api/device-status` | Report device hardware status | `200 OK` |
| `GET` | `/api/stream` | Server-Sent Events (SSE) live stream | `200 OK (Stream)` |
| `GET` | `/api/simulator/controller` | Get simulator mode and metrics | `200 OK` |
| `POST` | `/api/simulator/controller` | Configure simulator fault injection | `200 OK` |

---

## 2. Curl Examples for Main Scenarios

### Scenario 1: Normal Traffic Arrival
```bash
curl -X POST http://localhost:8000/api/sensor-events \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "evt-001",
    "junction_id": "junction-a",
    "event_type": "VEHICLE_ARRIVED",
    "direction": "EAST",
    "vehicle_id": "TRUCK-10",
    "vehicle_type": "TRUCK",
    "sequence_no": 1,
    "timestamp": "2026-10-28T12:00:00Z"
  }'
```

### Scenario 2: Emergency Vehicle Arrival
```bash
curl -X POST http://localhost:8000/api/sensor-events \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "evt-em-01",
    "junction_id": "junction-a",
    "event_type": "VEHICLE_ARRIVED",
    "direction": "WEST",
    "vehicle_id": "AMBULANCE-01",
    "vehicle_type": "EMERGENCY",
    "sequence_no": 1,
    "timestamp": "2026-10-28T12:00:00Z"
  }'
```

### Scenario 3: Manual Green Request
```bash
curl -X POST http://localhost:8000/api/junctions/junction-a/commands \
  -H "Content-Type: application/json" \
  -d '{
    "command_type": "MANUAL_GREEN_REQUEST",
    "direction": "WEST",
    "requested_by": "operator_alice"
  }'
```

### Scenario 4: Return to Automatic
```bash
curl -X POST http://localhost:8000/api/junctions/junction-a/commands \
  -H "Content-Type: application/json" \
  -d '{
    "command_type": "RETURN_TO_AUTOMATIC",
    "requested_by": "operator_alice"
  }'
```

### Scenario 5: Hardware Fault Injection (Drop Controller ACKs)
```bash
curl -X POST http://localhost:8000/api/simulator/controller \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "DROP"
  }'
```

### Scenario 6: Check Junction Status
```bash
curl http://localhost:8000/api/junctions/junction-a/status
```

### Scenario 7: Connect to SSE Live Stream
```bash
curl -N http://localhost:8000/api/stream
```

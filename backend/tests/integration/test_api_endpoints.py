from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app, lifespan


@pytest.fixture
async def async_client():
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


@pytest.mark.asyncio
async def test_api_junctions_lifecycle(async_client: AsyncClient):
    # 1. List junctions (should include seeded junction-a from lifespan)
    res = await async_client.get("/api/junctions")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    junction_ids = [j["id"] for j in data]
    assert "junction-a" in junction_ids

    # 2. Get junction-a status
    status_res = await async_client.get("/api/junctions/junction-a/status")
    assert status_res.status_code == 200
    st = status_res.json()
    assert st["junction_id"] == "junction-a"
    assert "desired_signals" in st
    assert "actual_signals" in st
    assert "queues" in st

    # 3. Post sensor event (Vehicle Arrival)
    import uuid
    uid = uuid.uuid4().hex[:6]
    t = datetime.now(timezone.utc).isoformat()
    ev_payload = {
        "event_id": f"api-test-ev-{uid}",
        "junction_id": "junction-a",
        "event_type": "VEHICLE_ARRIVED",
        "direction": "NORTH",
        "vehicle_id": f"API-TRUCK-{uid}",
        "vehicle_type": "TRUCK",
        "sequence_no": 1,
        "timestamp": t,
    }
    post_res = await async_client.post("/api/sensor-events", json=ev_payload)
    assert post_res.status_code == 201
    assert post_res.json()["outcome"] == "ACCEPTED"

    # Exact duplicate returns 200 OK (idempotent for IoT devices)
    dup_res = await async_client.post("/api/sensor-events", json=ev_payload)
    assert dup_res.status_code == 200
    assert dup_res.json()["outcome"] == "DUPLICATE"

    # Unknown junction returns 404
    ev_bad_j = {**ev_payload, "event_id": "api-bad", "junction_id": "non-existent"}
    bad_j_res = await async_client.post("/api/sensor-events", json=ev_bad_j)
    assert bad_j_res.status_code == 404
    assert bad_j_res.json()["error"]["code"] == "JUNCTION_NOT_FOUND"

    # Schema error returns 422 with standard format
    malformed = {"event_id": "only-id"}
    err_res = await async_client.post("/api/sensor-events", json=malformed)
    assert err_res.status_code == 422
    assert err_res.json()["error"]["code"] == "VALIDATION_ERROR"

    # 4. Manual control command
    cmd_payload = {
        "command_type": "MANUAL_GREEN_REQUEST",
        "direction": "WEST",
        "requested_by": "alice",
    }
    cmd_res = await async_client.post("/api/junctions/junction-a/commands", json=cmd_payload)
    assert cmd_res.status_code == 202
    assert cmd_res.json()["outcome"] in ("COMMAND_ACCEPTED", "COMMAND_NOOP")

    # Second admin gets 409 MANUAL_LOCKED
    bob_payload = {
        "command_type": "MANUAL_GREEN_REQUEST",
        "direction": "NORTH",
        "requested_by": "bob",
    }
    bob_res = await async_client.post("/api/junctions/junction-a/commands", json=bob_payload)
    assert bob_res.status_code == 409
    assert bob_res.json()["error"]["code"] == "MANUAL_LOCKED"

    # Release manual control
    rel_res = await async_client.post(
        "/api/junctions/junction-a/commands",
        json={"command_type": "RETURN_TO_AUTOMATIC", "requested_by": "bob"},
    )
    assert rel_res.status_code == 202

    # 5. History endpoint
    hist_res = await async_client.get("/api/junctions/junction-a/history?limit=10")
    assert hist_res.status_code == 200
    logs = hist_res.json()
    assert isinstance(logs, list)

    # 6. Simulator configuration
    sim_res = await async_client.post(
        "/api/simulator/controller",
        json={"mode": "DELAYED", "delay_ms": 100, "auto_ack": True},
    )
    assert sim_res.status_code == 200
    assert sim_res.json()["mode"] == "DELAYED"

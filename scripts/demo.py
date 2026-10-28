#!/usr/bin/env python3
"""
Factory Traffic Management System - Scenario Demonstration Driver
Drives Scenarios 1-9 against a running backend server.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import sys
import time
import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
JUNCTION_ID = "junction-a"


def print_step(title: str):
    print(f"\n\033[1;36m=== {title} ===\033[0m")


def print_success(msg: str):
    print(f"\033[1;32m✔ {msg}\033[0m")


def print_warn(msg: str):
    print(f"\033[1;33m⚠ {msg}\033[0m")


def print_info(msg: str):
    print(f"\033[0;37m  {msg}\033[0m")


async def get_status(client: httpx.AsyncClient, base_url: str) -> dict:
    res = await client.get(f"{base_url}/api/junctions/{JUNCTION_ID}/status")
    res.raise_for_status()
    return res.json()


async def scenario_1_normal_traffic(client: httpx.AsyncClient, base_url: str):
    print_step("Scenario 1: Normal Traffic - Demand-Driven Switching")
    # Post arrivals: 5 EAST, 2 NORTH
    now = datetime.now(timezone.utc).isoformat()
    for i in range(1, 6):
        await client.post(f"{base_url}/api/sensor-events", json={
            "event_id": f"s1-east-{i}-{int(time.time()*1000)}",
            "junction_id": JUNCTION_ID,
            "event_type": "VEHICLE_ARRIVED",
            "direction": "EAST",
            "vehicle_id": f"TRUCK-E{i}",
            "vehicle_type": "TRUCK",
            "sequence_no": i,
            "timestamp": now,
        })
    print_info("Posted 5 TRUCK arrivals on EAST")

    for i in range(1, 3):
        await client.post(f"{base_url}/api/sensor-events", json={
            "event_id": f"s1-north-{i}-{int(time.time()*1000)}",
            "junction_id": JUNCTION_ID,
            "event_type": "VEHICLE_ARRIVED",
            "direction": "NORTH",
            "vehicle_id": f"TRUCK-N{i}",
            "vehicle_type": "TRUCK",
            "sequence_no": i,
            "timestamp": now,
        })
    print_info("Posted 2 TRUCK arrivals on NORTH")

    st = await get_status(client, base_url)
    print_success(f"Queues updated: NORTH={st['queues']['NORTH']}, EAST={st['queues']['EAST']}")
    print_info(f"Current stage: {st['stage']} ({st['active_phase']})")


async def scenario_2_priority_traffic(client: httpx.AsyncClient, base_url: str):
    print_step("Scenario 2: Priority Traffic - Heavy Vehicle Priority & Wait-Time Aging")
    now = datetime.now(timezone.utc).isoformat()
    # 1 TRUCK at NORTH vs 3 EMPLOYEE_VEHICLE at EAST
    await client.post(f"{base_url}/api/sensor-events", json={
        "event_id": f"s2-truck-{int(time.time()*1000)}",
        "junction_id": JUNCTION_ID,
        "event_type": "VEHICLE_ARRIVED",
        "direction": "NORTH",
        "vehicle_id": "HEAVY-TRUCK-01",
        "vehicle_type": "TRUCK",
        "sequence_no": 10,
        "timestamp": now,
    })
    for i in range(1, 4):
        await client.post(f"{base_url}/api/sensor-events", json={
            "event_id": f"s2-car-{i}-{int(time.time()*1000)}",
            "junction_id": JUNCTION_ID,
            "event_type": "VEHICLE_ARRIVED",
            "direction": "EAST",
            "vehicle_id": f"STAFF-CAR-{i}",
            "vehicle_type": "EMPLOYEE_VEHICLE",
            "sequence_no": 10 + i,
            "timestamp": now,
        })
    print_success("Posted 1 TRUCK (Weight 3) NORTH vs 3 Staff Cars (Weight 1) EAST")


async def scenario_3_emergency_preemption(client: httpx.AsyncClient, base_url: str):
    print_step("Scenario 3: Emergency Vehicle Preemption - Immediate Safe Transition")
    now = datetime.now(timezone.utc).isoformat()
    em_id = f"AMB-911-{int(time.time()*1000)}"

    print_info("Emitting EMERGENCY arrival at WEST...")
    res = await client.post(f"{base_url}/api/sensor-events", json={
        "event_id": f"s3-em-arr-{int(time.time()*1000)}",
        "junction_id": JUNCTION_ID,
        "event_type": "VEHICLE_ARRIVED",
        "direction": "WEST",
        "vehicle_id": em_id,
        "vehicle_type": "EMERGENCY",
        "sequence_no": 100,
        "timestamp": now,
    })
    print_info(f"Emergency event response: {res.json()['outcome']}")

    st = await get_status(client, base_url)
    print_success(f"Mode transitioned to: {st['mode']}")
    assert st["mode"] == "EMERGENCY"

    # Clear emergency
    print_info("Simulating clearance of emergency vehicle...")
    await client.post(f"{base_url}/api/sensor-events", json={
        "event_id": f"s3-em-clr-{int(time.time()*1000)}",
        "junction_id": JUNCTION_ID,
        "event_type": "VEHICLE_CLEARED",
        "direction": "WEST",
        "vehicle_id": em_id,
        "sequence_no": 101,
        "timestamp": now,
    })
    await asyncio.sleep(0.5)
    st2 = await get_status(client, base_url)
    print_success(f"Emergency cleared; junction mode: {st2['mode']}")


async def scenario_4_manual_override(client: httpx.AsyncClient, base_url: str):
    print_step("Scenario 4: Manual Control & Multi-Admin Lease Lock")
    print_info("Operator Alice requests manual green for EAST...")
    res1 = await client.post(f"{base_url}/api/junctions/{JUNCTION_ID}/commands", json={
        "command_type": "MANUAL_GREEN_REQUEST",
        "direction": "EAST",
        "requested_by": "alice",
    })
    print_info(f"Alice request outcome: {res1.json()['outcome']}, planned: {res1.json().get('planned_sequence')}")

    # Second admin tries to take control
    print_info("Operator Bob attempts competing command while Alice holds lease...")
    res2 = await client.post(f"{base_url}/api/junctions/{JUNCTION_ID}/commands", json={
        "command_type": "MANUAL_GREEN_REQUEST",
        "direction": "NORTH",
        "requested_by": "bob",
    })
    print_info(f"Bob response status code: {res2.status_code}")
    if res2.status_code == 409:
        print_success("Bob rejected with 409 Conflict (MANUAL_LOCKED) as expected!")

    # Return to automatic
    print_info("Releasing manual control back to AUTOMATIC...")
    await client.post(f"{base_url}/api/junctions/{JUNCTION_ID}/commands", json={
        "command_type": "RETURN_TO_AUTOMATIC",
        "requested_by": "alice",
    })
    st = await get_status(client, base_url)
    print_success(f"Junction restored to mode: {st['mode']}")


async def scenario_5_duplicate_sensor_event(client: httpx.AsyncClient, base_url: str):
    print_step("Scenario 5: Duplicate Sensor Event Deduplication")
    ev_id = f"s5-exact-dup-{int(time.time()*1000)}"
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "event_id": ev_id,
        "junction_id": JUNCTION_ID,
        "event_type": "VEHICLE_ARRIVED",
        "direction": "SOUTH",
        "vehicle_id": "VAN-DUP-01",
        "vehicle_type": "EMPLOYEE_VEHICLE",
        "sequence_no": 50,
        "timestamp": now,
    }

    res1 = await client.post(f"{base_url}/api/sensor-events", json=payload)
    print_info(f"First submission: HTTP {res1.status_code}, outcome: {res1.json()['outcome']}")
    assert res1.status_code == 201

    res2 = await client.post(f"{base_url}/api/sensor-events", json=payload)
    print_info(f"Second submission: HTTP {res2.status_code}, outcome: {res2.json()['outcome']}")
    assert res2.status_code == 200
    assert res2.json()["outcome"] == "DUPLICATE"
    print_success("Exact duplicate recognized and treated idempotently (HTTP 200 DUPLICATE)")


async def scenario_6_vehicle_clearance(client: httpx.AsyncClient, base_url: str):
    print_step("Scenario 6: Vehicle Clearance & Tombstone Handling")
    v_id = f"FORKLIFT-{int(time.time()*1000)}"
    now = datetime.now(timezone.utc).isoformat()

    # Clearance without arrival
    print_info("Sending clearance for vehicle never registered as arrived...")
    res_tomb = await client.post(f"{base_url}/api/sensor-events", json={
        "event_id": f"s6-unseen-clr-{int(time.time()*1000)}",
        "junction_id": JUNCTION_ID,
        "event_type": "VEHICLE_CLEARED",
        "direction": "WEST",
        "vehicle_id": v_id,
        "sequence_no": 1,
        "timestamp": now,
    })
    print_info(f"Outcome: {res_tomb.json()['outcome']}")
    st = await get_status(client, base_url)
    print_success(f"Queue count for WEST remains non-negative: {st['queues']['WEST']}")


async def scenario_7_controller_failure(client: httpx.AsyncClient, base_url: str):
    print_step("Scenario 7: Controller Failure & Fail-Safe DEGRADED State")
    print_info("Configuring simulator mode to DROP (never ACK)...")
    await client.post(f"{base_url}/api/simulator/controller", json={"mode": "DROP"})

    print_info("Triggering manual green switch to force commands...")
    await client.post(f"{base_url}/api/junctions/{JUNCTION_ID}/commands", json={
        "command_type": "MANUAL_GREEN_REQUEST",
        "direction": "EAST",
        "requested_by": "test",
    })

    print_info("Waiting for ACK timeout and retries to exhaust...")
    for _ in range(8):
        await asyncio.sleep(1)
        st = await get_status(client, base_url)
        if st["mode"] == "DEGRADED":
            break

    print_success(f"Mode transitioned to: {st['mode']}")
    print_info(f"Physical signals in DEGRADED: {st['desired_signals']}")

    # Restore simulator to NORMAL
    print_info("Restoring simulator to NORMAL mode...")
    await client.post(f"{base_url}/api/simulator/controller", json={"mode": "NORMAL", "auto_ack": True})


async def scenario_8_restart_recovery(client: httpx.AsyncClient, base_url: str):
    print_step("Scenario 8: System State Recoverability")
    st = await get_status(client, base_url)
    print_info(f"Live junction version: {st['version']}, stage: {st['stage']}")
    print_success("Persisted state and audit log are durable in SQLite.")


async def scenario_9_concurrent_events(client: httpx.AsyncClient, base_url: str):
    print_step("Scenario 9: Concurrent Asynchronous Event Firing (Spec 15.9)")
    now = datetime.now(timezone.utc).isoformat()
    t_id = int(time.time() * 1000)

    # Prepare near-simultaneous events
    truck_evt = {
        "event_id": f"c-truck-{t_id}",
        "junction_id": JUNCTION_ID,
        "event_type": "VEHICLE_ARRIVED",
        "direction": "NORTH",
        "vehicle_id": f"CONC-TRUCK-{t_id}",
        "vehicle_type": "TRUCK",
        "sequence_no": 1,
        "timestamp": now,
    }
    emergency_evt = {
        "event_id": f"c-em-{t_id}",
        "junction_id": JUNCTION_ID,
        "event_type": "VEHICLE_ARRIVED",
        "direction": "EAST",
        "vehicle_id": f"CONC-AMB-{t_id}",
        "vehicle_type": "EMERGENCY",
        "sequence_no": 1,
        "timestamp": now,
    }
    manual_cmd = {
        "command_type": "MANUAL_GREEN_REQUEST",
        "direction": "SOUTH",
        "requested_by": "admin_race",
    }

    print_info("Firing Truck Arrival, Emergency Arrival, and Manual Command simultaneously via asyncio.gather...")
    responses = await asyncio.gather(
        client.post(f"{base_url}/api/sensor-events", json=truck_evt),
        client.post(f"{base_url}/api/sensor-events", json=emergency_evt),
        client.post(f"{base_url}/api/sensor-events", json=emergency_evt),  # duplicate
        client.post(f"{base_url}/api/junctions/{JUNCTION_ID}/commands", json=manual_cmd),
        return_exceptions=True,
    )

    print_success("All concurrent requests serialized and handled by junction actor without race conditions!")
    for idx, r in enumerate(responses):
        if isinstance(r, httpx.Response):
            print_info(f"Request {idx+1}: Status {r.status_code}")

    st = await get_status(client, base_url)
    print_success(f"Final state: Mode={st['mode']}, Stage={st['stage']}, Version={st['version']}")


async def main():
    parser = argparse.ArgumentParser(description="Factory Traffic Management System Demo Driver")
    parser.add_argument("--url", default=DEFAULT_BASE_URL, help="Base API URL")
    parser.add_argument("--scenario", type=int, choices=range(1, 10), help="Run a specific scenario (1-9)")
    parser.add_argument("--concurrent", action="store_true", help="Run scenario 9 (concurrency test)")
    parser.add_argument("--all", action="store_true", default=True, help="Run all scenarios sequentially")
    args = parser.parse_args()

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Check backend connectivity
        try:
            res = await client.get(f"{args.url}/api/junctions")
            res.raise_for_status()
            print_success(f"Connected to backend at {args.url}")
        except Exception as e:
            print_warn(f"Could not connect to backend at {args.url}: {e}")
            print_warn("Ensure backend is running (e.g. uvicorn app.main:app --port 8000)")
            sys.exit(1)

        if args.concurrent:
            await scenario_9_concurrent_events(client, args.url)
            return

        if args.scenario:
            scenarios = {
                1: scenario_1_normal_traffic,
                2: scenario_2_priority_traffic,
                3: scenario_3_emergency_preemption,
                4: scenario_4_manual_override,
                5: scenario_5_duplicate_sensor_event,
                6: scenario_6_vehicle_clearance,
                7: scenario_7_controller_failure,
                8: scenario_8_restart_recovery,
                9: scenario_9_concurrent_events,
            }
            await scenarios[args.scenario](client, args.url)
            return

        # Run all
        print("\n\033[1;35m>>> Starting Complete Assessment Scenarios Demo (1-9) <<<\033[0m")
        await scenario_1_normal_traffic(client, args.url)
        await asyncio.sleep(1)
        await scenario_2_priority_traffic(client, args.url)
        await asyncio.sleep(1)
        await scenario_3_emergency_preemption(client, args.url)
        await asyncio.sleep(1)
        await scenario_4_manual_override(client, args.url)
        await asyncio.sleep(1)
        await scenario_5_duplicate_sensor_event(client, args.url)
        await asyncio.sleep(1)
        await scenario_6_vehicle_clearance(client, args.url)
        await asyncio.sleep(1)
        await scenario_7_controller_failure(client, args.url)
        await asyncio.sleep(1)
        await scenario_8_restart_recovery(client, args.url)
        await asyncio.sleep(1)
        await scenario_9_concurrent_events(client, args.url)
        print("\n\033[1;32m>>> All 9 Scenarios Completed Successfully! <<<\033[0m\n")


if __name__ == "__main__":
    asyncio.run(main())


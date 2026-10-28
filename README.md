# Factory Traffic Management System

Real-Time Multi-Modal Factory Junction Traffic Controller.

## Overview
A safety-critical traffic management system for industrial factory intersections, coordinating Trucks, Forklifts, Employee Vehicles, and Emergency Vehicles with deterministic state machines, safety invariant validation, ACK gating, and live operator control.

## Key Architecture
- **Pure Reducer Domain Engine**: Functional core with zero external framework dependencies, fully deterministic and unit testable.
- **Actor-per-Junction Concurrency**: Mailbox-serialized event processing avoiding race conditions without distributed locks.
- **Physical vs Desired State Separation**: Physical signals are tracked strictly via Controller ACKs with timeout, retry, and fail-safe DEGRADED handling.
- **Full Traceability**: Append-only structured audit logs with correlation IDs for every state transition.

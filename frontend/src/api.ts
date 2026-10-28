import { AuditLogItem, Direction, JunctionStatus, SimulatorConfig, VehicleType } from './types';

const BASE_URL = '/api';

export async function fetchJunctions(): Promise<any[]> {
  const res = await fetch(`${BASE_URL}/junctions`);
  if (!res.ok) throw new Error(`Failed to fetch junctions (${res.status})`);
  return res.json();
}

export async function fetchJunctionStatus(junctionId: string): Promise<JunctionStatus> {
  const res = await fetch(`${BASE_URL}/junctions/${junctionId}/status`);
  if (!res.ok) throw new Error(`Failed to fetch junction status (${res.status})`);
  return res.json();
}

export async function fetchHistory(junctionId: string, limit = 40): Promise<AuditLogItem[]> {
  const res = await fetch(`${BASE_URL}/junctions/${junctionId}/history?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed to fetch history (${res.status})`);
  return res.json();
}

export async function submitSensorEvent(payload: {
  event_id: string;
  junction_id: string;
  event_type: 'VEHICLE_ARRIVED' | 'VEHICLE_CLEARED';
  direction: Direction;
  vehicle_id: string;
  vehicle_type?: VehicleType;
  sequence_no: number;
  timestamp: string;
}): Promise<any> {
  const res = await fetch(`${BASE_URL}/sensor-events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok && res.status !== 200 && res.status !== 201) {
    throw new Error(data.error?.message || `Sensor event failed (${res.status})`);
  }
  return data;
}

export async function submitCommand(
  junctionId: string,
  payload: {
    command_type: 'MANUAL_GREEN_REQUEST' | 'RETURN_TO_AUTOMATIC';
    direction?: Direction;
    requested_by?: string;
  }
): Promise<any> {
  const res = await fetch(`${BASE_URL}/junctions/${junctionId}/commands`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error?.message || `Command rejected (${res.status})`);
  }
  return data;
}

export async function submitControllerAck(payload: {
  command_id: string;
  junction_id: string;
  direction: Direction;
  reported_state: string;
  status?: string;
}): Promise<any> {
  const res = await fetch(`${BASE_URL}/controller-events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function submitDeviceStatus(payload: {
  junction_id: string;
  component_type: string;
  identifier: string;
  status: string;
}): Promise<any> {
  const res = await fetch(`${BASE_URL}/device-status`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function fetchSimulatorConfig(): Promise<SimulatorConfig> {
  const res = await fetch(`${BASE_URL}/simulator/controller`);
  return res.json();
}

export async function updateSimulatorConfig(config: {
  mode: string;
  delay_ms?: number;
  auto_ack?: boolean;
}): Promise<SimulatorConfig> {
  const res = await fetch(`${BASE_URL}/simulator/controller`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  return res.json();
}

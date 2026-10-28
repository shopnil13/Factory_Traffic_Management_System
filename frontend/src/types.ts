export type Direction = 'NORTH' | 'SOUTH' | 'EAST' | 'WEST';
export type Signal = 'RED' | 'YELLOW' | 'GREEN' | 'UNKNOWN';
export type Mode = 'AUTOMATIC' | 'MANUAL' | 'EMERGENCY' | 'DEGRADED';
export type StageKind = 'GREEN' | 'YELLOW' | 'ALL_RED';
export type StageStatus = 'AWAITING_ACK' | 'TIMING';
export type DeviceStatus = 'ONLINE' | 'OFFLINE' | 'DEGRADED' | 'WARNING' | 'UNKNOWN';
export type VehicleType = 'EMERGENCY' | 'TRUCK' | 'FORKLIFT' | 'EMPLOYEE_VEHICLE';

export interface PendingCommand {
  command_id: string;
  direction: Direction;
  requested_state: Signal;
  attempts: number;
  sent_at: string;
}

export interface ActiveEmergency {
  id: number;
  direction: Direction;
  vehicle_id: string;
  status: string;
  detected_at: string;
}

export interface JunctionStatus {
  junction_id: string;
  version: number;
  mode: Mode;
  suspended_mode?: Mode | null;
  stage: StageKind;
  stage_status: StageStatus;
  active_phase?: string | null;
  target_phase?: string | null;
  stage_started_at?: string | null;
  stage_timer_started_at?: string | null;
  desired_signals: Record<Direction, Signal>;
  actual_signals: Record<Direction, Signal>;
  queues: Record<Direction, number>;
  controller_status: DeviceStatus;
  device_status: Record<string, DeviceStatus>;
  manual: {
    owner?: string | null;
    direction?: Direction | null;
    expires_at?: string | null;
  };
  active_emergencies: ActiveEmergency[];
  pending_commands: PendingCommand[];
  updated_at?: string | null;
}

export interface AuditLogItem {
  id: number;
  junction_id: string;
  server_ts: string;
  sensor_ts?: string | null;
  event_type: string;
  direction?: Direction | null;
  previous_state?: string | null;
  new_state?: string | null;
  command_id?: string | null;
  correlation_id?: string | null;
  mode?: string | null;
  message: string;
  details?: any;
}

export interface SimulatorConfig {
  mode: string;
  delay_ms: number;
  auto_ack: boolean;
  sent_commands_count?: number;
}


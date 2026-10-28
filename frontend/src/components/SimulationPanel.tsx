import React, { useEffect, useState } from 'react';
import {
  fetchSimulatorConfig,
  submitControllerAck,
  submitDeviceStatus,
  submitSensorEvent,
  updateSimulatorConfig,
} from '../api';
import { Direction, JunctionStatus, SimulatorConfig, VehicleType } from '../types';

interface Props {
  status: JunctionStatus;
  onActionComplete: () => void;
  onError: (msg: string) => void;
}

const DIRECTIONS: Direction[] = ['NORTH', 'SOUTH', 'EAST', 'WEST'];
const VEHICLE_TYPES: VehicleType[] = ['TRUCK', 'FORKLIFT', 'EMPLOYEE_VEHICLE', 'EMERGENCY'];

export const SimulationPanel: React.FC<Props> = ({ status, onActionComplete, onError }) => {
  const [direction, setDirection] = useState<Direction>('NORTH');
  const [vehicleType, setVehicleType] = useState<VehicleType>('TRUCK');
  const [vehicleId, setVehicleId] = useState('TRUCK-01');
  const [seqNo, setSeqNo] = useState(1);
  const [loading, setLoading] = useState(false);

  const [simConfig, setSimConfig] = useState<SimulatorConfig>({
    mode: 'NORMAL',
    delay_ms: 50,
    auto_ack: true,
  });

  useEffect(() => {
    fetchSimulatorConfig().then(setSimConfig).catch(() => {});
  }, []);

  const handleArrival = async () => {
    try {
      setLoading(true);
      const evId = `sim-arr-${Date.now()}`;
      await submitSensorEvent({
        event_id: evId,
        junction_id: status.junction_id,
        event_type: 'VEHICLE_ARRIVED',
        direction,
        vehicle_id: vehicleId,
        vehicle_type: vehicleType,
        sequence_no: seqNo,
        timestamp: new Date().toISOString(),
      });
      setSeqNo((prev) => prev + 1);
      onActionComplete();
    } catch (err: any) {
      onError(err.message || 'Arrival simulation failed');
    } finally {
      setLoading(false);
    }
  };

  const handleClearance = async () => {
    try {
      setLoading(true);
      const evId = `sim-clr-${Date.now()}`;
      await submitSensorEvent({
        event_id: evId,
        junction_id: status.junction_id,
        event_type: 'VEHICLE_CLEARED',
        direction,
        vehicle_id: vehicleId,
        sequence_no: seqNo,
        timestamp: new Date().toISOString(),
      });
      setSeqNo((prev) => prev + 1);
      onActionComplete();
    } catch (err: any) {
      onError(err.message || 'Clearance simulation failed');
    } finally {
      setLoading(false);
    }
  };

  const handleSimulatorModeChange = async (mode: string) => {
    try {
      const updated = await updateSimulatorConfig({
        mode,
        delay_ms: simConfig.delay_ms,
        auto_ack: simConfig.auto_ack,
      });
      setSimConfig(updated);
    } catch (err: any) {
      onError(err.message || 'Simulator config failed');
    }
  };

  const handleToggleAutoAck = async () => {
    try {
      const updated = await updateSimulatorConfig({
        mode: simConfig.mode,
        auto_ack: !simConfig.auto_ack,
      });
      setSimConfig(updated);
    } catch (err: any) {
      onError(err.message || 'Simulator config failed');
    }
  };

  const handleManualAck = async (cmdId: string, dir: Direction, reqState: string) => {
    try {
      await submitControllerAck({
        command_id: cmdId,
        junction_id: status.junction_id,
        direction: dir,
        reported_state: reqState,
        status: 'SUCCESS',
      });
      onActionComplete();
    } catch (err: any) {
      onError(err.message || 'Manual ACK failed');
    }
  };

  const handleToggleControllerStatus = async () => {
    try {
      const newStatus = status.controller_status === 'ONLINE' ? 'OFFLINE' : 'ONLINE';
      await submitDeviceStatus({
        junction_id: status.junction_id,
        component_type: 'SIGNAL_CONTROLLER',
        identifier: 'controller',
        status: newStatus,
      });
      onActionComplete();
    } catch (err: any) {
      onError(err.message || 'Device status update failed');
    }
  };

  return (
    <div className="panel simulation-panel">
      <h3>Simulation & Hardware Fault Injection</h3>

      {/* Vehicle Event Injection */}
      <div className="sim-sub-section">
        <h4>1. Vehicle Sensor Simulator</h4>
        <div className="form-row">
          <label>Direction:</label>
          <select value={direction} onChange={(e) => setDirection(e.target.value as Direction)}>
            {DIRECTIONS.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>

        <div className="form-row">
          <label>Vehicle Type:</label>
          <select value={vehicleType} onChange={(e) => setVehicleType(e.target.value as VehicleType)}>
            {VEHICLE_TYPES.map((vt) => (
              <option key={vt} value={vt}>{vt}</option>
            ))}
          </select>
        </div>

        <div className="form-row">
          <label>Vehicle ID:</label>
          <input
            type="text"
            value={vehicleId}
            onChange={(e) => setVehicleId(e.target.value)}
          />
        </div>

        <div className="form-buttons-row">
          <button className="btn btn-primary" onClick={handleArrival} disabled={loading}>
            Simulate ARRIVAL
          </button>
          <button className="btn btn-secondary" onClick={handleClearance} disabled={loading}>
            Simulate CLEARANCE
          </button>
        </div>
      </div>

      {/* Controller Simulator Controls */}
      <div className="sim-sub-section">
        <h4>2. Hardware Controller Behavior</h4>
        <div className="form-row">
          <label>Simulation Mode:</label>
          <div className="mode-toggle-group">
            {['NORMAL', 'DELAYED', 'DROP', 'OFFLINE'].map((m) => (
              <button
                key={m}
                className={`btn btn-toggle ${simConfig.mode === m ? 'active' : ''}`}
                onClick={() => handleSimulatorModeChange(m)}
              >
                {m}
              </button>
            ))}
          </div>
        </div>

        <div className="form-row">
          <button className="btn btn-outline" onClick={handleToggleControllerStatus}>
            Toggle Controller Status (Current: {status.controller_status})
          </button>
          <button className="btn btn-outline" onClick={handleToggleAutoAck}>
            Auto-ACK: {simConfig.auto_ack ? 'ON' : 'OFF'}
          </button>
        </div>

        {status.pending_commands.length > 0 && !simConfig.auto_ack && (
          <div className="manual-ack-group">
            <h5>Manual ACK for Pending Commands:</h5>
            {status.pending_commands.map((cmd) => (
              <div key={cmd.command_id} className="manual-ack-row">
                <span>{cmd.command_id} ({cmd.direction} &rarr; {cmd.requested_state})</span>
                <button
                  className="btn btn-small btn-primary"
                  onClick={() => handleManualAck(cmd.command_id, cmd.direction, cmd.requested_state)}
                >
                  Send ACK
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};


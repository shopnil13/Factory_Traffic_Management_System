import React from 'react';
import { DeviceStatus, Direction, JunctionStatus } from '../types';

interface Props {
  status: JunctionStatus;
}

const DIRECTIONS: Direction[] = ['NORTH', 'SOUTH', 'EAST', 'WEST'];

export const AlertsPanel: React.FC<Props> = ({ status }) => {
  const getBadgeClass = (devStatus: DeviceStatus) => {
    switch (devStatus) {
      case 'ONLINE': return 'badge-online';
      case 'OFFLINE': return 'badge-offline';
      case 'DEGRADED': return 'badge-degraded';
      case 'WARNING': return 'badge-warning';
      default: return 'badge-unknown';
    }
  };

  // Collect active alerts
  const alerts: string[] = [];
  if (status.controller_status === 'OFFLINE') {
    alerts.push('Hardware Controller is OFFLINE: fail-safe all RED active.');
  }
  if (status.mode === 'DEGRADED') {
    alerts.push('Junction is running in DEGRADED fail-safe mode.');
  }
  if (status.active_emergencies.length > 0) {
    alerts.push(`Active Emergency Priority: ${status.active_emergencies.length} emergency vehicle(s) in queue.`);
  }
  DIRECTIONS.forEach((d) => {
    if (status.device_status[`sensor_${d}`] === 'OFFLINE') {
      alerts.push(`Sensor ${d} is OFFLINE: direction queue untrusted, using phantom score fallback.`);
    }
    if (status.desired_signals[d] !== status.actual_signals[d] && status.actual_signals[d] === 'UNKNOWN') {
      alerts.push(`Physical signal for ${d} is UNKNOWN (awaiting controller confirmation).`);
    }
  });

  return (
    <div className="panel alerts-panel">
      <h3>Hardware & Device Health</h3>
      
      <div className="devices-grid">
        <div className="device-item">
          <span>Signal Controller</span>
          <span className={`badge ${getBadgeClass(status.controller_status)}`}>
            {status.controller_status}
          </span>
        </div>
        {DIRECTIONS.map((d) => {
          const sStatus = status.device_status[`sensor_${d}`] || 'UNKNOWN';
          return (
            <div key={d} className="device-item">
              <span>Sensor {d}</span>
              <span className={`badge ${getBadgeClass(sStatus)}`}>
                {sStatus}
              </span>
            </div>
          );
        })}
      </div>

      {alerts.length > 0 && (
        <div className="active-alerts-list">
          <h4>System Warnings & Invariant Alerts ({alerts.length})</h4>
          <ul>
            {alerts.map((alert, idx) => (
              <li key={idx} className="alert-item">⚠️ {alert}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

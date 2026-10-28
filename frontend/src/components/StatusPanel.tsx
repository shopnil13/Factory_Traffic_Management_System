import React from 'react';
import { Direction, JunctionStatus } from '../types';

interface Props {
  status: JunctionStatus;
}

const DIRECTIONS: Direction[] = ['NORTH', 'SOUTH', 'EAST', 'WEST'];

export const StatusPanel: React.FC<Props> = ({ status }) => {
  return (
    <div className="panel status-panel">
      <h3>System State & Signals</h3>
      
      <div className="status-grid">
        <div className="status-stat">
          <label>Mode</label>
          <span className={`badge badge-mode-${status.mode.toLowerCase()}`}>{status.mode}</span>
        </div>
        <div className="status-stat">
          <label>Active Phase</label>
          <span className="value-highlight">{status.active_phase || 'None (All-Red)'}</span>
        </div>
        <div className="status-stat">
          <label>Stage Machine</label>
          <span>{status.stage} ({status.stage_status})</span>
        </div>
        <div className="status-stat">
          <label>Version</label>
          <span>v{status.version}</span>
        </div>
      </div>

      <h4>Desired vs Actual Physical Signals</h4>
      <table className="signals-table">
        <thead>
          <tr>
            <th>Direction</th>
            <th>Desired (Target)</th>
            <th>Actual (Reported ACK)</th>
            <th>Match</th>
          </tr>
        </thead>
        <tbody>
          {DIRECTIONS.map((dir) => {
            const des = status.desired_signals[dir] || 'RED';
            const act = status.actual_signals[dir] || 'UNKNOWN';
            const match = des === act;
            return (
              <tr key={dir} className={match ? 'row-match' : 'row-mismatch'}>
                <td><strong>{dir}</strong></td>
                <td><span className={`chip chip-${des.toLowerCase()}`}>{des}</span></td>
                <td><span className={`chip chip-${act.toLowerCase()}`}>{act}</span></td>
                <td>{match ? 'MATCH' : 'PENDING / MISMATCH'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {status.pending_commands.length > 0 && (
        <div className="pending-commands-section">
          <h4>Commands Awaiting Controller ACK ({status.pending_commands.length})</h4>
          <ul className="pending-list">
            {status.pending_commands.map((cmd) => (
              <li key={cmd.command_id}>
                <code>{cmd.command_id}</code>: {cmd.direction} &rarr; {cmd.requested_state} (Attempt {cmd.attempts})
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};


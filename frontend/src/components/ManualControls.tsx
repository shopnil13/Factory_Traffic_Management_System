import React, { useState } from 'react';
import { submitCommand } from '../api';
import { Direction, JunctionStatus } from '../types';

interface Props {
  status: JunctionStatus;
  onActionComplete: () => void;
  onError: (msg: string) => void;
}

const DIRECTIONS: Direction[] = ['NORTH', 'SOUTH', 'EAST', 'WEST'];

export const ManualControls: React.FC<Props> = ({ status, onActionComplete, onError }) => {
  const [operator, setOperator] = useState('admin_1');
  const [loading, setLoading] = useState(false);

  const isEmergency = status.mode === 'EMERGENCY';
  const isDegraded = status.mode === 'DEGRADED';
  const isLockedByOther =
    status.mode === 'MANUAL' &&
    !!status.manual.owner &&
    status.manual.owner !== operator;

  const isDisabled = isEmergency || isDegraded || isLockedByOther;

  let disabledReason = '';
  if (isEmergency) disabledReason = 'Disabled: Emergency preemption is currently active.';
  if (isDegraded) disabledReason = 'Disabled: Junction is in DEGRADED fail-safe state.';
  if (isLockedByOther) disabledReason = `Disabled: Manual lease locked by operator '${status.manual.owner}'.`;

  const handleManualRequest = async (direction: Direction) => {
    try {
      setLoading(true);
      await submitCommand(status.junction_id, {
        command_type: 'MANUAL_GREEN_REQUEST',
        direction,
        requested_by: operator,
      });
      onActionComplete();
    } catch (err: any) {
      onError(err.message || 'Failed to submit manual command');
    } finally {
      setLoading(false);
    }
  };

  const handleReturnToAutomatic = async () => {
    try {
      setLoading(true);
      await submitCommand(status.junction_id, {
        command_type: 'RETURN_TO_AUTOMATIC',
        requested_by: operator,
      });
      onActionComplete();
    } catch (err: any) {
      onError(err.message || 'Failed to return to automatic mode');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="panel manual-panel">
      <h3>Operator Override Controls</h3>
      
      <div className="operator-input-row">
        <label>Operator ID:</label>
        <input
          type="text"
          value={operator}
          onChange={(e) => setOperator(e.target.value)}
          placeholder="e.g. admin_1"
        />
      </div>

      {disabledReason && <p className="warning-text">{disabledReason}</p>}

      <div className="direction-buttons-grid">
        {DIRECTIONS.map((dir) => (
          <button
            key={dir}
            className="btn btn-primary"
            disabled={isDisabled || loading}
            onClick={() => handleManualRequest(dir)}
          >
            Force GREEN: {dir}
          </button>
        ))}
      </div>

      <div className="release-row">
        <button
          className="btn btn-secondary"
          disabled={loading || status.mode !== 'MANUAL'}
          onClick={handleReturnToAutomatic}
        >
          Return to Automatic Sequencing
        </button>
      </div>
    </div>
  );
};


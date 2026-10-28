import React from 'react';
import { Direction, JunctionStatus, Signal } from '../types';

interface Props {
  status: JunctionStatus;
}

const SIGNAL_COLORS: Record<Signal, string> = {
  GREEN: '#22c55e',
  YELLOW: '#eab308',
  RED: '#ef4444',
  UNKNOWN: '#6b7280',
};

export const IntersectionView: React.FC<Props> = ({ status }) => {
  const getSignalColor = (dir: Direction) => {
    const act = status.actual_signals[dir] || 'UNKNOWN';
    return SIGNAL_COLORS[act] || '#6b7280';
  };

  const isMismatch = (dir: Direction) => {
    return status.desired_signals[dir] !== status.actual_signals[dir];
  };

  const getQueue = (dir: Direction) => {
    return status.queues[dir] || 0;
  };

  return (
    <div className="intersection-container">
      <h3>Intersection Physical Status</h3>
      <div className="intersection-svg-wrapper">
        <svg viewBox="0 0 400 400" className="intersection-svg">
          {/* Background roads */}
          <rect x="0" y="0" width="400" height="400" fill="#1e293b" />
          
          {/* North-South Road */}
          <rect x="140" y="0" width="120" height="400" fill="#334155" />
          {/* East-West Road */}
          <rect x="0" y="140" width="400" height="120" fill="#334155" />

          {/* Road center road markings */}
          <line x1="200" y1="0" x2="200" y2="130" stroke="#facc15" strokeWidth="2" strokeDasharray="8 8" />
          <line x1="200" y1="270" x2="200" y2="400" stroke="#facc15" strokeWidth="2" strokeDasharray="8 8" />
          <line x1="0" y1="200" x2="130" y2="200" stroke="#facc15" strokeWidth="2" strokeDasharray="8 8" />
          <line x1="270" y1="200" x2="400" y2="200" stroke="#facc15" strokeWidth="2" strokeDasharray="8 8" />

          {/* Central Conflict Junction Box */}
          <rect x="140" y="140" width="120" height="120" fill="#1e293b" stroke="#64748b" strokeWidth="1" />
          <text x="200" y="195" textAnchor="middle" fill="#94a3b8" fontSize="11" fontWeight="bold">
            STAGE: {status.stage}
          </text>
          <text x="200" y="215" textAnchor="middle" fill="#60a5fa" fontSize="10">
            {status.active_phase || 'TRANSITION'}
          </text>

          {/* NORTH Signal Arm */}
          <g transform="translate(160, 40)">
            <rect
              x="0"
              y="0"
              width="80"
              height="30"
              rx="6"
              fill={getSignalColor('NORTH')}
              stroke={isMismatch('NORTH') ? '#facc15' : '#0f172a'}
              strokeWidth={isMismatch('NORTH') ? '3' : '1'}
              strokeDasharray={isMismatch('NORTH') ? '4 3' : 'none'}
            />
            <text x="40" y="20" textAnchor="middle" fill="#ffffff" fontWeight="bold" fontSize="13">
              NORTH: {status.actual_signals.NORTH}
            </text>
          </g>
          {/* North Queue badge */}
          <rect x="175" y="80" width="50" height="20" rx="10" fill="#0f172a" stroke="#475569" />
          <text x="200" y="94" textAnchor="middle" fill="#38bdf8" fontSize="11" fontWeight="bold">
            {getQueue('NORTH')} wait
          </text>

          {/* SOUTH Signal Arm */}
          <g transform="translate(160, 330)">
            <rect
              x="0"
              y="0"
              width="80"
              height="30"
              rx="6"
              fill={getSignalColor('SOUTH')}
              stroke={isMismatch('SOUTH') ? '#facc15' : '#0f172a'}
              strokeWidth={isMismatch('SOUTH') ? '3' : '1'}
              strokeDasharray={isMismatch('SOUTH') ? '4 3' : 'none'}
            />
            <text x="40" y="20" textAnchor="middle" fill="#ffffff" fontWeight="bold" fontSize="13">
              SOUTH: {status.actual_signals.SOUTH}
            </text>
          </g>
          {/* South Queue badge */}
          <rect x="175" y="300" width="50" height="20" rx="10" fill="#0f172a" stroke="#475569" />
          <text x="200" y="314" textAnchor="middle" fill="#38bdf8" fontSize="11" fontWeight="bold">
            {getQueue('SOUTH')} wait
          </text>

          {/* WEST Signal Arm */}
          <g transform="translate(30, 160)">
            <rect
              x="0"
              y="0"
              width="30"
              height="80"
              rx="6"
              fill={getSignalColor('WEST')}
              stroke={isMismatch('WEST') ? '#facc15' : '#0f172a'}
              strokeWidth={isMismatch('WEST') ? '3' : '1'}
              strokeDasharray={isMismatch('WEST') ? '4 3' : 'none'}
            />
            <text x="15" y="45" textAnchor="middle" fill="#ffffff" fontWeight="bold" fontSize="11" transform="rotate(-90 15 45)">
              WEST: {status.actual_signals.WEST}
            </text>
          </g>
          {/* West Queue badge */}
          <rect x="70" y="190" width="50" height="20" rx="10" fill="#0f172a" stroke="#475569" />
          <text x="95" y="204" textAnchor="middle" fill="#38bdf8" fontSize="11" fontWeight="bold">
            {getQueue('WEST')} wait
          </text>

          {/* EAST Signal Arm */}
          <g transform="translate(340, 160)">
            <rect
              x="0"
              y="0"
              width="30"
              height="80"
              rx="6"
              fill={getSignalColor('EAST')}
              stroke={isMismatch('EAST') ? '#facc15' : '#0f172a'}
              strokeWidth={isMismatch('EAST') ? '3' : '1'}
              strokeDasharray={isMismatch('EAST') ? '4 3' : 'none'}
            />
            <text x="15" y="45" textAnchor="middle" fill="#ffffff" fontWeight="bold" fontSize="11" transform="rotate(90 15 45)">
              EAST: {status.actual_signals.EAST}
            </text>
          </g>
          {/* East Queue badge */}
          <rect x="280" y="190" width="50" height="20" rx="10" fill="#0f172a" stroke="#475569" />
          <text x="305" y="204" textAnchor="middle" fill="#38bdf8" fontSize="11" fontWeight="bold">
            {getQueue('EAST')} wait
          </text>
        </svg>
      </div>

      <div className="intersection-legend">
        <span className="legend-item"><span className="color-box" style={{ background: '#22c55e' }} /> GREEN</span>
        <span className="legend-item"><span className="color-box" style={{ background: '#eab308' }} /> YELLOW</span>
        <span className="legend-item"><span className="color-box" style={{ background: '#ef4444' }} /> RED</span>
        <span className="legend-item"><span className="color-box" style={{ background: '#6b7280' }} /> UNKNOWN</span>
        <span className="legend-item"><span className="color-box-dashed" /> Desired != Actual</span>
      </div>
    </div>
  );
};

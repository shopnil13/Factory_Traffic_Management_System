import React from 'react';

interface Props {
  connected: boolean;
  lastUpdated?: string | null;
  onRefresh: () => void;
}

export const ConnectionBanner: React.FC<Props> = ({ connected, lastUpdated, onRefresh }) => {
  return (
    <div className={`connection-banner ${connected ? 'connected' : 'disconnected'}`}>
      <div className="status-indicator">
        <span className="dot" />
        <span className="text">
          {connected ? 'LIVE STREAM ACTIVE (SSE)' : 'DISCONNECTED — RECONNECTING...'}
        </span>
      </div>
      <div className="timestamp-info">
        {lastUpdated && <span>Last sync: {new Date(lastUpdated).toLocaleTimeString()}</span>}
        <button onClick={onRefresh} className="btn-small">Refresh</button>
      </div>
    </div>
  );
};


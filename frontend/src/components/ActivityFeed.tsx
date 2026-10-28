import React from 'react';
import { AuditLogItem } from '../types';

interface Props {
  logs: AuditLogItem[];
  onRefresh: () => void;
}

export const ActivityFeed: React.FC<Props> = ({ logs, onRefresh }) => {
  return (
    <div className="panel activity-panel">
      <div className="panel-header">
        <h3>Live Audit & Event Feed ({logs.length})</h3>
        <button className="btn-small" onClick={onRefresh}>Refresh Feed</button>
      </div>

      <div className="feed-list">
        {logs.length === 0 ? (
          <p className="no-data-text">No audit events recorded yet.</p>
        ) : (
          logs.map((item) => (
            <div key={item.id} className="feed-item">
              <div className="feed-item-header">
                <span className="feed-event-type">{item.event_type}</span>
                <span className="feed-time">
                  {new Date(item.server_ts).toLocaleTimeString()}
                </span>
              </div>
              <div className="feed-message">{item.message}</div>
              <div className="feed-meta">
                {item.direction && <span className="meta-tag">Dir: {item.direction}</span>}
                {item.mode && <span className="meta-tag">Mode: {item.mode}</span>}
                {item.correlation_id && (
                  <span className="meta-tag">Corr: {item.correlation_id.substring(0, 16)}...</span>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

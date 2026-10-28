import React, { useEffect, useState, useCallback } from 'react';
import { fetchHistory, fetchJunctions, fetchJunctionStatus } from './api';
import { ActivityFeed } from './components/ActivityFeed';
import { AlertsPanel } from './components/AlertsPanel';
import { ConnectionBanner } from './components/ConnectionBanner';
import { IntersectionView } from './components/IntersectionView';
import { ManualControls } from './components/ManualControls';
import { ModeBanner } from './components/ModeBanner';
import { SimulationPanel } from './components/SimulationPanel';
import { StatusPanel } from './components/StatusPanel';
import { AuditLogItem, JunctionStatus } from './types';

export const App: React.FC = () => {
  const [junctions, setJunctions] = useState<any[]>([]);
  const [selectedJunctionId, setSelectedJunctionId] = useState<string>('junction-a');
  const [status, setStatus] = useState<JunctionStatus | null>(null);
  const [history, setHistory] = useState<AuditLogItem[]>([]);
  const [connected, setConnected] = useState<boolean>(false);
  const [errorToast, setErrorToast] = useState<string | null>(null);

  // Load junctions list
  const loadJunctions = async () => {
    try {
      const list = await fetchJunctions();
      setJunctions(list);
      if (list.length > 0 && !list.some((j) => j.id === selectedJunctionId)) {
        setSelectedJunctionId(list[0].id);
      }
    } catch (e: any) {
      console.error('Failed to load junctions', e);
    }
  };

  // Load junction status and history
  const loadData = useCallback(async () => {
    if (!selectedJunctionId) return;
    try {
      const [st, hist] = await Promise.all([
        fetchJunctionStatus(selectedJunctionId),
        fetchHistory(selectedJunctionId, 40),
      ]);
      setStatus(st);
      setHistory(hist);
    } catch (e: any) {
      console.error('Failed to load junction data', e);
    }
  }, [selectedJunctionId]);

  useEffect(() => {
    loadJunctions();
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Setup Server-Sent Events (SSE)
  useEffect(() => {
    let eventSource: EventSource | null = null;
    let fallbackInterval: ReturnType<typeof setInterval> | null = null;

    const connectSSE = () => {
      eventSource = new EventSource('/api/stream');

      eventSource.onopen = () => {
        setConnected(true);
      };

      eventSource.addEventListener('junction_updated', (e: MessageEvent) => {
        try {
          const parsed = JSON.parse(e.data);
          if (parsed.junction_id === selectedJunctionId && parsed.data) {
            setStatus(parsed.data);
          }
        } catch (err) {
          console.error('Error parsing SSE junction_updated', err);
        }
      });

      eventSource.onerror = () => {
        setConnected(false);
        eventSource?.close();
        // Fallback polling every 2 seconds when SSE is disconnected
        if (!fallbackInterval) {
          fallbackInterval = setInterval(loadData, 2000);
        }
        setTimeout(connectSSE, 4000);
      };
    };

    connectSSE();

    // 1-second refresh on history
    const historyInterval = setInterval(() => {
      if (selectedJunctionId) {
        fetchHistory(selectedJunctionId, 40).then(setHistory).catch(() => {});
      }
    }, 2000);

    return () => {
      eventSource?.close();
      if (fallbackInterval) clearInterval(fallbackInterval);
      clearInterval(historyInterval);
    };
  }, [selectedJunctionId, loadData]);

  const showToast = (msg: string) => {
    setErrorToast(msg);
    setTimeout(() => setErrorToast(null), 5000);
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="header-title">
          <h1>Factory Traffic Management System</h1>
          <span className="subtitle">Real-Time Industrial Intersection Traffic Controller</span>
        </div>
        <div className="junction-switcher">
          <label>Junction:</label>
          <select
            value={selectedJunctionId}
            onChange={(e) => setSelectedJunctionId(e.target.value)}
          >
            {junctions.map((j) => (
              <option key={j.id} value={j.id}>{j.name} ({j.id})</option>
            ))}
          </select>
        </div>
      </header>

      <ConnectionBanner
        connected={connected}
        lastUpdated={status?.updated_at}
        onRefresh={loadData}
      />

      {errorToast && (
        <div className="toast-notification">
          <span>{errorToast}</span>
          <button onClick={() => setErrorToast(null)}>&times;</button>
        </div>
      )}

      {status ? (
        <main className="dashboard-content">
          <ModeBanner status={status} />

          <div className="main-grid">
            {/* Left Column: Intersection Visual & Manual Controls */}
            <div className="grid-column">
              <IntersectionView status={status} />
              <ManualControls
                status={status}
                onActionComplete={loadData}
                onError={showToast}
              />
            </div>

            {/* Middle Column: Status & Simulation Fault Injection */}
            <div className="grid-column">
              <StatusPanel status={status} />
              <SimulationPanel
                status={status}
                onActionComplete={loadData}
                onError={showToast}
              />
            </div>

            {/* Right Column: Hardware Health & Live Feed */}
            <div className="grid-column">
              <AlertsPanel status={status} />
              <ActivityFeed logs={history} onRefresh={loadData} />
            </div>
          </div>
        </main>
      ) : (
        <div className="loading-state">
          <p>Connecting to Junction controller...</p>
        </div>
      )}
    </div>
  );
};

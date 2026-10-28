import React, { useEffect, useState } from 'react';
import { JunctionStatus } from '../types';

interface Props {
  status: JunctionStatus;
}

export const ModeBanner: React.FC<Props> = ({ status }) => {
  const [remainingSecs, setRemainingSecs] = useState<number | null>(null);

  useEffect(() => {
    if (status.mode === 'MANUAL' && status.manual.expires_at) {
      const updateTime = () => {
        const diff = Math.max(0, Math.round((new Date(status.manual.expires_at!).getTime() - Date.now()) / 1000));
        setRemainingSecs(diff);
      };
      updateTime();
      const interval = setInterval(updateTime, 1000);
      return () => clearInterval(interval);
    } else {
      setRemainingSecs(null);
    }
  }, [status.mode, status.manual.expires_at]);

  if (status.mode === 'EMERGENCY') {
    const activeEm = status.active_emergencies[0];
    return (
      <div className="banner banner-emergency">
        <div className="banner-title">EMERGENCY VEHICLE PREEMPTION ACTIVE</div>
        <div className="banner-desc">
          Emergency vehicle {activeEm ? `${activeEm.vehicle_id} approaching from ${activeEm.direction}` : 'active'}.
          Junction is safely sequencing to clear the path. Manual overrides are suspended.
        </div>
      </div>
    );
  }

  if (status.mode === 'MANUAL') {
    return (
      <div className="banner banner-manual">
        <div className="banner-title">MANUAL OPERATOR OVERRIDE ACTIVE</div>
        <div className="banner-desc">
          Phase held by operator <strong>{status.manual.owner || 'Admin'}</strong>
          {status.manual.direction && ` (Requested direction: ${status.manual.direction})`}.
          {remainingSecs !== null && (
            <span className="lease-timer"> Lease auto-expires in: <strong>{remainingSecs}s</strong></span>
          )}
        </div>
      </div>
    );
  }

  if (status.mode === 'DEGRADED') {
    return (
      <div className="banner banner-degraded">
        <div className="banner-title">FAIL-SAFE DEGRADED STATE ACTIVE</div>
        <div className="banner-desc">
          Hardware controller or communication fault detected. All signals forced to physical RED.
          Normal sequencing will automatically resume after controller re-sync confirmation.
        </div>
      </div>
    );
  }

  return null;
};


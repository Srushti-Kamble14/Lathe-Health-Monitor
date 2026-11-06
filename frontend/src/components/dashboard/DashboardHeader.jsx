import { Link } from 'react-router-dom';
import HealthIndicator from './HealthIndicator.jsx';

export default function DashboardHeader({
  machines,
  machineId,
  onMachineChange,
  health,
  refreshing,
  onRefresh,
  lastUpdated,
}) {
  return (
    <header className="dashboard-header">
      <Link to="/" className="dashboard-brand" aria-label="Lathe Health Monitor home">
        <span className="dashboard-brand__mark" aria-hidden="true">LH</span>
        <span>
          <strong>LATHE HEALTH</strong>
          <small>Industrial monitoring</small>
        </span>
      </Link>

      <div className="dashboard-header__controls">
        <label className="machine-select">
          <span>Machine</span>
          <select
            value={machineId}
            onChange={(event) => onMachineChange(event.target.value)}
            disabled={!machines.length}
          >
            {!machines.length && <option value="">No machines</option>}
            {machines.map((machine) => (
              <option key={machine.id} value={machine.id}>
                {machine.name} · {machine.machine_code}
              </option>
            ))}
          </select>
        </label>

        <div className="header-health" aria-label="Service connections">
          <HealthIndicator label="Backend" status={health.backend} />
          <HealthIndicator label="Database" status={health.database} />
          <HealthIndicator label="ML" status={health.ml} />
        </div>

        <div className="refresh-control">
          <span className="refresh-control__updated">
            Last updated: {lastUpdated || '—'}
          </span>
          <button
            className="button button--refresh"
            type="button"
            onClick={onRefresh}
            disabled={refreshing}
            aria-label="Refresh latest monitoring data and service health"
          >
            <span aria-hidden="true">{refreshing ? '…' : '↻'}</span>
            <span>{refreshing ? 'Refreshing' : 'Refresh'}</span>
          </button>
        </div>
      </div>
    </header>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AnomalyPanel from '../components/dashboard/AnomalyPanel.jsx';
import DashboardHeader from '../components/dashboard/DashboardHeader.jsx';
import SensorCharts from '../components/dashboard/SensorCharts.jsx';
import SensorKpiGrid from '../components/dashboard/SensorKpiGrid.jsx';
import SessionSelector from '../components/dashboard/SessionSelector.jsx';
import StateMessage from '../components/common/StateMessage.jsx';
import {
  getAnomalies,
  getBackendHealth,
  getDatabaseHealth,
  getLatestAnomaly,
  getLatestReading,
  getMachines,
  getMLReadiness,
  getReadings,
  getSessions,
} from '../services/api.js';

const POLL_INTERVAL_MS = 15000;
const HISTORY_LIMIT = 500;
const INITIAL_HEALTH = { backend: 'checking', database: 'checking', ml: 'checking' };

function formatDate(value, options = {}) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    dateStyle: options.dateStyle || 'medium',
    timeStyle: options.timeStyle || 'medium',
  }).format(date);
}

function MachineOverview({ machine, reading, session }) {
  if (!machine) {
    return (
      <section className="machine-overview panel">
        <StateMessage>No machine selected.</StateMessage>
      </section>
    );
  }

  return (
    <section className="machine-overview panel" aria-labelledby="machine-overview-title">
      <div className="machine-overview__heading">
        <div>
          <p className="eyebrow">Machine overview</p>
          <h1 id="machine-overview-title">{machine.name}</h1>
          <p className="machine-code">{machine.machine_code} <span>·</span> {machine.id}</p>
        </div>
        <div className="machine-status">
          <span className="machine-status__label">Machine status</span>
          <span className="machine-status__value">{machine.status || 'Unavailable'}</span>
        </div>
      </div>
      <div className="machine-overview__details">
        <div>
          <span>Selected session</span>
          <strong>{session ? `Session ${session.session_number}` : 'No session selected'}</strong>
        </div>
        <div>
          <span>Session start · UTC</span>
          <strong>{session ? formatDate(session.start_time) : '—'}</strong>
        </div>
        <div>
          <span>Session end · UTC</span>
          <strong>{session ? formatDate(session.end_time) : '—'}</strong>
        </div>
        <div>
          <span>Session reading count</span>
          <strong>{session?.sample_count ?? '—'}</strong>
        </div>
        <div>
          <span>Last reading · UTC</span>
          <strong>{formatDate(reading?.timestamp)}</strong>
        </div>
      </div>
    </section>
  );
}

export default function DashboardPage() {
  const [machines, setMachines] = useState([]);
  const [machineId, setMachineId] = useState('');
  const [machineLoading, setMachineLoading] = useState(true);
  const [machineError, setMachineError] = useState('');
  const [sessions, setSessions] = useState([]);
  const [selectedSessionId, setSelectedSessionId] = useState('');
  const [sessionLoading, setSessionLoading] = useState(false);
  const [sessionError, setSessionError] = useState('');
  const [latestReading, setLatestReading] = useState(null);
  const [latestAnomaly, setLatestAnomaly] = useState(null);
  const [latestLoading, setLatestLoading] = useState(false);
  const [readingError, setReadingError] = useState('');
  const [latestAnomalyError, setLatestAnomalyError] = useState('');
  const [readings, setReadings] = useState([]);
  const [anomalies, setAnomalies] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [readingHistoryError, setReadingHistoryError] = useState('');
  const [anomalyHistoryError, setAnomalyHistoryError] = useState('');
  const [health, setHealth] = useState(INITIAL_HEALTH);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState('');
  const latestRequest = useRef(null);
  const healthRequest = useRef(null);
  const currentMachineId = useRef(machineId);
  currentMachineId.current = machineId;

  const selectedMachine = useMemo(
    () => machines.find((machine) => machine.id === machineId) || null,
    [machines, machineId],
  );
  const selectedSession = useMemo(
    () => sessions.find((session) => session.id === selectedSessionId) || null,
    [sessions, selectedSessionId],
  );

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setMachineLoading(true);
    setMachineError('');
    getMachines({ signal: controller.signal })
      .then((data) => {
        if (!active) return;
        setMachines(data);
        setMachineId((current) => (
          data.some((machine) => machine.id === current) ? current : data[0]?.id || ''
        ));
      })
      .catch((error) => {
        if (!active) return;
        setMachineError(error.message);
        setMachines([]);
        setMachineId('');
      })
      .finally(() => {
        if (active) setMachineLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  const refreshHealth = useCallback(async () => {
    healthRequest.current?.abort();
    const controller = new AbortController();
    healthRequest.current = controller;
    const checks = [
      ['backend', getBackendHealth],
      ['database', getDatabaseHealth],
      ['ml', getMLReadiness],
    ];
    const results = await Promise.allSettled(
      checks.map(([, check]) => check({ signal: controller.signal })),
    );
    if (healthRequest.current !== controller) return;
    setHealth(Object.fromEntries(
      checks.map(([key], index) => [
        key,
        results[index].status === 'fulfilled'
          ? key === 'ml' ? 'ready' : 'connected'
          : 'unavailable',
      ]),
    ));
    healthRequest.current = null;
  }, []);

  useEffect(() => {
    refreshHealth();
    const timer = setInterval(refreshHealth, POLL_INTERVAL_MS);
    return () => {
      clearInterval(timer);
      healthRequest.current?.abort();
    };
  }, [refreshHealth]);

  const refreshLatest = useCallback(async ({ showRefreshing = false, includeHealth = true } = {}) => {
    if (!machineId || latestRequest.current?.machineId === machineId) return;
    latestRequest.current?.controller.abort();
    const controller = new AbortController();
    latestRequest.current = { machineId, controller };
    if (showRefreshing) setRefreshing(true);
    setLatestLoading(true);

    const jobs = await Promise.allSettled([
      getLatestReading(machineId, { signal: controller.signal }),
      getLatestAnomaly(machineId, { signal: controller.signal }),
      ...(includeHealth ? [refreshHealth()] : []),
    ]);

    if (
      currentMachineId.current !== machineId
      || latestRequest.current?.controller !== controller
    ) {
      return;
    }

    if (jobs[0].status === 'fulfilled') {
      setLatestReading(jobs[0].value);
      setReadingError('');
    } else {
      setReadingError(jobs[0].reason.message);
    }

    if (jobs[1].status === 'fulfilled') {
      setLatestAnomaly(jobs[1].value);
      setLatestAnomalyError('');
    } else {
      setLatestAnomalyError(jobs[1].reason.message);
    }

    setLastUpdated(formatDate(new Date().toISOString()));
    setLatestLoading(false);
    setRefreshing(false);
    latestRequest.current = null;
  }, [machineId, refreshHealth]);

  useEffect(() => {
    if (!machineId) {
      setSessions([]);
      setSelectedSessionId('');
      setLatestReading(null);
      setLatestAnomaly(null);
      setReadingError('');
      setLatestAnomalyError('');
      setRefreshing(false);
      return undefined;
    }
    const controller = new AbortController();
    let active = true;
    setSessionLoading(true);
    setSessionError('');
    setSessions([]);
    setSelectedSessionId('');
    setLatestReading(null);
    setLatestAnomaly(null);
    setReadings([]);
    setAnomalies([]);

    getSessions(machineId, { signal: controller.signal })
      .then((data) => {
        if (!active) return;
        setSessions(data);
        setSelectedSessionId(data[0]?.id || '');
      })
      .catch((error) => {
        if (!active) return;
        setSessionError(error.message);
        setSessions([]);
      })
      .finally(() => {
        if (active) setSessionLoading(false);
      });

    refreshLatest({ includeHealth: false });
    return () => {
      active = false;
      controller.abort();
    };
  }, [machineId, refreshLatest]);

  useEffect(() => {
    if (!machineId || !selectedSession) {
      setReadings([]);
      setAnomalies([]);
      setReadingHistoryError('');
      setAnomalyHistoryError('');
      return undefined;
    }

    const controller = new AbortController();
    let active = true;
    setHistoryLoading(true);
    setReadingHistoryError('');
    setAnomalyHistoryError('');
    setReadings([]);
    setAnomalies([]);

    const filters = {
      machineId,
      start: selectedSession.start_time,
      end: selectedSession.end_time,
      limit: HISTORY_LIMIT,
      offset: 0,
    };
    Promise.allSettled([
      getReadings(filters, { signal: controller.signal }),
      getAnomalies(filters, { signal: controller.signal }),
    ]).then(([readingResult, anomalyResult]) => {
      if (!active) return;
      if (readingResult.status === 'fulfilled') {
        setReadings([...readingResult.value.data].reverse());
        setReadingHistoryError('');
      } else {
        setReadings([]);
        setReadingHistoryError(readingResult.reason.message);
      }
      if (anomalyResult.status === 'fulfilled') {
        setAnomalies([...anomalyResult.value.data].reverse());
        setAnomalyHistoryError('');
      } else {
        setAnomalies([]);
        setAnomalyHistoryError(anomalyResult.reason.message);
      }
    }).finally(() => {
      if (active) setHistoryLoading(false);
    });

    return () => {
      active = false;
      controller.abort();
    };
  }, [machineId, selectedSession]);

  useEffect(() => {
    if (!machineId) return undefined;
    const timer = setInterval(() => {
      refreshLatest({ includeHealth: false });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [machineId, refreshLatest]);

  useEffect(() => () => {
    latestRequest.current?.controller.abort();
    healthRequest.current?.abort();
  }, []);

  const onRefresh = useCallback(() => {
    refreshLatest({ showRefreshing: true, includeHealth: true });
  }, [refreshLatest]);

  return (
    <main className="dashboard">
      <DashboardHeader
        machines={machines}
        machineId={machineId}
        onMachineChange={setMachineId}
        health={health}
        refreshing={refreshing}
        onRefresh={onRefresh}
        lastUpdated={lastUpdated}
      />

      <div className="dashboard-content">
        <div className="dashboard-title-row">
          <div>
            <p className="eyebrow">Monitoring console</p>
            <h2>Machine health overview</h2>
          </div>
          <span className="utc-note">All displayed timestamps use UTC</span>
        </div>

        {machineLoading ? (
          <StateMessage>Loading machine data…</StateMessage>
        ) : machineError ? (
          <StateMessage variant="error" role="alert">{machineError}</StateMessage>
        ) : !machines.length ? (
          <StateMessage>No machines available.</StateMessage>
        ) : (
          <>
            <MachineOverview
              machine={selectedMachine}
              reading={latestReading}
              session={selectedSession}
            />

            {sessionError && (
              <StateMessage variant="error" role="alert">{sessionError}</StateMessage>
            )}
            <div className="session-toolbar">
              <SessionSelector
                sessions={sessions}
                selectedSessionId={selectedSessionId}
                onChange={setSelectedSessionId}
                loading={sessionLoading}
              />
              {selectedSession && (
                <span className="session-samples">
                  {selectedSession.sample_count} recorded samples in session
                </span>
              )}
            </div>
            {!sessionLoading && !sessions.length && !sessionError && (
              <StateMessage>No monitoring sessions available.</StateMessage>
            )}

            {readingError && (
              <StateMessage variant="error" role="alert">
                Unable to load latest sensor readings.
              </StateMessage>
            )}
            <SensorKpiGrid
              reading={latestReading}
              loading={latestLoading}
              error={readingError}
            />

            <SensorCharts
              readings={readings}
              loading={historyLoading}
              error={readingHistoryError}
              session={selectedSession}
            />

            <AnomalyPanel
              latest={latestAnomaly}
              loading={latestLoading}
              error={latestAnomalyError || anomalyHistoryError}
              anomalies={anomalies}
            />
            <footer className="dashboard-footer">
              Monitoring data and anomaly statuses are displayed as returned by the backend.
              Anomaly statuses indicate unusual behavior, not a confirmed machine fault.
            </footer>
          </>
        )}
      </div>
    </main>
  );
}

import StateMessage from '../common/StateMessage.jsx';

function formatDate(value) {
  if (!value) return 'Time unavailable';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Time unavailable';
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    dateStyle: 'medium',
    timeStyle: 'medium',
  }).format(date);
}

function formatScore(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return Number(value).toFixed(4);
}

export default function AnomalyPanel({ latest, loading, error, anomalies }) {
  const counts = anomalies.reduce(
    (result, anomaly) => {
      if (Object.hasOwn(result, anomaly.anomaly_status)) {
        result[anomaly.anomaly_status] += 1;
      }
      return result;
    },
    { NORMAL: 0, WARNING: 0, ANOMALOUS: 0 },
  );

  return (
    <section className="anomaly-layout" aria-label="Persisted anomaly monitoring">
      <article className="panel anomaly-summary">
        <div className="section-heading section-heading--compact">
          <div>
            <p className="eyebrow">Model output</p>
            <h2>Latest anomaly result</h2>
          </div>
          <span className="panel-mark" aria-hidden="true">AI</span>
        </div>
        {loading && !latest ? (
          <StateMessage>Loading anomaly result…</StateMessage>
        ) : error && !latest ? (
          <StateMessage variant="error" role="alert">{error}</StateMessage>
        ) : !latest ? (
          <StateMessage>No anomaly result available.</StateMessage>
        ) : (
          <>
            <div className="anomaly-score-row">
              <span className="anomaly-score">{formatScore(latest.anomaly_score)}</span>
              <span className={`status-badge status-badge--${String(latest.anomaly_status || '').toLowerCase()}`}>
                {latest.anomaly_status || 'Status unavailable'}
              </span>
            </div>
            <p className="anomaly-caption">Anomaly score · higher scores indicate more unusual behavior</p>
            <dl className="anomaly-metadata">
              <div><dt>Timestamp (UTC)</dt><dd>{formatDate(latest.timestamp)}</dd></div>
              <div><dt>Model</dt><dd>{latest.model_name || 'Unavailable'}</dd></div>
              <div><dt>Version</dt><dd>{latest.model_version || 'Unavailable'}</dd></div>
            </dl>
            <p className="scope-note">
              Anomaly status indicates unusual sensor behavior; it does not identify a physical fault.
            </p>
          </>
        )}
      </article>

      <article className="panel anomaly-history">
        <div className="section-heading section-heading--compact">
          <div>
            <p className="eyebrow">Persisted results</p>
            <h2>Anomaly timeline</h2>
          </div>
          <span className="section-note">Selected session · max 500 rows</span>
        </div>
        {error && !anomalies.length ? (
          <StateMessage variant="error" role="alert">{error}</StateMessage>
        ) : !anomalies.length ? (
          <StateMessage>No anomaly results available for this session.</StateMessage>
        ) : (
          <>
            <div className="anomaly-counts" aria-label="Status counts in loaded persisted results">
              {[
                ['NORMAL', counts.NORMAL],
                ['WARNING', counts.WARNING],
                ['ANOMALOUS', counts.ANOMALOUS],
              ].map(([status, count]) => (
                <div className={`anomaly-count anomaly-count--${status.toLowerCase()}`} key={status}>
                  <span>{status}</span>
                  <strong>{count}</strong>
                </div>
              ))}
            </div>
            <p className="section-note anomaly-history__note">
              Counts reflect retrieved persisted results only, not production incident totals.
            </p>
            <ol className="anomaly-timeline">
              {anomalies.map((item) => (
                <li className="anomaly-timeline__item" key={item.id}>
                  <span
                    className={`anomaly-timeline__marker anomaly-timeline__marker--${String(item.anomaly_status || '').toLowerCase()}`}
                    aria-hidden="true"
                  />
                  <time dateTime={item.timestamp}>{formatDate(item.timestamp)}</time>
                  <span className={`status-badge status-badge--${String(item.anomaly_status || '').toLowerCase()}`}>
                    {item.anomaly_status || 'Status unavailable'}
                  </span>
                  <strong>{formatScore(item.anomaly_score)}</strong>
                </li>
              ))}
            </ol>
          </>
        )}
      </article>
    </section>
  );
}

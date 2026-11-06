const SENSOR_GROUPS = [
  {
    key: 'current',
    title: 'Current',
    metrics: [
      ['current_l1', 'L1'],
      ['current_l2', 'L2'],
      ['current_l3', 'L3'],
    ],
  },
  {
    key: 'voltage',
    title: 'Voltage',
    metrics: [
      ['voltage_l1', 'L1'],
      ['voltage_l2', 'L2'],
      ['voltage_l3', 'L3'],
    ],
  },
  {
    key: 'vibration',
    title: 'Vibration',
    metrics: [
      ['vibration_x', 'X'],
      ['vibration_y', 'Y'],
      ['vibration_z', 'Z'],
    ],
  },
  {
    key: 'temperature',
    title: 'Temperature',
    metrics: [
      ['tool_temperature', 'Tool'],
      ['ambient_temperature', 'Ambient'],
    ],
  },
];

function formatValue(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return Number(value).toLocaleString('en-GB', { maximumFractionDigits: 3 });
}

export default function SensorKpiGrid({ reading, loading, error }) {
  return (
    <section className="sensor-kpi-grid" aria-label="Latest sensor readings">
      {SENSOR_GROUPS.map((group) => (
        <article className="sensor-card" key={group.key}>
          <div className="sensor-card__heading">
            <h3>{group.title}</h3>
            <span className="sensor-card__icon" aria-hidden="true">
              {group.key === 'temperature' ? '°' : group.key === 'vibration' ? '〰' : '∿'}
            </span>
          </div>
          {loading && !reading ? (
            <p className="sensor-card__state">Loading readings…</p>
          ) : error && !reading ? (
            <p className="sensor-card__state sensor-card__state--error">Readings unavailable</p>
          ) : !reading ? (
            <p className="sensor-card__state">No sensor readings available.</p>
          ) : (
            <dl className="sensor-values">
              {group.metrics.map(([field, label]) => (
                <div className="sensor-values__item" key={field}>
                  <dt>{label}</dt>
                  <dd>{formatValue(reading[field])}</dd>
                </div>
              ))}
            </dl>
          )}
        </article>
      ))}
    </section>
  );
}

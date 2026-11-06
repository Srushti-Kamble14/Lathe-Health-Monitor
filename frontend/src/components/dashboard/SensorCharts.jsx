import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import StateMessage from '../common/StateMessage.jsx';

const CHARTS = [
  {
    key: 'current',
    title: 'Current vs time',
    axis: 'Current',
    series: [
      ['current_l1', 'L1', '#228b82'],
      ['current_l2', 'L2', '#d39a3c'],
      ['current_l3', 'L3', '#5578a8'],
    ],
  },
  {
    key: 'voltage',
    title: 'Voltage vs time',
    axis: 'Voltage',
    series: [
      ['voltage_l1', 'L1', '#228b82'],
      ['voltage_l2', 'L2', '#d39a3c'],
      ['voltage_l3', 'L3', '#5578a8'],
    ],
  },
  {
    key: 'vibration',
    title: 'Vibration vs time',
    axis: 'Vibration',
    series: [
      ['vibration_x', 'X', '#228b82'],
      ['vibration_y', 'Y', '#d39a3c'],
      ['vibration_z', 'Z', '#5578a8'],
    ],
  },
  {
    key: 'temperature',
    title: 'Temperature vs time',
    axis: 'Temperature',
    series: [
      ['tool_temperature', 'Tool', '#c56b4f'],
      ['ambient_temperature', 'Ambient', '#5578a8'],
    ],
  },
];

function formatTick(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function formatTooltip(value) {
  return Number(value).toLocaleString('en-GB', { maximumFractionDigits: 3 });
}

function SensorChart({ chart, readings, loading }) {
  return (
    <article className="chart-card">
      <div className="section-heading section-heading--compact">
        <div>
          <p className="eyebrow">Sensor trend</p>
          <h3>{chart.title}</h3>
        </div>
        <span className="chart-card__axis">{chart.axis}</span>
      </div>
      {loading ? (
        <StateMessage>Loading session readings…</StateMessage>
      ) : !readings.length ? (
        <StateMessage>No sensor readings available for this session.</StateMessage>
      ) : (
        <div className="chart-container" role="img" aria-label={`${chart.title} chart. Time axis is shown in UTC.`}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={readings} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
              <CartesianGrid stroke="#e9eeec" vertical={false} />
              <XAxis
                dataKey="timestamp"
                tickFormatter={formatTick}
                minTickGap={36}
                tick={{ fill: '#78847f', fontSize: 11 }}
                axisLine={{ stroke: '#dce4e0' }}
                tickLine={false}
                label={{ value: 'Time (UTC)', position: 'insideBottom', offset: -2, fill: '#78847f', fontSize: 10 }}
              />
              <YAxis
                width={64}
                tickFormatter={formatTooltip}
                tick={{ fill: '#78847f', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                label={{ value: chart.axis, angle: -90, position: 'insideLeft', fill: '#78847f', fontSize: 10 }}
              />
              <Tooltip
                labelFormatter={(value) => `UTC ${new Date(value).toISOString()}`}
                formatter={(value, name) => [formatTooltip(value), name]}
                contentStyle={{
                  border: '1px solid #dfe7e3',
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Legend verticalAlign="bottom" height={28} iconType="circle" />
              {chart.series.map(([field, label, color]) => (
                <Line
                  key={field}
                  type="monotone"
                  dataKey={field}
                  name={label}
                  stroke={color}
                  strokeWidth={1.8}
                  dot={false}
                  activeDot={{ r: 3 }}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </article>
  );
}

export default function SensorCharts({ readings, loading, error, session }) {
  const sampleCount = readings.length;
  return (
    <section className="dashboard-section" aria-labelledby="trends-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Historical measurements</p>
          <h2 id="trends-title">Sensor trends</h2>
        </div>
        <p className="section-note">
          {loading
            ? 'Loading selected session…'
            : error
              ? 'Readings unavailable'
              : session
                ? `Showing ${sampleCount} latest readings (maximum 500) · UTC`
                : 'Select a session to view readings'}
        </p>
      </div>
      {error && <StateMessage variant="error" role="alert">{error}</StateMessage>}
      <div className="chart-grid">
        {CHARTS.map((chart) => (
          <SensorChart
            key={chart.key}
            chart={chart}
            readings={readings}
            loading={loading}
          />
        ))}
      </div>
    </section>
  );
}

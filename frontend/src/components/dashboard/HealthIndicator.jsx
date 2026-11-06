const STATUS_LABELS = {
  checking: 'Checking',
  connected: 'Connected',
  ready: 'Ready',
  unavailable: 'Unavailable',
};

export default function HealthIndicator({ label, status }) {
  return (
    <span className={`health-indicator health-indicator--${status}`} role="status">
      <span className="health-indicator__dot" aria-hidden="true" />
      <span>{label}: {STATUS_LABELS[status] || STATUS_LABELS.unavailable}</span>
    </span>
  );
}

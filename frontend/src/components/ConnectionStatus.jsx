export default function ConnectionStatus({ status, message }) {
  const isConnected = status === 'connected';

  return (
    <div
      className={`connection-status connection-status--${status}`}
      role="status"
      aria-live="polite"
    >
      <span className="connection-status__indicator" aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

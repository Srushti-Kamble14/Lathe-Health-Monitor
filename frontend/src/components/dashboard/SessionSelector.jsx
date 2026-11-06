function formatSessionDate(value) {
  if (!value) return 'Time unavailable';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Time unavailable';
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

export default function SessionSelector({ sessions, selectedSessionId, onChange, loading }) {
  return (
    <label className="session-select">
      <span>Monitoring session</span>
      <select
        value={selectedSessionId}
        onChange={(event) => onChange(event.target.value)}
        disabled={loading || !sessions.length}
      >
        {!sessions.length && <option value="">No sessions available</option>}
        {sessions.map((session) => (
          <option key={session.id} value={session.id}>
            Session {session.session_number} · {formatSessionDate(session.start_time)}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function StateMessage({ children, variant = 'empty', role }) {
  return (
    <p className={`state-message state-message--${variant}`} role={role}>
      {children}
    </p>
  );
}

import { useEffect, useState } from 'react';
import ConnectionStatus from '../components/ConnectionStatus.jsx';
import { getHealth } from '../services/api.js';

export default function LandingPage() {
  const [connection, setConnection] = useState({
    status: 'checking',
    message: 'Checking backend connection…',
  });

  useEffect(() => {
    let active = true;

    getHealth()
      .then((health) => {
        if (active && health.success && health.status === 'ok') {
          setConnection({ status: 'connected', message: 'Backend connected' });
        } else if (active) {
          setConnection({ status: 'disconnected', message: 'Backend unavailable' });
        }
      })
      .catch(() => {
        if (active) {
          setConnection({ status: 'disconnected', message: 'Backend unavailable' });
        }
      });

    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="landing">
      <section className="landing__content" aria-labelledby="project-title">
        <p className="landing__eyebrow">Industrial machine monitoring</p>
        <h1 id="project-title">
          AI-Based IoT Lathe Machine Health Monitoring and Predictive Maintenance
          System
        </h1>
        <p className="landing__description">
          A foundation for connecting machine data, backend services, and future
          predictive maintenance capabilities.
        </p>
        <ConnectionStatus status={connection.status} message={connection.message} />
        <p className="landing__note">
          Monitoring interface foundation · Machine readings are not available
          in this setup phase.
        </p>
      </section>
      <div className="landing__accent" aria-hidden="true" />
    </main>
  );
}

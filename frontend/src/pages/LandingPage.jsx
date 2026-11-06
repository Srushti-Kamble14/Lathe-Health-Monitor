import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
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
          Monitor backend-provided sensor measurements and exploratory anomaly
          results for the connected lathe machine.
        </p>
        <ConnectionStatus status={connection.status} message={connection.message} />
        <p className="landing__note">
          Explore the live monitoring dashboard using data returned by the backend.
        </p>
        <Link className="landing__dashboard-link" to="/dashboard">
          Open monitoring dashboard <span aria-hidden="true">→</span>
        </Link>
      </section>
      <div className="landing__accent" aria-hidden="true" />
    </main>
  );
}

const app = require('./app');
const { getEnvironment } = require('./config/environment');
const { pool, verifyDatabaseConnection } = require('./config/database');

const { port, nodeEnv } = getEnvironment();
let server;
let shuttingDown = false;

async function startServer() {
  try {
    await verifyDatabaseConnection();
  } catch (_error) {
    console.error(
      'Backend startup failed: PostgreSQL connection verification failed. Check DATABASE_URL and Neon availability.',
    );
    if (pool) {
      await pool.end();
    }
    process.exitCode = 1;
    return;
  }

  server = app.listen(port, () => {
    console.log(`Backend listening on port ${port} (${nodeEnv}).`);
  });

  server.on('error', (error) => {
    console.error(`Backend server error: ${error.message}`);
    process.exitCode = 1;
    void shutdown();
  });
}

async function shutdown() {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;

  if (server) {
    await new Promise((resolve) => server.close(resolve));
  }

  if (pool) {
    await pool.end();
  }
}

process.on('SIGINT', () => {
  void shutdown().then(() => {
    process.exit(0);
  });
});

process.on('SIGTERM', () => {
  void shutdown().then(() => {
    process.exit(0);
  });
});

void startServer();

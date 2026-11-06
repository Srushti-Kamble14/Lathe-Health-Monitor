const { Pool } = require('pg');
const { getEnvironment } = require('./environment');

const { databaseUrl } = getEnvironment();
const pool = databaseUrl
  ? new Pool({
      connectionString: databaseUrl,
      ssl: { rejectUnauthorized: true },
      connectionTimeoutMillis: 5000,
      application_name: 'lathe-health-monitor-backend',
    })
  : null;

if (pool) {
  pool.on('error', (error) => {
    console.error('Unexpected PostgreSQL pool error.');
    if (process.env.NODE_ENV === 'development') {
      console.error(`PostgreSQL error code: ${error.code || 'unknown'}`);
    }
  });
}

async function queryDatabase(query, parameters = []) {
  if (!pool) {
    throw new Error('DATABASE_URL is not configured.');
  }

  return pool.query(query, parameters);
}

async function verifyDatabaseConnection() {
  await queryDatabase('SELECT 1');
}

module.exports = { pool, queryDatabase, verifyDatabaseConnection };

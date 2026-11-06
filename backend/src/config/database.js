const { Pool } = require('pg');
const { getEnvironment } = require('./environment');

const { databaseUrl } = getEnvironment();
const pool = databaseUrl
  ? new Pool({
      connectionString: databaseUrl,
      ssl: { rejectUnauthorized: true },
      connectionTimeoutMillis: 5000,
    })
  : null;

if (pool) {
  pool.on('error', () => {
    console.error('Unexpected PostgreSQL pool error.');
  });
}

async function queryDatabase(query) {
  if (!pool) {
    throw new Error('DATABASE_URL is not configured.');
  }

  return pool.query(query);
}

async function verifyDatabaseConnection() {
  await queryDatabase('SELECT 1');
}

module.exports = { pool, queryDatabase, verifyDatabaseConnection };

const fs = require('node:fs/promises');
const path = require('node:path');
const { pool } = require('../config/database');

const MIGRATIONS_DIRECTORY = path.join(__dirname, 'migrations');
const LOCK_NAMESPACE = 1828353093;
const LOCK_ID = 1;

async function runMigrations() {
  if (!pool) {
    throw new Error('DATABASE_URL is not configured.');
  }

  const client = await pool.connect();
  let locked = false;
  try {
    await client.query('SELECT pg_advisory_lock($1, $2)', [LOCK_NAMESPACE, LOCK_ID]);
    locked = true;
    await client.query(`
      CREATE TABLE IF NOT EXISTS schema_migrations (
        migration_name TEXT PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      )
    `);

    const files = (await fs.readdir(MIGRATIONS_DIRECTORY))
      .filter((name) => /^\d{3}_[a-z0-9_]+\.sql$/.test(name))
      .sort();
    const result = await client.query('SELECT migration_name FROM schema_migrations');
    const applied = new Set(result.rows.map((row) => row.migration_name));
    let appliedCount = 0;

    for (const file of files) {
      if (applied.has(file)) {
        console.log(`Skipping applied migration: ${file}`);
        continue;
      }

      const sql = await fs.readFile(path.join(MIGRATIONS_DIRECTORY, file), 'utf8');
      try {
        await client.query('BEGIN');
        await client.query(sql);
        await client.query(
          'INSERT INTO schema_migrations (migration_name) VALUES ($1)',
          [file],
        );
        await client.query('COMMIT');
      } catch (error) {
        await client.query('ROLLBACK');
        console.error(`Migration failed: ${file} (code ${error.code || 'unknown'}).`);
        throw new Error(`Migration failed: ${file}`);
      }

      appliedCount += 1;
      console.log(`Applied migration: ${file}`);
    }

    console.log(`Migration run complete. Newly applied: ${appliedCount}.`);
  } finally {
    if (locked) {
      await client.query('SELECT pg_advisory_unlock($1, $2)', [
        LOCK_NAMESPACE,
        LOCK_ID,
      ]);
    }
    client.release();
    await pool.end();
  }
}

runMigrations().catch((error) => {
  if (error.message === 'DATABASE_URL is not configured.') {
    console.error(error.message);
  } else if (!error.message.startsWith('Migration failed:')) {
    console.error(`Migration runner failed (code ${error.code || 'unknown'}).`);
  }
  process.exitCode = 1;
});

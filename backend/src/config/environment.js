const path = require('node:path');
const dotenv = require('dotenv');

dotenv.config({ path: path.resolve(__dirname, '../../.env') });

function getEnvironment() {
  const port = Number.parseInt(process.env.PORT || '3000', 10);
  const frontendOrigins = (process.env.FRONTEND_URL || 'http://localhost:5173')
    .split(',')
    .map((origin) => origin.trim())
    .filter(Boolean);
  const mlServiceTimeoutMs = Number.parseInt(
    process.env.ML_SERVICE_TIMEOUT_MS || '5000',
    10,
  );

  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('PORT must be a valid TCP port between 1 and 65535.');
  }
  if (!Number.isInteger(mlServiceTimeoutMs) || mlServiceTimeoutMs < 1) {
    throw new Error('ML_SERVICE_TIMEOUT_MS must be a positive integer.');
  }

  return {
    port,
    nodeEnv: process.env.NODE_ENV || 'development',
    databaseUrl: process.env.DATABASE_URL,
    frontendOrigins,
    mlServiceUrl: process.env.ML_SERVICE_URL,
    mlServiceTimeoutMs,
  };
}

module.exports = { getEnvironment };

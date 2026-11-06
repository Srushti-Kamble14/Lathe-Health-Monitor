const { queryDatabase } = require('../config/database');

const APPLICATION_NAME =
  'AI-Based IoT Lathe Machine Health Monitoring and Predictive Maintenance System';

function getServerHealth() {
  return {
    success: true,
    application: APPLICATION_NAME,
    status: 'ok',
    timestamp: new Date().toISOString(),
  };
}

async function getDatabaseHealth() {
  await queryDatabase('SELECT 1');

  return {
    success: true,
    status: 'ok',
    timestamp: new Date().toISOString(),
  };
}

module.exports = { getServerHealth, getDatabaseHealth };

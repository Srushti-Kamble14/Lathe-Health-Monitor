const healthService = require('../services/healthService');

function getServerHealth(_request, response) {
  response.status(200).json(healthService.getServerHealth());
}

async function getDatabaseHealth(_request, response) {
  try {
    const health = await healthService.getDatabaseHealth();
    response.status(200).json(health);
  } catch (_error) {
    response.status(503).json({
      success: false,
      status: 'unavailable',
      error: {
        code: 'DATABASE_UNAVAILABLE',
        message: 'The database health check could not be completed.',
      },
      timestamp: new Date().toISOString(),
    });
  }
}

module.exports = { getServerHealth, getDatabaseHealth };

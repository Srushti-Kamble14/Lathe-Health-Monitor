const readingService = require('../services/readingService');

async function listReadings(request, response) {
  const result = await readingService.listReadings(request.query);
  response.status(200).json({
    success: true,
    data: result.data,
    pagination: result.pagination,
  });
}

async function getLatestReading(request, response) {
  const reading = await readingService.getLatestReading(request.query);
  response.status(200).json({ success: true, data: reading });
}

module.exports = { listReadings, getLatestReading };

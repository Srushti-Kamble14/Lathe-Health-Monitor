const anomalyService = require('../services/anomalyService').createAnomalyService();
const asyncHandler = require('../utils/asyncHandler');

function createAnomalyController(service = anomalyService) {
  return {
    list: asyncHandler(async (request, response) => {
      const result = await service.listAnomalies(request.query);
      response.status(200).json({
        success: true,
        data: result.data,
        pagination: result.pagination,
      });
    }),
    latest: asyncHandler(async (request, response) => {
      const result = await service.getLatestAnomaly(request.query.machineId);
      response.status(200).json({ success: true, data: result });
    }),
    score: asyncHandler(async (request, response) => {
      const result = await service.scoreAndPersist(request.body);
      response.status(200).json({ success: true, data: result });
    }),
  };
}

module.exports = createAnomalyController;

const anomalyService = require('../services/anomalyService').createAnomalyService();
const asyncHandler = require('../utils/asyncHandler');

function createAnomalyController(service = anomalyService) {
  return {
    score: asyncHandler(async (request, response) => {
      const result = await service.scoreAndPersist(request.body);
      response.status(200).json({ success: true, data: result });
    }),
  };
}

module.exports = createAnomalyController;

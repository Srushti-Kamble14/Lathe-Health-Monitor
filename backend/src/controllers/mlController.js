const { createMlServiceClient } = require('../services/mlService');
const asyncHandler = require('../utils/asyncHandler');

function createMlController(mlClient = createMlServiceClient()) {
  return {
    readiness: asyncHandler(async (_request, response) => {
      const data = await mlClient.checkReadiness();
      response.status(200).json({ success: true, data });
    }),
  };
}

module.exports = createMlController;

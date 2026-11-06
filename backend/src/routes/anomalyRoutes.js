const express = require('express');
const createAnomalyController = require('../controllers/anomalyController');

function createAnomalyRoutes(service) {
  const router = express.Router();
  const controller = createAnomalyController(service);
  router.post('/score', controller.score);
  return router;
}

module.exports = createAnomalyRoutes;

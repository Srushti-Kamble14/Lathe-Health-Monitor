const express = require('express');
const createMlController = require('../controllers/mlController');

function createMlRoutes(mlClient) {
  const router = express.Router();
  const controller = createMlController(mlClient);
  router.get('/ready', controller.readiness);
  return router;
}

module.exports = createMlRoutes;

const express = require('express');
const machineController = require('../controllers/machineController');
const asyncHandler = require('../utils/asyncHandler');
const HttpError = require('../utils/httpError');

const router = express.Router();
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

router.get('/', asyncHandler(machineController.listMachines));
router.get(
  '/:id',
  (request, _response, next) => {
    if (!uuidPattern.test(request.params.id)) {
      return next(new HttpError(400, 'INVALID_ID', 'Machine id must be a valid UUID.'));
    }
    return next();
  },
  asyncHandler(machineController.getMachine),
);

module.exports = router;

const express = require('express');
const sessionController = require('../controllers/sessionController');
const asyncHandler = require('../utils/asyncHandler');

const router = express.Router();

router.get('/', asyncHandler(sessionController.listSessions));

module.exports = router;

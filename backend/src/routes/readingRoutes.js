const express = require('express');
const readingController = require('../controllers/readingController');
const asyncHandler = require('../utils/asyncHandler');

const router = express.Router();

router.get('/latest', asyncHandler(readingController.getLatestReading));
router.get('/', asyncHandler(readingController.listReadings));

module.exports = router;

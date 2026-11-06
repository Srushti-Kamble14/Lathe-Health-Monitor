const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const { getEnvironment } = require('./config/environment');
const healthRoutes = require('./routes/healthRoutes');
const machineRoutes = require('./routes/machineRoutes');
const readingRoutes = require('./routes/readingRoutes');
const sessionRoutes = require('./routes/sessionRoutes');
const createAnomalyRoutes = require('./routes/anomalyRoutes');
const notFound = require('./middleware/notFound');
const errorHandler = require('./middleware/errorHandler');

const { frontendOrigins } = getEnvironment();

function createApp(options = {}) {
  const app = express();

  app.use(helmet());
  app.use(
    cors({
      origin(origin, callback) {
        if (!origin || frontendOrigins.includes(origin)) {
          return callback(null, true);
        }

        return callback(new Error('Origin is not allowed by CORS.'));
      },
    }),
  );
  app.use(express.json({ limit: '16kb' }));
  app.use('/api/v1/health', healthRoutes);
  app.use('/api/v1/machines', machineRoutes);
  app.use('/api/v1/readings', readingRoutes);
  app.use('/api/v1/sessions', sessionRoutes);
  app.use('/api/v1/anomalies', createAnomalyRoutes(options.anomalyService));
  app.use(notFound);
  app.use(errorHandler);
  return app;
}

const app = createApp();
app.createApp = createApp;

module.exports = app;

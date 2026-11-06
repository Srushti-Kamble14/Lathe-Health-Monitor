const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const { getEnvironment } = require('./config/environment');
const healthRoutes = require('./routes/healthRoutes');
const machineRoutes = require('./routes/machineRoutes');
const readingRoutes = require('./routes/readingRoutes');
const sessionRoutes = require('./routes/sessionRoutes');
const notFound = require('./middleware/notFound');
const errorHandler = require('./middleware/errorHandler');

const app = express();
const { frontendOrigins } = getEnvironment();

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
app.use(express.json());
app.use('/api/v1/health', healthRoutes);
app.use('/api/v1/machines', machineRoutes);
app.use('/api/v1/readings', readingRoutes);
app.use('/api/v1/sessions', sessionRoutes);
app.use(notFound);
app.use(errorHandler);

module.exports = app;

const { queryDatabase } = require('../config/database');
const { createMlServiceClient } = require('./mlService');
const HttpError = require('../utils/httpError');

const FEATURE_NAMES = [
  'current_mean',
  'current_std',
  'current_imbalance',
  'voltage_mean',
  'voltage_imbalance',
  'vibration_rms',
  'vibration_magnitude_std',
  'temperature_delta',
  'temperature_rate',
];
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const REQUEST_KEYS = ['machine_id', 'session_id', 'timestamp', 'features'];

function invalidRequest(message = 'The anomaly scoring request is invalid.') {
  return new HttpError(400, 'INVALID_ANOMALY_REQUEST', message);
}

function validateRequest(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    throw invalidRequest();
  }
  const keys = Object.keys(body).sort();
  if (keys.length !== REQUEST_KEYS.length || REQUEST_KEYS.some((key) => !keys.includes(key))) {
    throw invalidRequest('Request must contain machine_id, session_id, timestamp, and features only.');
  }
  if (typeof body.machine_id !== 'string' || !UUID_PATTERN.test(body.machine_id)) {
    throw invalidRequest('machine_id must be a valid UUID.');
  }
  if (typeof body.session_id !== 'string' || !UUID_PATTERN.test(body.session_id)) {
    throw invalidRequest('session_id must be a valid UUID.');
  }
  if (
    typeof body.timestamp !== 'string'
    || body.timestamp.length > 64
    || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(body.timestamp)
    || Number.isNaN(Date.parse(body.timestamp))
    || Number.isNaN(Date.parse(`${body.timestamp.slice(0, 10)}T00:00:00Z`))
    || new Date(`${body.timestamp.slice(0, 10)}T00:00:00Z`).toISOString().slice(0, 10)
      !== body.timestamp.slice(0, 10)
  ) {
    throw invalidRequest('timestamp must be an ISO timestamp with a timezone.');
  }
  if (!body.features || typeof body.features !== 'object' || Array.isArray(body.features)) {
    throw invalidRequest('features must contain exactly the approved numeric feature fields.');
  }

  const featureKeys = Object.keys(body.features).sort();
  if (
    featureKeys.length !== FEATURE_NAMES.length
    || FEATURE_NAMES.some((name) => !featureKeys.includes(name))
  ) {
    throw invalidRequest('features must contain exactly the approved numeric feature fields.');
  }
  for (const name of FEATURE_NAMES) {
    const value = body.features[name];
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      throw invalidRequest('All feature values must be finite numbers.');
    }
  }

  return {
    machineId: body.machine_id,
    sessionId: body.session_id,
    timestamp: new Date(body.timestamp).toISOString(),
    features: Object.fromEntries(FEATURE_NAMES.map((name) => [name, body.features[name]])),
  };
}

function createAnomalyService({
  query = queryDatabase,
  mlClient = createMlServiceClient(),
} = {}) {
  async function scoreAndPersist(body) {
    const request = validateRequest(body);

    const machine = await query(
      'SELECT id FROM machines WHERE id = $1',
      [request.machineId],
    );
    if (machine.rowCount === 0) {
      throw new HttpError(404, 'MACHINE_NOT_FOUND', 'Machine was not found.');
    }

    const session = await query(
      `SELECT id
       FROM machine_sessions
       WHERE id = $1
         AND machine_id = $2
         AND start_time <= $3::timestamptz
         AND end_time >= $3::timestamptz`,
      [request.sessionId, request.machineId, request.timestamp],
    );
    if (session.rowCount === 0) {
      throw new HttpError(
        404,
        'SESSION_NOT_FOUND',
        'Session was not found for this machine and timestamp.',
      );
    }

    const reading = await query(
      `SELECT id
       FROM sensor_readings
       WHERE machine_id = $1 AND timestamp = $2::timestamptz`,
      [request.machineId, request.timestamp],
    );
    const readingId = reading.rows[0] ? reading.rows[0].id : null;

    const prediction = await mlClient.scoreFeatures(request.features);
    const stored = await query(
      `INSERT INTO anomaly_results (
         machine_id, reading_id, timestamp, anomaly_score, anomaly_status,
         model_name, model_version
       )
       VALUES ($1, $2, $3::timestamptz, $4, $5, $6, $7)
       ON CONFLICT (machine_id, timestamp) DO UPDATE SET
         reading_id = EXCLUDED.reading_id,
         anomaly_score = EXCLUDED.anomaly_score,
         anomaly_status = EXCLUDED.anomaly_status,
         model_name = EXCLUDED.model_name,
         model_version = EXCLUDED.model_version
       RETURNING id, machine_id, reading_id, timestamp, anomaly_score,
                 anomaly_status, model_name, model_version, created_at`,
      [
        request.machineId,
        readingId,
        request.timestamp,
        prediction.anomaly_score,
        prediction.anomaly_status,
        prediction.model_name,
        prediction.model_version,
      ],
    );

    return {
      ...stored.rows[0],
      session_id: request.sessionId,
      features_used: prediction.features_used,
    };
  }

  return { scoreAndPersist };
}

module.exports = { createAnomalyService, validateRequest };

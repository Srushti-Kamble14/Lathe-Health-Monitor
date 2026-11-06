const { queryDatabase } = require('../config/database');
const HttpError = require('../utils/httpError');

const READING_COLUMNS = `
  id, machine_id, timestamp,
  current_l1, current_l2, current_l3,
  voltage_l1, voltage_l2, voltage_l3,
  vibration_x, vibration_y, vibration_z,
  ambient_temperature, tool_temperature,
  created_at
`;

function validateUuid(value, fieldName) {
  if (
    typeof value !== 'string'
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
  ) {
    throw new HttpError(400, 'INVALID_QUERY_PARAMETER', `${fieldName} must be a valid UUID.`);
  }
}

function validateTimestamp(value, fieldName) {
  if (typeof value !== 'string' || value.length > 64 || Number.isNaN(Date.parse(value))) {
    throw new HttpError(400, 'INVALID_QUERY_PARAMETER', `${fieldName} must be a valid timestamp.`);
  }
  return new Date(value).toISOString();
}

function parsePagination(query) {
  const limit = query.limit === undefined ? 100 : Number(query.limit);
  const offset = query.offset === undefined ? 0 : Number(query.offset);
  if (!Number.isInteger(limit) || limit < 1 || limit > 500) {
    throw new HttpError(400, 'INVALID_QUERY_PARAMETER', 'limit must be an integer from 1 to 500.');
  }
  if (!Number.isInteger(offset) || offset < 0 || offset > 10000000) {
    throw new HttpError(400, 'INVALID_QUERY_PARAMETER', 'offset must be a non-negative integer no greater than 10000000.');
  }
  return { limit, offset };
}

function buildFilters(query) {
  const clauses = [];
  const parameters = [];
  if (query.machineId !== undefined) {
    validateUuid(query.machineId, 'machineId');
    parameters.push(query.machineId);
    clauses.push(`machine_id = $${parameters.length}`);
  }
  if (query.start !== undefined) {
    parameters.push(validateTimestamp(query.start, 'start'));
    clauses.push(`timestamp >= $${parameters.length}::timestamptz`);
  }
  if (query.end !== undefined) {
    parameters.push(validateTimestamp(query.end, 'end'));
    clauses.push(`timestamp <= $${parameters.length}::timestamptz`);
  }
  if (
    query.start !== undefined
    && query.end !== undefined
    && Date.parse(query.start) > Date.parse(query.end)
  ) {
    throw new HttpError(400, 'INVALID_QUERY_PARAMETER', 'start must not be later than end.');
  }
  return { where: clauses.length ? `WHERE ${clauses.join(' AND ')}` : '', parameters };
}

async function listReadings(query) {
  const { limit, offset } = parsePagination(query);
  const { where, parameters } = buildFilters(query);
  const countResult = await queryDatabase(
    `SELECT COUNT(*)::bigint AS total FROM sensor_readings ${where}`,
    parameters,
  );
  const result = await queryDatabase(
    `SELECT ${READING_COLUMNS}
     FROM sensor_readings
     ${where}
     ORDER BY timestamp DESC, id DESC
     LIMIT $${parameters.length + 1} OFFSET $${parameters.length + 2}`,
    [...parameters, limit, offset],
  );
  return {
    data: result.rows,
    pagination: { limit, offset, total: Number(countResult.rows[0].total) },
  };
}

async function getLatestReading(query) {
  if (query.machineId !== undefined) {
    validateUuid(query.machineId, 'machineId');
  }
  const parameters = query.machineId === undefined ? [] : [query.machineId];
  const where = parameters.length ? 'WHERE machine_id = $1' : '';
  const result = await queryDatabase(
    `SELECT ${READING_COLUMNS}
     FROM sensor_readings
     ${where}
     ORDER BY timestamp DESC, id DESC
     LIMIT 1`,
    parameters,
  );
  return result.rows[0] || null;
}

module.exports = { listReadings, getLatestReading };

const { queryDatabase } = require('../config/database');
const HttpError = require('../utils/httpError');

async function listSessions(query) {
  const parameters = [];
  let where = '';
  if (query.machineId !== undefined) {
    if (
      typeof query.machineId !== 'string'
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(query.machineId)
    ) {
      throw new HttpError(400, 'INVALID_QUERY_PARAMETER', 'machineId must be a valid UUID.');
    }
    parameters.push(query.machineId);
    where = 'WHERE machine_id = $1';
  }
  const result = await queryDatabase(
    `SELECT id, machine_id, session_number, start_time, end_time, sample_count, created_at
     FROM machine_sessions
     ${where}
     ORDER BY start_time DESC`,
    parameters,
  );
  return result.rows;
}

module.exports = { listSessions };

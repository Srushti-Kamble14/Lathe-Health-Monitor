const { queryDatabase } = require('../config/database');
const HttpError = require('../utils/httpError');

async function listMachines() {
  const result = await queryDatabase(
    `SELECT id, name, machine_code, description, location, status, created_at, updated_at
     FROM machines
     ORDER BY machine_code`,
  );
  return result.rows;
}

async function getMachineById(id) {
  const result = await queryDatabase(
    `SELECT id, name, machine_code, description, location, status, created_at, updated_at
     FROM machines
     WHERE id = $1`,
    [id],
  );
  if (result.rowCount === 0) {
    throw new HttpError(404, 'MACHINE_NOT_FOUND', 'Machine was not found.');
  }
  return result.rows[0];
}

module.exports = { listMachines, getMachineById };

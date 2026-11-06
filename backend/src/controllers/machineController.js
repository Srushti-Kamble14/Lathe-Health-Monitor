const machineService = require('../services/machineService');

async function listMachines(_request, response) {
  const machines = await machineService.listMachines();
  response.status(200).json({ success: true, data: machines });
}

async function getMachine(request, response) {
  const machine = await machineService.getMachineById(request.params.id);
  response.status(200).json({ success: true, data: machine });
}

module.exports = { listMachines, getMachine };

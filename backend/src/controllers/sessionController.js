const sessionService = require('../services/sessionService');

async function listSessions(request, response) {
  const sessions = await sessionService.listSessions(request.query);
  response.status(200).json({ success: true, data: sessions });
}

module.exports = { listSessions };

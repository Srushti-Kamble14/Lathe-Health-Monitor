const assert = require('node:assert/strict');
const { once } = require('node:events');
const test = require('node:test');

const app = require('../src/app');
const { createAnomalyService } = require('../src/services/anomalyService');
const { createMlServiceClient } = require('../src/services/mlService');
const HttpError = require('../src/utils/httpError');

const machineId = '00000000-0000-4000-8000-000000000001';
const anomaly = {
  id: '22222222-2222-4222-8222-222222222222',
  machine_id: machineId,
  reading_id: '11111111-1111-4111-8111-111111111111',
  timestamp: '2026-11-01T09:03:01.000Z',
  anomaly_score: 0.42,
  anomaly_status: 'WARNING',
  model_name: 'IsolationForest',
  model_version: 'isolation-forest-v1',
  created_at: '2026-11-01T09:03:02.000Z',
};

function createMockQuery({ rows = [anomaly], total = 1 } = {}) {
  const calls = [];
  const query = async (sql, params) => {
    calls.push({ sql, params });
    if (sql.includes('COUNT(*)')) {
      return { rows: [{ total: String(total) }], rowCount: 1 };
    }
    return { rows, rowCount: rows.length };
  };
  query.calls = calls;
  return query;
}

async function request(path, { anomalyService, mlClient } = {}) {
  const server = app.createApp({ anomalyService, mlClient }).listen(0);
  await once(server, 'listening');
  try {
    return await fetch(`http://127.0.0.1:${server.address().port}${path}`);
  } finally {
    await new Promise((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
  }
}

test('anomaly list defaults to bounded pagination and returns database rows', async () => {
  const query = createMockQuery({ total: 17 });
  const service = createAnomalyService({ query, mlClient: {} });

  const result = await service.listAnomalies({});

  assert.deepEqual(result, {
    data: [anomaly],
    pagination: { limit: 50, offset: 0, total: 17 },
  });
  assert.equal(query.calls.length, 2);
  assert.deepEqual(query.calls[0].params, [null, null, null, null]);
  assert.deepEqual(query.calls[1].params, [null, null, null, null, 50, 0]);
  assert.match(query.calls[1].sql, /ORDER BY timestamp DESC, id DESC/);
});

test('anomaly list applies machine, date, status, and pagination filters with parameters', async () => {
  const query = createMockQuery({ total: 22 });
  const service = createAnomalyService({ query, mlClient: {} });

  const result = await service.listAnomalies({
    machineId,
    start: '2026-11-01T00:00:00Z',
    end: '2026-11-02T00:00:00Z',
    status: 'WARNING',
    limit: '10',
    offset: '5',
  });

  assert.deepEqual(result.pagination, { limit: 10, offset: 5, total: 22 });
  assert.deepEqual(query.calls[1].params, [
    machineId,
    '2026-11-01T00:00:00.000Z',
    '2026-11-02T00:00:00.000Z',
    'WARNING',
    10,
    5,
  ]);
  assert.match(query.calls[0].sql, /\$1::uuid/);
  assert.match(query.calls[0].sql, /\$2::timestamptz/);
  assert.match(query.calls[0].sql, /\$4::varchar/);
});

test('anomaly list rejects invalid filters and pagination before querying', async () => {
  const invalidCases = [
    [{ machineId: 'not-a-uuid' }, 'machineId'],
    [{ status: 'OFFLINE' }, 'status'],
    [{ limit: '0' }, 'limit'],
    [{ limit: '501' }, 'limit'],
    [{ offset: '-1' }, 'offset'],
    [{ offset: '10000001' }, 'offset'],
    [{ start: '2026-11-03T00:00:00Z', end: '2026-11-02T00:00:00Z' }, 'start'],
  ];

  for (const [filters, messagePart] of invalidCases) {
    const query = createMockQuery();
    const service = createAnomalyService({ query, mlClient: {} });
    await assert.rejects(
      service.listAnomalies(filters),
      (error) => error.statusCode === 400 && error.message.includes(messagePart),
    );
    assert.equal(query.calls.length, 0);
  }
});

test('latest anomaly returns the latest persisted row or null', async () => {
  const query = createMockQuery();
  const service = createAnomalyService({ query, mlClient: {} });
  assert.deepEqual(await service.getLatestAnomaly(machineId), anomaly);
  assert.deepEqual(query.calls[0].params, [machineId]);
  assert.match(query.calls[0].sql, /ORDER BY timestamp DESC, id DESC\s+LIMIT 1/);

  const emptyQuery = createMockQuery({ rows: [] });
  const emptyService = createAnomalyService({ query: emptyQuery, mlClient: {} });
  assert.equal(await emptyService.getLatestAnomaly(machineId), null);
});

test('latest anomaly rejects an invalid or missing machine id', async () => {
  const query = createMockQuery();
  const service = createAnomalyService({ query, mlClient: {} });
  await assert.rejects(service.getLatestAnomaly('bad-id'), { statusCode: 400 });
  await assert.rejects(service.getLatestAnomaly(undefined), { statusCode: 400 });
  assert.equal(query.calls.length, 0);
});

test('anomaly read routes return the documented response shapes', async () => {
  const query = createMockQuery();
  const anomalyService = createAnomalyService({ query, mlClient: {} });
  const list = await request('/api/v1/anomalies?machineId=' + machineId, {
    anomalyService,
    mlClient: { checkReadiness: async () => ({ status: 'ready' }) },
  });
  assert.equal(list.status, 200);
  assert.deepEqual(await list.json(), {
    success: true,
    data: [anomaly],
    pagination: { limit: 50, offset: 0, total: 1 },
  });

  const latest = await request(`/api/v1/anomalies/latest?machineId=${machineId}`, {
    anomalyService,
    mlClient: { checkReadiness: async () => ({ status: 'ready' }) },
  });
  assert.equal(latest.status, 200);
  assert.deepEqual(await latest.json(), { success: true, data: anomaly });
});

test('ML readiness route reports ready without exposing upstream details', async () => {
  const client = createMlServiceClient({
    baseUrl: 'http://ml.invalid',
    fetchImpl: async (url, options) => {
      assert.equal(String(url), 'http://ml.invalid/ready');
      assert.equal(options.method, undefined);
      return {
        ok: true,
        json: async () => ({ success: true, status: 'ready', model_loaded: true }),
      };
    },
  });
  const response = await request('/api/v1/ml/ready', {
    mlClient: client,
    anomalyService: {},
  });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { success: true, data: { status: 'ready' } });
});

test('ML readiness route returns sanitized unavailable errors', async () => {
  const unavailable = new HttpError(
    503,
    'ML_SERVICE_UNAVAILABLE',
    'The anomaly inference service is unavailable.',
  );
  const response = await request('/api/v1/ml/ready', {
    mlClient: { checkReadiness: async () => { throw unavailable; } },
    anomalyService: {},
  });
  assert.equal(response.status, 503);
  const body = await response.json();
  assert.equal(body.success, false);
  assert.equal(body.error.code, 'ML_SERVICE_UNAVAILABLE');
  assert.doesNotMatch(JSON.stringify(body), /ml\.invalid|stack|secret|filesystem/i);
});

test('ML readiness client treats connection errors and non-ready responses as unavailable', async () => {
  const disconnected = createMlServiceClient({
    baseUrl: 'http://ml.invalid',
    fetchImpl: async () => { throw new Error('private upstream detail'); },
  });
  await assert.rejects(disconnected.checkReadiness(), {
    statusCode: 503,
    code: 'ML_SERVICE_UNAVAILABLE',
  });

  const notReady = createMlServiceClient({
    baseUrl: 'http://ml.invalid',
    fetchImpl: async () => ({
      ok: false,
      json: async () => ({ detail: 'private upstream detail' }),
    }),
  });
  await assert.rejects(notReady.checkReadiness(), {
    statusCode: 503,
    code: 'ML_SERVICE_UNAVAILABLE',
  });
});

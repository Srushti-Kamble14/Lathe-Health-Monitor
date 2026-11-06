const assert = require('node:assert/strict');
const { once } = require('node:events');
const test = require('node:test');

const app = require('../src/app');
const { createAnomalyService } = require('../src/services/anomalyService');
const { createMlServiceClient } = require('../src/services/mlService');
const HttpError = require('../src/utils/httpError');

const machineId = '00000000-0000-4000-8000-000000000001';
const sessionId = '780fc743-2049-492f-a939-f1096faec6ac';
const readingId = '11111111-1111-4111-8111-111111111111';
const featureNames = [
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
const features = Object.fromEntries(featureNames.map((name) => [name, 1.25]));
const validRequest = {
  machine_id: machineId,
  session_id: sessionId,
  timestamp: '2026-11-01T09:03:01Z',
  features,
};
const mlResponse = {
  success: true,
  data: {
    anomaly_score: 0.42,
    anomaly_status: 'NORMAL',
    model_name: 'IsolationForest',
    model_version: 'isolation-forest-v1',
    features_used: featureNames,
  },
};

function createMockQuery({ failAt } = {}) {
  const calls = [];
  const query = async (sql, params) => {
    calls.push({ sql, params });
    if (failAt && sql.includes(failAt)) {
      throw new Error('simulated database failure with private details');
    }
    if (sql.includes('FROM machines')) {
      return { rowCount: 1, rows: [{ id: machineId }] };
    }
    if (sql.includes('FROM machine_sessions')) {
      return { rowCount: 1, rows: [{ id: sessionId }] };
    }
    if (sql.includes('FROM sensor_readings')) {
      return { rowCount: 1, rows: [{ id: readingId }] };
    }
    if (sql.includes('INSERT INTO anomaly_results')) {
      return {
        rowCount: 1,
        rows: [{
          id: '22222222-2222-4222-8222-222222222222',
          machine_id: machineId,
          reading_id: readingId,
          timestamp: validRequest.timestamp,
          anomaly_score: 0.42,
          anomaly_status: 'NORMAL',
          model_name: 'IsolationForest',
          model_version: 'isolation-forest-v1',
          created_at: validRequest.timestamp,
        }],
      };
    }
    throw new Error('Unexpected query in test.');
  };
  query.calls = calls;
  return query;
}

async function withServer(handler) {
  const server = app.createApp({ anomalyService: handler }).listen(0);
  await once(server, 'listening');
  try {
    const address = server.address();
    return await fetch(`http://127.0.0.1:${address.port}/api/v1/anomalies/score`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(validRequest),
    });
  } finally {
    await new Promise((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
  }
}

async function postToService(service, requestBody = validRequest) {
  const server = app.createApp({ anomalyService: service }).listen(0);
  await once(server, 'listening');
  try {
    return await fetch(
      `http://127.0.0.1:${server.address().port}/api/v1/anomalies/score`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(requestBody),
      },
    );
  } finally {
    await new Promise((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
  }
}

test('valid request calls ML, validates references, and persists idempotently', async () => {
  const query = createMockQuery();
  const mlClient = { scoreFeatures: async () => mlResponse.data };
  const service = createAnomalyService({ query, mlClient });
  const result = await service.scoreAndPersist(validRequest);

  assert.equal(result.anomaly_score, 0.42);
  assert.equal(result.session_id, sessionId);
  assert.deepEqual(result.features_used, featureNames);
  assert.equal(query.calls.length, 4);
  assert.match(query.calls[3].sql, /ON CONFLICT \(machine_id, timestamp\) DO UPDATE/);
});

test('request rejects missing, non-finite, or unapproved features before dependencies', async () => {
  const query = createMockQuery();
  const mlClient = { scoreFeatures: async () => mlResponse.data };
  const service = createAnomalyService({ query, mlClient });

  await assert.rejects(
    service.scoreAndPersist({ ...validRequest, features: { current_mean: 1 } }),
    { statusCode: 400, code: 'INVALID_ANOMALY_REQUEST' },
  );
  await assert.rejects(
    service.scoreAndPersist({
      ...validRequest,
      features: { ...features, current_mean: Number.POSITIVE_INFINITY },
    }),
    { statusCode: 400, code: 'INVALID_ANOMALY_REQUEST' },
  );
  await assert.rejects(
    service.scoreAndPersist({ ...validRequest, unapproved_feature: 1200 }),
    { statusCode: 400, code: 'INVALID_ANOMALY_REQUEST' },
  );
  await assert.rejects(
    service.scoreAndPersist({ ...validRequest, timestamp: '2026-02-30T09:03:01Z' }),
    { statusCode: 400, code: 'INVALID_ANOMALY_REQUEST' },
  );
  assert.equal(query.calls.length, 0);
});

test('ML transport failures, timeouts, and malformed responses are structured', async () => {
  const unavailable = createMlServiceClient({
    baseUrl: 'http://ml.invalid',
    fetchImpl: async () => {
      throw new Error('private network detail');
    },
  });
  await assert.rejects(unavailable.scoreFeatures(features), {
    statusCode: 503,
    code: 'ML_SERVICE_UNAVAILABLE',
  });

  const timeout = createMlServiceClient({
    baseUrl: 'http://ml.invalid',
    timeoutMs: 5,
    fetchImpl: (_url, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => {
        const error = new Error('aborted');
        error.name = 'AbortError';
        reject(error);
      });
    }),
  });
  await assert.rejects(timeout.scoreFeatures(features), {
    statusCode: 504,
    code: 'ML_SERVICE_TIMEOUT',
  });

  const malformed = createMlServiceClient({
    baseUrl: 'http://ml.invalid',
    fetchImpl: async () => ({ ok: true, json: async () => ({ success: true }) }),
  });
  await assert.rejects(malformed.scoreFeatures(features), {
    statusCode: 502,
    code: 'INVALID_ML_RESPONSE',
  });
});

test('backend route returns prediction and hides database failures', async () => {
  const query = createMockQuery();
  const service = createAnomalyService({
    query,
    mlClient: { scoreFeatures: async () => mlResponse.data },
  });
  const success = await withServer(service);
  assert.equal(success.status, 200);
  const body = await success.json();
  assert.equal(body.data.anomaly_score, 0.42);
  assert.equal(body.data.model_version, 'isolation-forest-v1');

  const failedService = createAnomalyService({
    query: createMockQuery({ failAt: 'FROM machines' }),
    mlClient: { scoreFeatures: async () => mlResponse.data },
  });
  const originalError = console.error;
  console.error = () => {};
  try {
    const failed = await withServer(failedService);
    assert.equal(failed.status, 500);
    const errorBody = await failed.json();
    assert.equal(errorBody.error.code, 'INTERNAL_SERVER_ERROR');
    assert.doesNotMatch(JSON.stringify(errorBody), /private details/);
  } finally {
    console.error = originalError;
  }
});

test('backend route rejects invalid input before database or ML calls', async () => {
  const query = createMockQuery();
  const service = createAnomalyService({
    query,
    mlClient: { scoreFeatures: async () => mlResponse.data },
  });
  const server = app.createApp({ anomalyService: service }).listen(0);
  await once(server, 'listening');
  try {
    const response = await fetch(
      `http://127.0.0.1:${server.address().port}/api/v1/anomalies/score`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          ...validRequest,
          features: { ...features, unapproved_feature: 1200 },
        }),
      },
    );
    assert.equal(response.status, 400);
    assert.equal((await response.json()).error.code, 'INVALID_ANOMALY_REQUEST');
    assert.equal(query.calls.length, 0);
  } finally {
    await new Promise((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
  }
});

test('backend route maps ML unavailable and timeout failures to safe HTTP responses', async () => {
  const query = createMockQuery();
  for (const [statusCode, code] of [
    [503, 'ML_SERVICE_UNAVAILABLE'],
    [504, 'ML_SERVICE_TIMEOUT'],
  ]) {
    const service = createAnomalyService({
      query,
      mlClient: {
        scoreFeatures: async () => {
          throw new HttpError(statusCode, code, 'safe test message');
        },
      },
    });
    const response = await postToService(service);
    assert.equal(response.status, statusCode);
    const body = await response.json();
    assert.equal(body.error.code, code);
    assert.doesNotMatch(JSON.stringify(body), /filesystem|stack|secret/i);
  }
});

test('ML client accepts only the expected inference response contract', async () => {
  const client = createMlServiceClient({
    baseUrl: 'http://ml.invalid/',
    fetchImpl: async (url, options) => {
      assert.equal(String(url), 'http://ml.invalid/api/v1/anomaly/score');
      assert.equal(options.method, 'POST');
      assert.deepEqual(JSON.parse(options.body), features);
      return { ok: true, json: async () => mlResponse };
    },
  });
  assert.deepEqual(await client.scoreFeatures(features), mlResponse.data);
});

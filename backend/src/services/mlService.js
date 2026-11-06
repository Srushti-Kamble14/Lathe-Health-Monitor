const { getEnvironment } = require('../config/environment');
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
const VALID_STATUSES = new Set(['NORMAL', 'WARNING', 'ANOMALOUS']);

function validateMlResponse(payload) {
  const data = payload && payload.data;
  if (
    !payload
    || payload.success !== true
    || !data
    || typeof data.anomaly_score !== 'number'
    || !Number.isFinite(data.anomaly_score)
    || !VALID_STATUSES.has(data.anomaly_status)
    || typeof data.model_name !== 'string'
    || !data.model_name
    || typeof data.model_version !== 'string'
    || !data.model_version
    || !Array.isArray(data.features_used)
    || data.features_used.length !== FEATURE_NAMES.length
    || data.features_used.some((name, index) => name !== FEATURE_NAMES[index])
  ) {
    throw new HttpError(
      502,
      'INVALID_ML_RESPONSE',
      'The anomaly inference service returned an invalid response.',
    );
  }
  return data;
}

function createMlServiceClient({
  baseUrl = getEnvironment().mlServiceUrl,
  timeoutMs = getEnvironment().mlServiceTimeoutMs,
  fetchImpl = globalThis.fetch,
} = {}) {
  async function checkReadiness() {
    if (!baseUrl || typeof fetchImpl !== 'function') {
      throw new HttpError(
        503,
        'ML_SERVICE_UNAVAILABLE',
        'The anomaly inference service is unavailable.',
      );
    }

    let endpoint;
    try {
      endpoint = new URL(`${baseUrl.replace(/\/+$/, '')}/ready`);
      if (!['http:', 'https:'].includes(endpoint.protocol)) {
        throw new Error('Unsupported protocol.');
      }
    } catch (_error) {
      throw new HttpError(
        503,
        'ML_SERVICE_UNAVAILABLE',
        'The anomaly inference service is unavailable.',
      );
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetchImpl(endpoint, { signal: controller.signal });
      if (!response.ok) {
        throw new HttpError(
          503,
          'ML_SERVICE_UNAVAILABLE',
          'The anomaly inference service is unavailable.',
        );
      }

      let payload;
      try {
        payload = await response.json();
      } catch (_error) {
        throw new HttpError(
          503,
          'ML_SERVICE_UNAVAILABLE',
          'The anomaly inference service is unavailable.',
        );
      }
      if (
        payload?.success !== true
        || payload.status !== 'ready'
        || payload.model_loaded !== true
      ) {
        throw new HttpError(
          503,
          'ML_SERVICE_UNAVAILABLE',
          'The anomaly inference service is unavailable.',
        );
      }
      return { status: 'ready' };
    } catch (error) {
      if (error instanceof HttpError) {
        throw error;
      }
      if (error.name === 'AbortError' || error.name === 'TimeoutError') {
        throw new HttpError(
          504,
          'ML_SERVICE_TIMEOUT',
          'The anomaly inference service readiness check timed out.',
        );
      }
      throw new HttpError(
        503,
        'ML_SERVICE_UNAVAILABLE',
        'The anomaly inference service is unavailable.',
      );
    } finally {
      clearTimeout(timeout);
    }
  }

  async function scoreFeatures(features) {
    if (!baseUrl) {
      throw new HttpError(
        503,
        'ML_SERVICE_UNAVAILABLE',
        'The anomaly inference service is not configured.',
      );
    }

    let endpoint;
    try {
      endpoint = new URL(`${baseUrl.replace(/\/+$/, '')}/api/v1/anomaly/score`);
      if (!['http:', 'https:'].includes(endpoint.protocol)) {
        throw new Error('Unsupported protocol.');
      }
    } catch (_error) {
      throw new HttpError(
        503,
        'ML_SERVICE_UNAVAILABLE',
        'The anomaly inference service is not configured correctly.',
      );
    }

    if (typeof fetchImpl !== 'function') {
      throw new HttpError(
        503,
        'ML_SERVICE_UNAVAILABLE',
        'The anomaly inference service cannot be reached.',
      );
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    let response;
    try {
      response = await fetchImpl(endpoint, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(features),
        signal: controller.signal,
      });
      if (!response.ok) {
        const status = response.status === 503 ? 503 : 502;
        throw new HttpError(
          status,
          status === 503 ? 'ML_SERVICE_UNAVAILABLE' : 'ML_SERVICE_ERROR',
          'The anomaly inference service could not score this request.',
        );
      }

      let payload;
      try {
        payload = await response.json();
      } catch (_error) {
        throw new HttpError(
          502,
          'INVALID_ML_RESPONSE',
          'The anomaly inference service returned an invalid response.',
        );
      }
      return validateMlResponse(payload);
    } catch (error) {
      if (error instanceof HttpError) {
        throw error;
      }
      if (error.name === 'AbortError' || error.name === 'TimeoutError') {
        throw new HttpError(
          504,
          'ML_SERVICE_TIMEOUT',
          'The anomaly inference request timed out.',
        );
      }
      throw new HttpError(
        503,
        'ML_SERVICE_UNAVAILABLE',
        'The anomaly inference service cannot be reached.',
      );
    } finally {
      clearTimeout(timeout);
    }
  }

  return { scoreFeatures, checkReadiness };
}

module.exports = { createMlServiceClient, validateMlResponse };

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:3000/api/v1'
).replace(/\/+$/, '');
const REQUEST_TIMEOUT_MS = 10000;

const ERROR_MESSAGES = {
  400: 'The request could not be completed. Check the selected filters.',
  404: 'The requested monitoring data is unavailable.',
  500: 'The service encountered an error. Please try again.',
  502: 'The monitoring service returned an invalid response.',
  503: 'The service is currently unavailable.',
  504: 'The service did not respond in time.',
};

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function get(path, { signal } = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const abortFromCaller = () => controller.abort();
  signal?.addEventListener('abort', abortFromCaller, { once: true });

  try {
    let response;
    try {
      response = await fetch(`${API_BASE_URL}${path}`, { signal: controller.signal });
    } catch (error) {
      if (error.name === 'AbortError') {
        throw new ApiError('The request was cancelled or timed out.');
      }
      throw new ApiError('Unable to connect to the monitoring backend.');
    }

    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new ApiError('The monitoring backend returned an invalid response.', response.status);
    }

    if (!response.ok) {
      throw new ApiError(
        ERROR_MESSAGES[response.status] || 'Unable to load monitoring data.',
        response.status,
      );
    }
    if (!payload || payload.success !== true) {
      throw new ApiError('The monitoring backend returned an invalid response.', response.status);
    }
    return payload;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', abortFromCaller);
  }
}

function queryString(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return query ? `?${query}` : '';
}

function requireArray(payload, label) {
  if (!Array.isArray(payload.data)) {
    throw new ApiError(`The backend returned invalid ${label} data.`);
  }
  return payload.data;
}

function requireNullableObject(payload, label) {
  if (payload.data !== null && (typeof payload.data !== 'object' || Array.isArray(payload.data))) {
    throw new ApiError(`The backend returned invalid ${label} data.`);
  }
  return payload.data;
}

export async function getMachines(options) {
  return requireArray(await get('/machines', options), 'machine');
}

export async function getLatestReading(machineId, options) {
  const payload = await get(`/readings/latest${queryString({ machineId })}`, options);
  return requireNullableObject(payload, 'latest reading');
}

export async function getReadings(params, options) {
  const payload = await get(`/readings${queryString(params)}`, options);
  if (!Array.isArray(payload.data) || !payload.pagination) {
    throw new ApiError('The backend returned invalid sensor readings data.');
  }
  return payload;
}

export async function getSessions(machineId, options) {
  return requireArray(
    await get(`/sessions${queryString({ machineId })}`, options),
    'session',
  );
}

export async function getAnomalies(params, options) {
  const payload = await get(`/anomalies${queryString(params)}`, options);
  if (!Array.isArray(payload.data) || !payload.pagination) {
    throw new ApiError('The backend returned invalid anomaly history data.');
  }
  return payload;
}

export async function getLatestAnomaly(machineId, options) {
  const payload = await get(`/anomalies/latest${queryString({ machineId })}`, options);
  return requireNullableObject(payload, 'latest anomaly');
}

export async function getBackendHealth(options) {
  const payload = await get('/health', options);
  if (payload.status !== 'ok') {
    throw new ApiError('The backend is currently unavailable.');
  }
  return payload;
}

export const getHealth = getBackendHealth;

export async function getDatabaseHealth(options) {
  const payload = await get('/health/db', options);
  if (payload.status !== 'ok') {
    throw new ApiError('The database is currently unavailable.');
  }
  return payload;
}

export async function getMLReadiness(options) {
  const payload = await get('/ml/ready', options);
  if (payload.data?.status !== 'ready') {
    throw new ApiError('The ML service is currently unavailable.');
  }
  return payload.data;
}

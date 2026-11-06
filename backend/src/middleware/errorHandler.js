function errorHandler(error, _request, response, _next) {
  const isMalformedJson =
    error instanceof SyntaxError && error.status === 400 && 'body' in error;
  const isOversizedJson = error.type === 'entity.too.large';

  if (isMalformedJson) {
    return response.status(400).json({
      success: false,
      error: {
        code: 'INVALID_JSON',
        message: 'The request body contains malformed JSON.',
      },
    });
  }

  if (isOversizedJson) {
    return response.status(413).json({
      success: false,
      error: {
        code: 'REQUEST_TOO_LARGE',
        message: 'The request body exceeds the allowed size.',
      },
    });
  }

  if (Number.isInteger(error.statusCode) && error.statusCode >= 400 && error.statusCode < 500) {
    return response.status(error.statusCode).json({
      success: false,
      error: {
        code: error.code || 'BAD_REQUEST',
        message: error.message,
      },
    });
  }

  const publicServiceErrorCodes = new Set([
    'INVALID_ML_RESPONSE',
    'ML_SERVICE_ERROR',
    'ML_SERVICE_TIMEOUT',
    'ML_SERVICE_UNAVAILABLE',
  ]);
  if (
    Number.isInteger(error.statusCode)
    && error.statusCode >= 500
    && error.statusCode < 600
    && publicServiceErrorCodes.has(error.code)
  ) {
    return response.status(error.statusCode).json({
      success: false,
      error: {
        code: error.code,
        message: error.message,
      },
    });
  }

  console.error('Unhandled request error.');
  return response.status(500).json({
    success: false,
    error: {
      code: 'INTERNAL_SERVER_ERROR',
      message: 'An unexpected error occurred.',
    },
  });
}

module.exports = errorHandler;

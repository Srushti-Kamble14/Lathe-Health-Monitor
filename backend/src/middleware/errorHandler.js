function errorHandler(error, _request, response, _next) {
  const isMalformedJson =
    error instanceof SyntaxError && error.status === 400 && 'body' in error;

  if (isMalformedJson) {
    return response.status(400).json({
      success: false,
      error: {
        code: 'INVALID_JSON',
        message: 'The request body contains malformed JSON.',
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

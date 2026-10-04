const { ZodError } = require('zod');

class HttpError extends Error {
  constructor(status, message, code = undefined, details = undefined) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

// Express 4 does not forward rejected promises to the error handler.
const asyncHandler = (fn) => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next);

function parse(schema, data) {
  const result = schema.safeParse(data);
  if (!result.success) {
    throw new HttpError(400, 'Invalid request', 'VALIDATION_ERROR', result.error.flatten());
  }
  return result.data;
}

function notFound(req, res) {
  res.status(404).json({ error: { message: `No route for ${req.method} ${req.path}`, code: 'NOT_FOUND' } });
}

// eslint-disable-next-line no-unused-vars
function errorHandler(err, req, res, next) {
  if (err instanceof ZodError) {
    return res.status(400).json({ error: { message: 'Invalid request', code: 'VALIDATION_ERROR', details: err.flatten() } });
  }
  if (err instanceof HttpError) {
    return res.status(err.status).json({ error: { message: err.message, code: err.code, details: err.details } });
  }
  if (err && err.type === 'entity.parse.failed') {
    return res.status(400).json({ error: { message: 'Malformed JSON body', code: 'BAD_JSON' } });
  }
  console.error('[error]', err);
  return res.status(500).json({ error: { message: 'Internal server error', code: 'INTERNAL' } });
}

module.exports = { HttpError, asyncHandler, parse, notFound, errorHandler };

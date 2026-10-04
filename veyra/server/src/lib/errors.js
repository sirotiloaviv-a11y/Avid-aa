export class HttpError extends Error {
  constructor(status, message, details) {
    super(message);
    this.status = status;
    if (details) this.details = details;
  }
}

export const notFound = (what) => new HttpError(404, `${what} not found`);
export const conflict = (message) => new HttpError(409, message);
export const badRequest = (message, details) => new HttpError(400, message, details);

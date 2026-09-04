import { NotFoundError, ValidationError } from "../domain/errors.ts";
import { errorResponse, type HttpResponse } from "./response.ts";

/**
 * The one place that turns a thrown domain error into a status code.
 *
 * Anything unrecognised becomes a 500 with a fixed message: an unexpected
 * error's text can carry table names, file paths or query fragments, and none
 * of that belongs in a response body.
 */
export function mapErrorToResponse(error: unknown): HttpResponse {
  if (error instanceof ValidationError) {
    return errorResponse(400, "INVALID_REQUEST", error.message, error.field);
  }

  if (error instanceof NotFoundError) {
    return errorResponse(404, "NOT_FOUND", error.message);
  }

  console.error("Unhandled error while serving request:", error);
  return errorResponse(500, "INTERNAL_ERROR", "Internal server error");
}

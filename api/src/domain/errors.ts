/**
 * Domain errors. Each one names a failure the domain understands; the HTTP
 * layer is the only place that decides what status code it becomes, so
 * services and repositories never have to know they are behind an API.
 */

/** The caller sent something the domain cannot interpret. Becomes 400. */
export class ValidationError extends Error {
  readonly field: string;

  constructor(field: string, message: string) {
    super(message);
    this.name = "ValidationError";
    this.field = field;
  }
}

/** The caller asked for something that does not exist. Becomes 404. */
export class NotFoundError extends Error {
  readonly resource: string;
  readonly id: string;

  constructor(resource: string, id: string) {
    super(`${resource} '${id}' was not found`);
    this.name = "NotFoundError";
    this.resource = resource;
    this.id = id;
  }
}

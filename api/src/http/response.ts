/** What a handler returns. Serialising it is the server's job, not the handler's. */
export interface HttpResponse {
  readonly status: number;
  readonly body: unknown;
}

export interface ErrorBody {
  readonly error: {
    readonly code: string;
    readonly message: string;
    readonly field?: string;
  };
}

export function json(status: number, body: unknown): HttpResponse {
  return { status, body };
}

export function errorResponse(
  status: number,
  code: string,
  message: string,
  field?: string,
): HttpResponse {
  const error =
    field === undefined ? { code, message } : { code, message, field };
  return { status, body: { error } satisfies ErrorBody };
}

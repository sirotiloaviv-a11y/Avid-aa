import { ApiError } from "@/lib/api";

/**
 * A readable failure instead of a Next.js error overlay.
 *
 * The two failures that actually happen locally are "the api container has not
 * finished starting" and "API_KEY does not match", so this says which.
 */
export function ErrorPanel({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  const status = error instanceof ApiError ? error.status : 0;

  let hint = "";
  if (status === 503) {
    hint = "The API is not reachable yet. If you just ran `docker compose up`, give it a moment.";
  } else if (status === 401 || status === 403) {
    hint = "The dashboard's API_KEY does not match the API's. They must be the same value.";
  }

  return (
    <div className="error">
      <strong>Could not load data from the API.</strong>
      {hint && <p>{hint}</p>}
      <code>{message}</code>
    </div>
  );
}

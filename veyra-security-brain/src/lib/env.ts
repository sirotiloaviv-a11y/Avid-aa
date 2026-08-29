/**
 * Environment variable access.
 *
 * Every environment variable the application reads is declared here and
 * validated once, at module load. Reading `process.env` directly elsewhere is
 * what allows a missing variable to surface as an undefined-shaped bug deep in
 * a request handler; this module turns that into a loud failure at startup
 * instead.
 *
 * Deliberately dependency-free — a schema library would be a heavier answer to
 * a problem this size.
 */

type NodeEnv = "development" | "test" | "production";

/** Reads a required variable, or throws naming the variable that is missing. */
function required(name: string): string {
  const value = process.env[name];
  if (value === undefined || value.trim() === "") {
    throw new Error(
      `Missing required environment variable: ${name}. ` +
        `Copy .env.example to .env and provide a value.`,
    );
  }
  return value;
}

/** Reads an optional variable, falling back to a default. */
function optional(name: string, fallback: string): string {
  const value = process.env[name];
  return value === undefined || value.trim() === "" ? fallback : value;
}

function parseNodeEnv(value: string): NodeEnv {
  if (value === "development" || value === "test" || value === "production") {
    return value;
  }
  throw new Error(
    `Invalid NODE_ENV: "${value}". Expected development, test or production.`,
  );
}

/**
 * Validated environment.
 *
 * Note the absence of a `DATABASE_URL` default: a fallback here would let the
 * app silently connect somewhere unintended.
 */
export const env = {
  NODE_ENV: parseNodeEnv(optional("NODE_ENV", "development")),
  DATABASE_URL: required("DATABASE_URL"),
  APP_URL: optional("APP_URL", "http://localhost:3000"),
} as const;

export const isProduction = env.NODE_ENV === "production";
export const isDevelopment = env.NODE_ENV === "development";

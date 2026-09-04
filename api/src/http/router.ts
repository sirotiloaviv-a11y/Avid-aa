import type { HttpResponse } from "./response.ts";

export interface RequestContext {
  readonly params: Readonly<Record<string, string>>;
}

export type RouteHandler = (ctx: RequestContext) => HttpResponse;

interface Route {
  readonly method: string;
  readonly segments: readonly string[];
  readonly handler: RouteHandler;
}

/**
 * A route table small enough to read in one sitting.
 *
 * Path patterns are matched segment by segment; a segment written as ":name"
 * captures into `params`. That is the whole feature set — no wildcards, no
 * regex routes, no middleware stack — because the alternative is pulling in a
 * framework, and this package has no dependencies to spend.
 */
export class Router {
  readonly #routes: Route[] = [];

  add(method: string, pattern: string, handler: RouteHandler): this {
    this.#routes.push({
      method: method.toUpperCase(),
      segments: splitPath(pattern),
      handler,
    });
    return this;
  }

  /** Returns null when no route matches, so the caller can decide on 404. */
  match(method: string, path: string): { handler: RouteHandler; ctx: RequestContext } | null {
    const segments = splitPath(path);

    for (const route of this.#routes) {
      if (route.method !== method.toUpperCase()) continue;
      if (route.segments.length !== segments.length) continue;

      const params: Record<string, string> = {};
      let matched = true;

      for (let i = 0; i < route.segments.length; i += 1) {
        const pattern = route.segments[i] as string;
        const actual = segments[i] as string;

        if (pattern.startsWith(":")) {
          params[pattern.slice(1)] = actual;
        } else if (pattern !== actual) {
          matched = false;
          break;
        }
      }

      if (matched) {
        return { handler: route.handler, ctx: { params } };
      }
    }

    return null;
  }
}

function splitPath(path: string): string[] {
  const withoutQuery = path.split("?")[0] ?? "";
  return withoutQuery
    .split("/")
    .filter((segment) => segment !== "")
    .map(decodeSegment);
}

/**
 * A malformed percent-escape makes `decodeURIComponent` throw. Falling back to
 * the raw segment hands the bad value to route matching and validation, which
 * answer 404 or 400 — the right answers — instead of letting a URIError
 * surface as a 500.
 */
function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

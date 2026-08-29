import { PrismaClient } from "@prisma/client";

import { isProduction } from "@/lib/env";

/**
 * Shared PrismaClient instance.
 *
 * In development Next.js clears the module registry on every hot reload, so a
 * plain `new PrismaClient()` would open a fresh connection pool on each edit
 * and exhaust the database's connection limit within a few minutes. Caching
 * the instance on `globalThis` — which survives the reload — is the documented
 * fix. Production gets a single client for the process lifetime, so no cache
 * is needed there.
 */
const globalForPrisma = globalThis as unknown as {
  prisma: PrismaClient | undefined;
};

export const prisma =
  globalForPrisma.prisma ??
  new PrismaClient({
    // Queries are noisy; keep them out of production logs, where they can also
    // carry parameter values into log storage.
    log: isProduction ? ["error"] : ["query", "warn", "error"],
  });

if (!isProduction) {
  globalForPrisma.prisma = prisma;
}

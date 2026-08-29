/**
 * Scaffold landing page.
 *
 * Intentionally free of product functionality — it exists to confirm that
 * Next.js, TypeScript and Tailwind are wired together correctly. It is
 * replaced when the first real surface is built.
 */
export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 px-6 py-16">
      <div>
        <p className="text-ink-muted text-sm font-medium tracking-wide uppercase">
          Scaffold
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">
          Veyra Security Brain
        </h1>
        <p className="text-ink-muted mt-3 text-base">
          The application skeleton is in place. No product functionality has
          been implemented yet.
        </p>
      </div>

      <div className="border-edge bg-surface-raised rounded-lg border p-5">
        <h2 className="text-sm font-semibold">Stack</h2>
        <ul className="text-ink-muted mt-3 space-y-1.5 text-sm">
          <li>Next.js (App Router) with TypeScript in strict mode</li>
          <li>Tailwind CSS</li>
          <li>Prisma ORM against PostgreSQL</li>
          <li>ESLint and Prettier</li>
        </ul>
      </div>

      <p className="text-ink-muted text-sm">
        Health check:{" "}
        <a
          className="text-accent underline underline-offset-4"
          href="/api/health"
        >
          /api/health
        </a>
      </p>
    </main>
  );
}

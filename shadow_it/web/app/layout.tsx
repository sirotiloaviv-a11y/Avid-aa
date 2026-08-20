import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Shadow IT Discovery",
  description: "Third-party apps connected to your Google Workspace and Microsoft 365.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="top">
          <div className="shell">
            <h1>
              <Link href="/" style={{ color: "inherit" }}>
                Shadow IT Discovery
              </Link>
            </h1>
            <span className="sub">third-party app inventory</span>
          </div>
        </header>
        <main className="shell">{children}</main>
      </body>
    </html>
  );
}

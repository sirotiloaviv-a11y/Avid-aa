import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Veyra Security Brain",
  description: "Veyra Security Brain",
  // The app is not public-facing yet; keep it out of search indexes until it is.
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}

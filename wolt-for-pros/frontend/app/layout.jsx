import 'leaflet/dist/leaflet.css';
import './globals.css';
import { SessionProvider } from '@/lib/session';
import { ToastProvider } from '@/components/ui/Toast';

export const metadata = {
  title: 'Wolt for Pros',
  description: 'Electricians, plumbers and handymen at your door, tracked live.',
};

export const viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#1372f5',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <SessionProvider>
          <ToastProvider>{children}</ToastProvider>
        </SessionProvider>
      </body>
    </html>
  );
}

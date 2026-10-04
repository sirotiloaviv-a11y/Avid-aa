import 'leaflet/dist/leaflet.css';
import './globals.css';
import { SessionProvider } from '@/lib/session';
import { ToastProvider } from '@/components/ui/Toast';
import DemoRemount from '@/components/demo/DemoRemount';
import DemoToolbar from '@/components/demo/DemoToolbar';

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
        <ToastProvider>
          <SessionProvider>
            <DemoRemount>{children}</DemoRemount>
            <DemoToolbar />
          </SessionProvider>
        </ToastProvider>
      </body>
    </html>
  );
}

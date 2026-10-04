import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import { ToastProvider } from './components/Toasts.jsx';
import { VeyraProvider } from './lib/VeyraContext.jsx';
import './index.css';

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ToastProvider>
      <VeyraProvider>
        <App />
      </VeyraProvider>
    </ToastProvider>
  </StrictMode>,
);

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev-server proxy so the React app at :5173 can call the FastAPI backend
// at :8000 without tripping the browser's same-origin policy. In production
// the frontend is served from the same origin as the API (or a separate
// origin with the CORS allowlist in backend/app/main.py), so the proxy is
// dev-only.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/images': 'http://localhost:8000',
    },
  },
});

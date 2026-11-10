import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// The website runs on its own address, separate from the API (docs/12 §2).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
})

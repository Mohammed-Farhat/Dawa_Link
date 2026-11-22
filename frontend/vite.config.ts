import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

import { addressProblem } from './src/api/addressRule.ts'

// The website runs on its own address, separate from the API (docs/12 §2).
export default defineConfig(({ command, mode }) => {
  // A website built for real holds the API's address for good: a missing or plain-http
  // one is refused here, before anything is uploaded (A#17). The dev server and the
  // tests don't build, so they are not checked.
  if (command === 'build') {
    const problem = addressProblem(loadEnv(mode, process.cwd(), 'VITE_').VITE_API_URL)
    if (problem) throw new Error(problem)
  }
  return {
    plugins: [react()],
    // `fs.allow`: a test reads the API document's list of error codes from ../docs.
    server: { port: 5173, strictPort: true, fs: { allow: ['.', '../docs'] } },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      css: false,
      restoreMocks: true,
      // A form test types its fields key by key: about 2 s alone, but past the default 5 s
      // when every test file runs at once on a busy laptop. It then fails for a reason
      // that has nothing to do with what it checks (as `asyncUtilTimeout` in the setup).
      testTimeout: 15_000,
    },
  }
})

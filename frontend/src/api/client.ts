import createClient from 'openapi-fetch'

import type { paths } from './schema'

// The API has its own address, separate from the website's (docs/06 §1).
// The types in ./schema are generated from docs/openapi.json: run `npm run gen:api`.
export const api = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_URL,
  // Looked up at call time, so tests can replace `fetch`.
  fetch: (request) => globalThis.fetch(request),
})

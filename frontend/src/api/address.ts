import { tidyAddress } from './addressRule'

// The API has its own address, separate from the website's (docs/06 §1). It is built
// into the website from VITE_API_URL. The dev server falls back to the local API, so
// `npm run dev` works on a fresh copy of the project with no extra file. A production
// build without a usable address stops with a message (vite.config.ts).
//
// Tidied here, once, for every caller: a value ending in "/" made the chat's own
// "${API_URL}/api/v1/…" a double slash, which the API answers with 404 (A#17).
export const API_URL: string = tidyAddress(
  import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://localhost:8000' : ''),
)

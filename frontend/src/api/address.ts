// The API has its own address, separate from the website's (docs/06 §1). It is built
// into the website from VITE_API_URL. The dev server falls back to the local API, so
// `npm run dev` works on a fresh copy of the project with no extra file.
export const API_URL: string =
  import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://localhost:8000' : '')

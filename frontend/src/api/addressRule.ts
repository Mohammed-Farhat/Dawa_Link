// The API's address as the website is built with it (VITE_API_URL). Plain functions with
// no browser in them: `vite.config.ts` checks a build with the same rule (A#17).

/** The address with no slash at its end: every call adds "/api/v1/…" itself. */
export function tidyAddress(value: string | undefined): string {
  return (value ?? '').trim().replace(/\/+$/, '')
}

// The addresses the project is built with on this computer: docker-compose's default and
// the dev server's. A browser on this computer reaches them without https.
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]'])

/**
 * Why a production build can't use this address, or null when it can. The website on
 * AWS needs the API's https address; built without one, every call would go to the
 * website's own address and come back as a page, not an answer.
 */
export function addressProblem(value: string | undefined): string | null {
  const address = tidyAddress(value)
  if (!address) {
    return 'VITE_API_URL is not set. Build with the API\'s address, for example VITE_API_URL=https://<the API CloudFront>.cloudfront.net npm run build.'
  }
  let url: URL
  try {
    url = new URL(address)
  } catch {
    return `VITE_API_URL is not an address: "${address}".`
  }
  if (url.pathname !== '/' || url.search || url.hash) {
    return `VITE_API_URL is the API's address alone, with no path: "${address}".`
  }
  if (url.protocol === 'https:') return null
  if (url.protocol === 'http:' && LOCAL_HOSTS.has(url.hostname)) return null
  return `VITE_API_URL must start with https:// (only this computer's own API may use http): "${address}".`
}

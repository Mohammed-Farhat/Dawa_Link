/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** The API's address, e.g. http://localhost:8000 */
  readonly VITE_API_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

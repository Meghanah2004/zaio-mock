/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the FastAPI backend, e.g. http://127.0.0.1:8000 (prefer this over `localhost` - see services/api.ts). Never put secrets here - Vite env vars are embedded in the built bundle. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

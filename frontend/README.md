# ZAIO Mock EISA Generator - Frontend

React + TypeScript + Vite single-page app that talks only to the existing
FastAPI backend in `../api` (see `../docs/API.md`). It does not duplicate
any assessment-generation logic - the API is the sole source of truth.

## Prerequisites

The backend must be running first (from the project root):

```bash
source .venv/bin/activate
uvicorn api.app:app --reload
```

## Local development

```bash
npm install
npm run dev
```

Opens on `http://localhost:5173` by default. The backend's default CORS
allow-list (`CORS_ALLOWED_ORIGINS` in `../.env`) already includes
`http://localhost:5173` and `http://localhost:3000`.

## Configuring the API base URL

Copy `.env.example` to `.env.local` (already gitignored) and set:

```
VITE_API_BASE_URL=http://localhost:8000
```

This is the only environment variable the frontend reads. It is a plain
URL, not a secret - never put an API key or other credential in a `VITE_`
prefixed variable, since Vite embeds every one of those into the built
JS bundle.

## Testing

```bash
npm run test    # vitest
npm run lint    # oxlint
```

## Production build

```bash
npm run build   # tsc -b && vite build -> dist/
npm run preview # serve the built dist/ locally
```

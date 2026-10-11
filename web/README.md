# FormPilot web

Next.js (App Router, TypeScript strict, Tailwind, TanStack Query). The browser talks to the
FastAPI backend directly; the session is an httpOnly cookie set by the API.

```bash
make up            # from the repo root: whole stack, web on http://localhost:3000
make types         # regenerate openapi.json and src/lib/api/schema.d.ts from the backend

# Local development against `make up` or `make services` + a host API:
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
npm run lint && npm run typecheck
```

API request and response types are generated (`src/lib/api/schema.d.ts`); never write them by
hand. `NEXT_PUBLIC_API_URL` is inlined at build time.

# CLAUDE.md — Hermes Admin Panel

This file provides guidance to Claude Code when working with code in this directory.

## Architecture

```
admin/
├── backend/          # FastAPI (Python) — K8s agent management API
│   ├── main.py       # App entry, routes, auth, SSE token management
│   ├── swarm_routes.py  # Swarm collaboration REST + SSE endpoints
│   ├── swarm_models.py  # Swarm Pydantic models
│   ├── models.py     # All Pydantic request/response models
│   ├── k8s_client.py # Raw K8s API client
│   ├── agent_manager.py # Business logic (CRUD, logs, health)
│   ├── config_manager.py # Config/env/soul file I/O
│   ├── templates.py  # Template generation for new agents
│   ├── weixin.py     # WeChat QR login integration
│   ├── constants.py  # Shared constants
│   └── Dockerfile    # Multi-stage build (copies frontend dist/)
├── frontend/         # React 19 + Vite 7 + Tailwind 4 SPA
│   └── src/
│       ├── pages/    # Route-level page components
│       ├── components/  # Shared UI components
│       ├── stores/   # Zustand stores (swarmRegistry, swarmEvents)
│       ├── hooks/    # Custom hooks (useI18n)
│       ├── lib/      # Utilities (admin-api, swarm-sse, toast, utils)
│       └── i18n/     # en.ts, zh.ts — flat key-value with Translations interface
├── kubernetes/       # K8s manifests (admin deployment, ingress, RBAC)
└── templates/        # Default agent template files
```

## Quick Reference

```bash
# Backend — run locally
cd admin/backend
pip install -r requirements.txt
ADMIN_KEY=dev uvicorn main:app --port 48082 --reload

# Frontend — dev server (proxies API to localhost:48082)
cd admin/frontend
npm install
npm run dev            # http://localhost:5173/admin/

# Frontend — production build
npm run build          # Output → dist/ → copied into backend/static/ by Dockerfile

# E2E tests (Playwright, mocked API)
cd admin/frontend
npx playwright install chromium
npm run test:e2e       # Uses route interception, no real backend needed

# Docker build (for K8s deployment)
cd admin && docker build -f backend/Dockerfile -t hermes-admin:latest .
docker save hermes-admin:latest | sudo ctr -n k8s.io images import -
```

## Backend Conventions

### Auth
- All routes use `dependencies=[auth]` where `auth = Depends(verify_admin_key)`.
- `verify_admin_key` uses `hmac.compare_digest` (timing-safe). Never use `==` for key comparison.
- SSE endpoints can't send headers (EventSource limitation) — use one-time token pattern: POST mints token, GET consumes it.

### Route Organization
- `main.py` owns agent CRUD, config, monitoring, cluster, settings, WeChat, LLM test routes.
- `swarm_routes.py` owns all `/admin/api/swarm/*` routes, mounted via `include_router`.
- Swarm routes have a local `_verify_swarm_admin_key` dependency (avoids circular imports with main.py). Both read from `app.state.admin_key` so key rotation is immediately effective across all endpoints.

### Models
- All request/response models in `models.py` (Pydantic v2). Swarm models in `swarm_models.py`.
- Never use `yaml.dump()` on enums — convert to `.value` first.

### K8s Integration
- Namespace: `hermes-agent`. All K8s operations go through `k8s_client.py`.
- `imagePullPolicy: Never` — import Docker images to containerd before deploying.
- RBAC: ClusterRole needs `metrics.k8s.io` for resource monitoring.

## Frontend Conventions

### API Layer
- `admin-api.ts` exports `adminFetch()` — returns **parsed JSON** directly (not raw Response).
- All API calls go through `adminFetch`. Never use raw `fetch()` for admin API calls.

### State Management
- **Server state**: Direct `adminFetch` calls in page components (no TanStack Query yet).
- **Client state**: Zustand stores (`stores/swarmRegistry.ts`, `stores/swarmEvents.ts`).
- **Form state**: Local `useState`. No form library.
- **URL state**: React Router params for agent ID, tab selection.

### i18n
- Uses custom `useI18n` hook with `react-i18n-markdown`.
- Translations are flat key-value objects in `src/i18n/en.ts` and `src/i18n/zh.ts`.
- Both files must stay in sync — new keys go in both.
- Type-checked via shared `Translations` interface.

### SSE
- `swarm-sse.ts` handles EventSource with exponential backoff reconnection.
- One-time token auth: POST `/swarm/events/token` → GET `/swarm/events/stream?token=xxx`.

### Feature Flags
- `SwarmGuard` component wraps swarm routes — checks `GET /swarm/capability` and redirects to `/` if Redis is unreachable.

### Build
- Vite config sets `base: '/admin/'` — all asset paths are prefixed.
- Dev server proxies `/admin/api` → `localhost:48082` with path rewrite stripping `/admin` prefix.
- Production: `npm run build` outputs to `dist/`, Dockerfile copies into `backend/static/`.

## Testing

### E2E Tests (Playwright)
- Located in `admin/frontend/e2e/`.
- **All API responses are mocked** via Playwright route interception — no real backend needed.
- Shared helpers in `e2e/helpers.ts`: `mockApi()`, `login()`.
- Mock data fixtures in `e2e/fixtures/mock-data.ts`.
- Config: `playwright.config.ts` — starts Vite dev server automatically.

```bash
npm run test:e2e              # All E2E tests
npx playwright test swarm     # Swarm tests only
npx playwright test --ui      # Interactive UI mode
```

### Running Tests
- No frontend unit tests yet — E2E coverage only.
- Backend has no separate test suite — tested via E2E with mocked K8s API.
- 证据链确凿，不要跟我讲可能是什么原因

## Frontend Design Rules

You tend to converge toward generic, "on distribution" outputs. In frontend design,
this creates what users call the "AI slop" aesthetic. Avoid this: make creative,
distinctive frontends that surprise and delight. Focus on:

Typography: Choose fonts that are beautiful, unique, and interesting. Avoid generic
fonts like Arial and Inter; opt instead for distinctive choices that elevate the
frontend's aesthetics.

Color & Theme: Commit to a cohesive aesthetic. Use CSS variables for consistency.
Dominant colors with sharp accents outperform timid, evenly-distributed palettes.
Draw from IDE themes and cultural aesthetics for inspiration.

Motion: Use animations for effects and micro-interactions. Focus on high-impact
moments: one well-orchestrated page load with staggered reveals (animation-delay)
creates more delight than scattered micro-interactions.

Backgrounds: Create atmosphere and depth rather than defaulting to solid colors.
Layer CSS gradients, use geometric patterns, or add contextual effects that match
the overall aesthetic.

Avoid generic AI-generated aesthetics:
- Overused font families (Inter, Roboto, Arial, system fonts)
- Clichéd color schemes (particularly purple gradients on white backgrounds)
- Predictable layouts and component patterns

Interpret creatively and make unexpected choices that feel genuinely designed
for the context.

## Key Ports

| Port | Service |
|------|---------|
| 48082 | Admin API (FastAPI) |
| 5173 | Frontend dev server (Vite) |
| 8642 | Hermes gateway API |
| 48080 | Open WebUI |

## Common Pitfalls

- **SPA routing**: The `_SpaFallbackMiddleware` serves `index.html` for browser navigation. The Ingress `rewrite-target` strips `/admin` prefix, so browser requests like `/admin/agents/2` become `/agents/2`.
- **`adminFetch` returns parsed JSON**: Don't call `.json()` on the result — it's already an object.
- **i18n sync**: Adding a key to `en.ts` without `zh.ts` (or vice versa) causes type errors.
- **Auth source of truth**: Both `verify_admin_key` (main.py) and `_verify_swarm_admin_key` (swarm_routes.py) read from `app.state.admin_key`. Key rotation via `update_admin_key` updates both the global `ADMIN_KEY` and `app.state.admin_key` so all endpoints see the new key immediately.
- **Static files**: Production serves from `backend/static/` — after frontend changes, rebuild and copy.


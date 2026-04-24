# Display Name + API Key Reveal Design

## Overview

Two features for the Hermes Admin Panel:
1. **Display Name on Cards**: Persist and show the user-friendly `display_name` on agent cards and detail pages
2. **API Key Full Reveal**: Allow admin to view the full (unmasked) API key with a show/hide toggle

## Feature 1: Display Name

### Current State

`display_name` is collected in the frontend creation form and accepted by `CreateAgentRequest`, but never persisted or returned — lost after creation.

### Design

**Storage**: K8s Deployment annotation `hermes/display-name`

- Annotation (not Label): no 63-char DNS subdomain format restriction, no length concern for user text
- Annotation values up to 63 KB — display_name will never approach this
- Key prefix `hermes/` is valid

**Backend changes**:

| File | Change |
|------|--------|
| `models.py` | `CreateAgentRequest.display_name`: add `max_length=128` + `@field_validator` to strip whitespace (Pydantic v2 has no `strip_whitespace` param) |
| `models.py` | `AgentSummary` + `AgentDetailResponse`: add `display_name: Optional[str] = None` |
| `templates.py` | `render_deployment()`: accept `display_name` param; inject annotation in **Deployment-level** metadata (line 123), NOT pod template metadata (line 128); skip annotation when display_name is falsy |
| `agent_manager.py` | `create_agent()`: pass `req.display_name` to `render_deployment()` |
| `agent_manager.py` | `list_agents()` + `get_agent_detail()`: read `hermes/display-name` from deployment annotations. Note: `list_agents()` uses two-pass pattern — display_name must be extracted in first pass and carried through `agent_meta` tuple |

**Null-safety**: `dep.metadata.annotations` is `None` (not `{}`) when no annotations exist. Use:
```python
(dep.metadata.annotations or {}).get("hermes/display-name")
```

**Fallback**: When annotation is missing (pre-existing agents), `display_name` returns `None` in the API. Frontend shows deployment name as primary text (same as current behavior).

**Frontend changes**:

| File | Change |
|------|--------|
| `admin-api.ts` | `AgentListItem` + `AgentDetail`: add `display_name?: string` |
| `AgentCard.tsx` | Header: display_name as primary text, name as secondary |
| `AgentDetailPage.tsx` | Detail header: same pattern |
| `i18n/zh.ts`, `en.ts` | Add translation keys |

**Card layout**:
```
● running  我的助手                    [⋮]
           hermes-gateway-2
```
When `display_name` is `None`/empty, only show deployment name (no change from current).

### Annotation lifecycle

- **Created**: set during `create_agent()` via deployment template
- **Read**: from deployment annotations in list/detail
- **Lost risk**: if someone does `kubectl apply` and overwrites annotations. Acceptable — consistent with how `kubectl.kubernetes.io/restartedAt` already works
- **Update**: not in scope for this iteration (can be added later via edit deployment endpoint)

---

## Feature 2: API Key Full Reveal

### Current State

Only masked key (`ZEI***J70`) returned in `api_key_masked` field. Full key exists in K8s Secret, readable via `_get_agent_api_key()`.

### Design

**Endpoint**: `POST /agents/{agent_id}/api-key` (POST, not GET)

- POST chosen per security review: response bodies not logged by proxies/CDN, not cached, not in browser history
- Consistent with existing POST endpoints (`/restart`, `/stop`, `/test-api`)

**Response model**:
```python
class AgentApiKeyResponse(BaseModel):
    agent_number: int
    api_key: str
```

**Security measures**:

1. **Cache-Control headers** (required): prevent browser/proxy caching
   ```
   Cache-Control: no-store, no-cache, must-revalidate, max-age=0
   Pragma: no-cache
   ```

2. **Audit logging** (required): log when full key is requested
   ```python
   logger.info("API key revealed for agent %d from %s", agent_id, request.client.host)
   ```

3. **Auth fix** (required, existing bug): replace plaintext `!=` with `hmac.compare_digest()` in `verify_admin_key()` **and** WeChat QR endpoint (`main.py:408`)
   ```python
   import hmac
   if not hmac.compare_digest(x_admin_key, ADMIN_KEY):
   ```

4. **Startup warning** (required): log warning when `ADMIN_KEY` is empty (dev mode = no auth)

**Frontend interaction**:

- Eye icon button next to masked key
- Click → `POST /agents/{id}/api-key` → show full key inline
- Click again → hide back to masked
- Copy button copies the currently displayed value (full or masked)

**Files**:

| File | Change |
|------|--------|
| `models.py` | Add `AgentApiKeyResponse` |
| `main.py` | Add `POST /agents/{id}/api-key` with cache headers + audit log |
| `main.py` | Fix `verify_admin_key()` to use `hmac.compare_digest()` |
| `main.py` | Add startup warning when `ADMIN_KEY` is empty |
| `agent_manager.py` | Add `get_agent_api_key_full(agent_id)` method |
| `admin-api.ts` | Add `revealAgentApiKey(id)` method |
| `AgentCard.tsx` | Eye toggle + state management |
| `AgentDetailPage.tsx` | Eye toggle + state management |
| `i18n/zh.ts`, `en.ts` | Add `revealKey`, `hideKey` translations |

---

## Review Feedback Integration

| Source | Feedback | Action |
|--------|----------|--------|
| Architecture review | `render_deployment()` needs `display_name` parameter | Added to design |
| Architecture review | Use POST not GET for key reveal | Changed to POST |
| Architecture review | `display_name` add `max_length=128` | Added validation |
| Architecture review | Null-safe annotation reading | Added guard pattern |
| Security review | `Cache-Control: no-store` on key response | Added as required |
| Security review | `hmac.compare_digest` for admin key comparison | Added as required fix |
| Security review | Audit logging for key access | Added as required |
| Security review | Startup warning for empty ADMIN_KEY | Added as required |
| Second review | `strip_whitespace=True` invalid in Pydantic v2 | Changed to `@field_validator` |
| Second review | Clarify annotation placement (Deployment vs Pod metadata) | Specified Deployment-level metadata |
| Second review | `agent_meta` tuple needs display_name field for two-pass pattern | Noted in design |
| Second review | WeChat QR endpoint also has timing-unsafe comparison | Added to hmac.compare_digest fix scope |

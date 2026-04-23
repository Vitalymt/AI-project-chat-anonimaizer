# State Stability Regression Checklist

## Covered fixes
- stale `currentProjectId/currentChatId` in localStorage are reconciled after project list load
- Vault tab is guarded when no project is selected
- project selection handles 404/invalid id without cascading UI failures
- state transition trace logs are emitted to browser console (`[state-trace]`)

## Manual UI scenarios
1. Clear projects in backend (or use a fresh browser profile), open app, verify there is no "Project not found" loop.
2. With no selected project, open `Vault` tab and verify:
   - user gets warning toast
   - UI returns to `Чаты`
   - no vault API error popup appears.
3. Save invalid `currentProjectId` in localStorage, reload app, verify stale state is cleared and app remains usable.
4. Try `sendMessage` without project/chat selection:
   - expect business validation message only
   - after selecting project+chat, send succeeds.

## Runtime/API checks (automated)
- `GET /api/health` returns `status=ok`
- invalid project id returns 404
- create project/chat/message flow completes with SSE `done: true`
- `GET /api/vault/status` and `/api/vault/tree?project_id=...` return success

# Agent Operational Notes (ProjectChat)

This file is for AI/coding agents working in this repository.

## SSH Tunnel Safety Checklist

Before suggesting or relying on SSH local-forwarding like:

`ssh -N -L 8002:localhost:8002 -p 2222 openclaw@<vm_ip>`

always verify on the VM:

1. ProjectChat API is actually listening on `localhost:8002`.
2. Health endpoint responds: `GET /api/health`.
3. If Vault integration is used, WebDAV is listening on `localhost:8081`.

### Required preflight commands (run on VM)

```bash
ss -tlnp | awk '$4 ~ /:8002$/ || $4 ~ /:8081$/ || $4 ~ /:2222$/'
curl -sS -m 5 http://localhost:8002/api/health
curl -sS -m 5 http://localhost:8002/api/vault/status
```

If `8002` is not listening, start app first:

```bash
./.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8002
```

If WebDAV is required and missing:

```bash
docker compose --profile vault up -d webdav
```

## Common failure pattern

If user sees repeated:

`channel X: open failed: connect failed: Connection refused`

it means SSH to VM works, but target port on VM side (`localhost:8002`) is not accepting connections.
Do not ask user to retry tunnel until service health is green.

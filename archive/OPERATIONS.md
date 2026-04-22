# Operations Runbook

## 1. Start backend

```bash
cd /home/openclaw/ProjectChat/AI-project-chat-anonimaizer
./.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8002
```

## 2. SSH tunnel from Windows

```powershell
ssh -N -L 8002:localhost:8002 -i "<path_to_private_key>" -p <ssh_port> <vm_user>@<vm_ip>
```

## 3. Smoke gate after each restart

1. Open `http://localhost:8002` (or your forwarded local port).
2. Check `GET /api/health` returns `status=ok`.
3. Open settings and save provider/model.
4. Create one test project.
5. Create one chat and send one message.
6. Verify stream completes with final `done` in network SSE.
7. Upload one txt/pdf document and open preview.
8. Save one artifact from chat output.

## 4. Fast failure diagnostics

- Tunnel says `connect failed: Connection refused`:
  - backend is not listening on VM port `8002`.
- UI loads without style/scripts:
  - verify `/static/style.css` and `/static/app.js` return HTTP 200.
- Chat starts but no answer:
  - check `/api/health`, provider key validity, and server logs.

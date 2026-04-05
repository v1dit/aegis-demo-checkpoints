# Frontend (Sandbox Live + Replay)

## Local Setup (with Cluster Tunnel)

Create `frontend/.env.local`:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Keep your SSH tunnel active so local `8000` maps to cluster backend `8000`.

```bash
bash ops/scripts/cluster_tunnel.expect
```

## Run Frontend

```bash
npm run dev
```

If `3000` is occupied by tunnel forwarding, run:

```bash
npm run dev -- --port 3001
```

Then open:

- `http://localhost:3000` (default), or
- `http://localhost:3001` (when running on alternate port)

## Sandbox Live Contract Notes

- Frontend sends `POST /sandbox/runs` with `{ "episode_spec": ... }`.
- `GET /sandbox/catalog` now includes readiness:
  - `execution_mode`
  - `live_run_enabled`
  - `live_block_reason`
- `Run Live` is disabled when `live_run_enabled=false`.
- Backend validation errors from FastAPI `detail` are shown directly in the UI.

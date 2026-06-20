# NormaCore Station — Full Stack Operations Guide

Complete guide to operating the NormaCore robot control stack: Station, MCP tools, HTTP API, N8N workflows, and Lovable dashboard.

> **Hardware:** Raspberry Pi 5 (192.168.137.104), ElRobot arm (bus serial: 5B61037157), SO-101 arm (bus serial: 5B3E089716), USB camera.

---

## Full Stack Overview

```
Lovable Dashboard (Windows PC, localhost:5173)
  → NormaCore HTTP API (Pi :8080, FastAPI/uvicorn)
    → NormaCore Station (Pi :8888, Rust binary)
      → ElRobot / SO-101 Arm (USB serial, ST3215 protocol)
      → Camera (224x224 JPEG via normvla inference stream)
  → N8N Workflows (Pi :5678, Docker)
    → HTTP API (health checks, demo tasks, training pipeline)
```

---

## Starting the Stack

Start each service in order. Each runs in a separate terminal on the Pi.

### 1. Start NormaCore Station (port 8888)

```bash
cd /home/venay/_Work/Hackathon/norma-core-berlin-hackathon/.tmp/station
RUST_LOG=info ./station --tcp --web --config station.yaml
```

Verify: look for `NormFS server listening on 0.0.0.0:8888` in logs, or open `http://192.168.137.104:8889` for the Station Web UI.

### 2. Start HTTP API (port 8080)

```bash
cd /home/venay/_Work/Hackathon/norma-core-berlin-hackathon/software/station/mcp
DEFAULT_BUS_SERIAL=5B61037157 uv run python -m norma_station_mcp --http --port 8080
```

Verify: `curl http://192.168.137.104:8080/api/connection` should return `"connected": true`.

> **Note:** `DEFAULT_BUS_SERIAL=5B61037157` is required because two buses are connected. Without it, endpoints return a "requires exactly one bus" error.

### 3. Start N8N (port 5678)

```bash
docker run -d \
  --name n8n \
  --restart unless-stopped \
  -p 5678:5678 \
  -v ~/.n8n:/home/node/.n8n \
  -e N8N_HOST=0.0.0.0 \
  -e N8N_SECURE_COOKIE=false \
  --add-host=host.docker.internal:host-gateway \
  n8nio/n8n
```

Verify: open `http://192.168.137.104:5678` from any browser on the network.

> If N8N is already running: `docker start n8n`

### 4. Start Lovable Dashboard (Windows PC)

```bash
cd <lovable-project-directory>
npm install
npx vite dev --port 5173
```

Open `http://localhost:5173`. Configure in the setup modal:
- **Robot API URL:** `http://192.168.137.104:8080`
- **Camera Stream URL:** *(leave blank — falls back to robot onboard camera)*
- **N8N Webhook URL:** `http://192.168.137.104:5678`

> **Important:** Do NOT use port 8080 for the dashboard — it conflicts with the API. Use port 5173.

---

## Stopping the Stack

```bash
# Stop HTTP API
kill $(lsof -ti:8080)

# Stop Station
kill $(lsof -ti:8888)
# Or Ctrl+C in the station terminal

# Stop N8N
docker stop n8n

# Dashboard: Ctrl+C in the Windows terminal
```

---

## HTTP API Reference (port 8080)

API docs with Swagger UI: `http://192.168.137.104:8080/docs`

### GET Endpoints

| Endpoint | Description |
|----------|-------------|
| `/api/connection` | Station connectivity, stream health, uptime |
| `/api/state` | Arm joints, gripper, arm type |
| `/api/state/full` | Arm state + camera image combined |
| `/api/camera` | 224x224 JPEG base64 from workspace camera |
| `/api/health` | Per-motor health, errors, warnings |
| `/api/planning` | Full world snapshot (arm + gripper + health + camera + history) |
| `/api/history?limit=10` | Recent action log |
| `/api/buses` | All detected motor buses |
| `/api/vla/status` | SmolVLA model loaded/available |
| `/api/training/dataset-check?path=...` | Check for parquet files at path |
| `/api/n8n/alerts?limit=20` | Recent alerts from N8N workflows |

### POST Endpoints

| Endpoint | Body | Description |
|----------|------|-------------|
| `/api/move/joint` | `{joint_id, position}` | Move single joint (0.0-1.0) |
| `/api/move/pose` | `{joint_positions: {id: pos}}` | Move multiple joints |
| `/api/move/verified` | `{joint_positions, tolerance_steps?, settle_seconds?}` | Move + verify + retry |
| `/api/gripper` | `{position}` | Set gripper (0.0=open, 1.0=closed) |
| `/api/gripper/open` | `{}` | Fully open gripper |
| `/api/gripper/close` | `{}` | Fully close gripper |
| `/api/torque/enable` | `{}` | Power all motors |
| `/api/torque/disable` | `{}` | Release all motors |
| `/api/emergency-stop` | `{}` | Kill all torque immediately |
| `/api/pick` | `{approach_positions, grasp_positions?, lift_positions?}` | Full pick sequence |
| `/api/place` | `{place_positions, retreat_positions?}` | Full place sequence |
| `/api/vla/load` | `{checkpoint_path}` | Load SmolVLA checkpoint |
| `/api/vla/step` | `{task, n_steps?, max_delta_ticks?}` | Run VLA inference ticks |
| `/api/n8n/alert` | `{alert_type, message, severity?, stage?}` | Receive N8N alert |

### WebSocket

| Endpoint | Description |
|----------|-------------|
| `/ws/state` | Live arm + camera state push (200ms interval) |

### Error Responses

All errors return `{"error": "message"}` with HTTP status codes: 400 (bad input), 404 (not found), 500 (server error), 502 (station unreachable), 504 (timeout).

---

## N8N Workflows (port 5678)

Three workflows in `software/station/mcp/n8n_workflows/`. Import via N8N UI > Workflows > Import from File.

### 1. Health Monitoring (`1_health_monitoring.json`)

- **Trigger:** Cron, every 5 minutes
- **What it does:** Checks `GET /api/health` and `GET /api/connection` in parallel. Sends alert to `POST /api/n8n/alert` if either fails.
- **Alert severities:** `critical` (connection lost), `warning` (motor errors)
- **Activate and forget** — runs automatically in the background.

### 2. Demo Task (`2_demo_task.json`)

- **Trigger:** `POST /webhook/normacore-demo`
- **What it does:** check connection → enable torque → check/load VLA model → run VLA task → capture result state
- **Request body:** `{"task": "pick up the pen", "n_steps": 30, "checkpoint_path": "/home/venay/smolvla_checkpoint"}`
- All fields optional (defaults shown).

```bash
# Test from terminal
curl -X POST http://192.168.137.104:5678/webhook/normacore-demo \
  -H "Content-Type: application/json" \
  -d '{"task": "pick up the pen", "n_steps": 10}'
```

### 3. Training Pipeline (`3_training_pipeline.json`)

Two-phase workflow with separate webhooks:

**Phase A — Dataset Validation:** `POST /webhook/normacore-train`
1. Checks for parquet files at dataset path
2. Sends alert with dataset status and Colab training instructions
3. Request: `{"dataset_path": "/home/venay/datasets/normacore", "steps": 5000, "batch_size": 32}`

**Phase B — Checkpoint Deployment:** `POST /webhook/normacore-training-complete`
1. Loads checkpoint into VLA bridge
2. Runs 5-step smoke test
3. Sends deployment status alert
4. Request: `{"output_dir": "/home/venay/smolvla_checkpoint"}`

```bash
# Test Phase A
curl -X POST http://192.168.137.104:5678/webhook/normacore-train \
  -H "Content-Type: application/json" \
  -d '{"dataset_path": "/home/venay/datasets/normacore", "steps": 5000, "batch_size": 32}'

# Test Phase B (after Colab training is done)
curl -X POST http://192.168.137.104:5678/webhook/normacore-training-complete \
  -H "Content-Type: application/json" \
  -d '{"output_dir": "/home/venay/smolvla_checkpoint"}'
```

### N8N Setup Notes

- URLs in workflows are hardcoded to `192.168.137.104:8080` (not `host.docker.internal`)
- `N8N_SECURE_COOKIE=false` is required for HTTP access (no TLS)
- Test webhooks (`/webhook-test/`) only listen after clicking "Test Workflow" in the editor
- Production webhooks (`/webhook/`) work when the workflow is activated

---

## MCP Tools (28 total)

For AI agent access via Claude Code / Cursor. Uses stdio transport (not HTTP).

### MCP Configuration

**Claude Code** (`~/.claude.json` or `.claude/settings.json`):
```json
{
  "mcpServers": {
    "norma-station": {
      "command": "uv",
      "args": ["run", "--project", "software/station/mcp", "python", "-m", "norma_station_mcp"],
      "env": {
        "STATION_HOST": "localhost:8888",
        "DEFAULT_BUS_SERIAL": "5B61037157"
      }
    }
  }
}
```

**Cursor** — uses `.cursor/mcp.json` (already configured in repo).

### Tool Categories

| Category | Tools | When to use |
|----------|-------|-------------|
| Discovery & State | `station_connection_status`, `get_arm_state`, `get_full_observation` | Starting a session, reading current state |
| Camera / Vision | `capture_image`, `get_full_observation` | Observing the workspace visually |
| Safety | `emergency_stop`, `get_motor_health` | Something goes wrong, diagnosing issues |
| Gripper | `open_gripper`, `close_gripper`, `set_gripper` | Grasping and releasing objects |
| Arm Motion | `move_joint`, `move_arm_pose`, `enable_arm_torque`, `disable_arm_torque` | Moving the robot arm |
| Verification | `verify_arm_position`, `verify_gripper_grasp`, `verify_action` | Confirming actions succeeded |
| Planning Loop | `move_and_verify`, `pick_object`, `place_object`, `get_planning_state` | Autonomous task execution |
| VLA (SmolVLA) | `vla_status`, `vla_load_model`, `vla_step` | Vision-guided manipulation |
| Advanced | `advanced_list_motor_buses`, `advanced_get_motor_state`, `advanced_move_motor_normalized`, `advanced_move_motor_steps`, `advanced_set_motor_torque` | Debugging, raw motor access |

### Quick Start (MCP)

```
1. station_connection_status     → confirm station is reachable
2. get_arm_state                 → see joints, gripper, arm type
3. enable_arm_torque             → power motors (required before moving)
4. get_planning_state            → full world view (arm + gripper + camera + health)
5. move_and_verify {1: 0.5}     → move joint 1 to midpoint, verify arrival
6. close_gripper                 → close the gripper
7. verify_gripper_grasp          → check if something was grasped
```

### VLA Tools (require trained SmolVLA checkpoint)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `vla_status` | — | Check if SmolVLA model is loaded and available |
| `vla_load_model` | `checkpoint_path`, `device?` | Load a trained SmolVLA checkpoint |
| `vla_step` | `task`, `n_steps?`, `bus_serial?`, `max_delta_ticks?` | Run VLA inference — camera + joints → motor commands |

**Task prompt examples for `vla_step`:**
- `"move to the yellow pen"` (30 steps)
- `"grasp the yellow pen"` (15 steps)
- `"lift the yellow pen"` (10 steps)
- `"move to center position"` (20 steps)

> **Blocker:** VLA tools need a trained checkpoint. See SmolVLA Training section below.

---

## Lovable Dashboard

React dashboard running locally on Windows PC.

### Panels

| Panel | Source | Poll Rate |
|-------|--------|-----------|
| Live Camera Feed | `/api/camera` (fallback) or external MJPEG stream | 500ms |
| Robot State | `/api/state` — joint bars, gripper visual, torque badges | 500ms |
| Control Panel | 3 tabs: NL control, joint sliders, system (torque/VLA/N8N) | on-demand |
| Action Log | `/api/history` | 2s |
| Automation Alerts | `/api/n8n/alerts` — N8N workflow alerts | 5s |

### Dashboard Controls

- **Emergency Stop** — always visible in header, sends `POST /api/emergency-stop`
- **Natural Language tab** — text input → `POST /api/vla/step`
- **Joint Control tab** — sliders for each joint → `POST /api/move/joint`
- **System tab** — torque enable/disable, VLA model loading, N8N demo/training triggers
- **Run Demo via N8N** — sends task to N8N demo workflow webhook
- **Start Training Pipeline** — sends config to N8N training workflow webhook

---

## SmolVLA Training (Pending)

Required to enable vision-guided manipulation (`vla_step`).

### Workflow

1. **Record teleop demos** (~30 min) — leader arm drives follower arm
2. **Export to parquet** — `dataset-generator` binary (in `.tmp/station/`)
3. **Upload to Google Colab** — free T4 GPU
4. **Train** — 5000 steps, batch size 32, lr 1e-4, base: `lerobot/smolvla_base` (~1-2 hrs)
5. **Download checkpoint** — `scp` to Pi at `/home/venay/smolvla_checkpoint`
6. **Deploy** — `POST /api/vla/load` or N8N training-complete webhook
7. **Test** — `POST /api/vla/step` with a simple task

### Colab Config

```python
base_model = "lerobot/smolvla_base"
training_steps = 5000
batch_size = 32
learning_rate = 1e-4
```

---

## Common Workflows

### Observe-Plan-Act-Verify Cycle (MCP)

```
1. get_planning_state              → observe the world
2. (AI agent decides what to do)   → plan
3. move_and_verify / pick_object   → act
4. get_planning_state              → verify outcome, plan next step
```

### Pick and Place (MCP)

```
1. enable_arm_torque
2. get_planning_state                      → see workspace
3. pick_object(approach=..., grasp=...)    → pick up target
4. place_object(place=..., retreat=...)    → place at destination
5. get_planning_state                      → confirm result
```

### Recovery After Emergency Stop

```
1. emergency_stop               → arm goes limp
2. (resolve the issue)
3. get_motor_health             → check for errors
4. enable_arm_torque            → re-enable motors
5. get_arm_state                → confirm positions
```

---

## Joint Reference

| Arm Type | Joint Motor IDs | Gripper Motor ID | Total |
|----------|-----------------|------------------|-------|
| SO-101   | 1, 2, 3, 4, 5  | 6                | 6     |
| ElRobot  | 1, 2, 3, 4, 5, 6, 7 | 8           | 8     |

All positions are **normalized 0.0 to 1.0** within each motor's calibrated range (not Cartesian XYZ).

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STATION_HOST` | `localhost:8888` | NormaCore Station TCP address |
| `DEFAULT_BUS_SERIAL` | *(none)* | Required when multiple buses connected (currently: `5B61037157`) |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Nothing listening on 8888` | Start station: `./station --tcp --web --config station.yaml` |
| `Address already in use (8888)` | Kill old process: `kill $(lsof -ti:8888)` then restart |
| `Address already in use (8080)` | Kill old process: `kill $(lsof -ti:8080)` then restart |
| HTTP API: `requires exactly one bus` | Start API with `DEFAULT_BUS_SERIAL=5B61037157` |
| No `/dev/ttyACM*` device | Replug USB, check `dmesg | tail` |
| Motors detected but won't move | Run `enable_arm_torque` first |
| N8N: secure cookie error | Restart with `-e N8N_SECURE_COOKIE=false` |
| N8N: `executeCommand` not recognized | Use HTTP request nodes instead (workflows already fixed) |
| N8N: env vars denied | URLs are hardcoded in workflow JSON, no env vars needed |
| N8N: webhook not registered | Click "Test Workflow" in editor before sending test requests |
| Dashboard: "Disconnected" | Check API is running, verify IP is correct in settings |
| Dashboard: can't reach Pi from Lovable preview | Run dashboard locally (`npm run dev`), not on lovable.dev |
| Dashboard: port 8080 conflict | Use `npx vite dev --port 5173` |
| Camera: no frames | Ensure torque is enabled on at least one motor |
| `ModuleNotFoundError: uvicorn` | Run via `uv run python -m norma_station_mcp --http --port 8080` |
| `externally-managed-environment` | Use `uv run` instead of `pip install` |

---

## Port Reference

| Port | Service | Access |
|------|---------|--------|
| 8888 | NormaCore Station (TCP) | Internal — used by HTTP API |
| 8889 | Station Web UI | `http://192.168.137.104:8889` |
| 8080 | NormaCore HTTP API | `http://192.168.137.104:8080` |
| 5678 | N8N Workflow Engine | `http://192.168.137.104:5678` |
| 5173 | Lovable Dashboard (local) | `http://localhost:5173` (Windows PC) |

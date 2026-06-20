# N8N Workflows for NormaCore Station

Three importable N8N workflows that integrate with the NormaCore HTTP API.

## Prerequisites

1. NormaCore HTTP API running: `python -m norma_station_mcp --http --port 8080`
2. N8N running (see setup below)

## N8N Setup (Docker on Pi 5)

```bash
# Install Docker (if not already installed)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# Log out and back in for group to take effect

# Start N8N
mkdir -p ~/.n8n
docker run -d \
  --name n8n \
  --restart unless-stopped \
  -p 5678:5678 \
  -v ~/.n8n:/home/node/.n8n \
  -e N8N_HOST=0.0.0.0 \
  -e WEBHOOK_URL=http://$(hostname -I | awk '{print $1}'):5678/ \
  -e NORMACORE_API_URL=http://host.docker.internal:8080 \
  -e VLA_CHECKPOINT_PATH=/home/venay/smolvla_checkpoint \
  --add-host=host.docker.internal:host-gateway \
  n8nio/n8n
```

Access N8N at `http://<pi-ip>:5678`

## Environment Variables

Set these in N8N Settings > Variables (or pass as `-e` to Docker):

| Variable | Default | Description |
|----------|---------|-------------|
| `NORMACORE_API_URL` | `http://localhost:8080` | NormaCore HTTP API base URL |
| `VLA_CHECKPOINT_PATH` | `/home/venay/smolvla_checkpoint` | Default SmolVLA checkpoint path |
| `ALERT_WEBHOOK_URL` | `http://localhost:8080/api/n8n/alert` | Where to send alert notifications |

**Note:** Inside Docker, use `http://host.docker.internal:8080` instead of `localhost:8080` to reach the Pi's HTTP API.

## Importing Workflows

1. Open N8N at `http://<pi-ip>:5678`
2. Go to **Workflows** > **Import from File**
3. Import each JSON file in order:
   - `1_health_monitoring.json`
   - `2_demo_task.json`
   - `3_training_pipeline.json`
4. Activate each workflow

## Workflow Details

### 1. Health Monitoring (`1_health_monitoring.json`)

**Trigger:** Every 5 minutes (cron)

Checks both motor health (`GET /api/health`) and station connection (`GET /api/connection`) in parallel. If either returns errors, sends an alert to the alert webhook. Silent when healthy.

Alert severities:
- `critical` — station connection lost
- `warning` — motor health errors detected

### 2. Demo Task (`2_demo_task.json`)

**Trigger:** Webhook POST to `/webhook/normacore-demo`

Runs a VLA-powered demonstration task end-to-end:

1. Checks station connection
2. Enables motor torque
3. Checks if VLA model is loaded; loads it if not
4. Runs the VLA task (default: "pick up the pen", 30 steps)
5. Captures final arm state
6. Returns structured result

**Request body:**
```json
{
  "task": "pick up the yellow pen",
  "n_steps": 30,
  "checkpoint_path": "/home/venay/smolvla_checkpoint"
}
```

All fields are optional (defaults shown in workflow).

**Example:**
```bash
curl -X POST http://<pi-ip>:5678/webhook/normacore-demo \
  -H "Content-Type: application/json" \
  -d '{"task": "pick up the pen"}'
```

### 3. Training Pipeline (`3_training_pipeline.json`)

Two-phase workflow with separate webhooks:

**Phase A — Data Upload** (POST `/webhook/normacore-train`)
1. Validates parquet dataset exists on disk
2. Acknowledges start immediately (202 response)
3. Lists episodes
4. Uploads to Google Drive via `rclone` (falls back to manual if unconfigured)
5. Sends notification with Colab training config

**Phase B — Deployment** (POST `/webhook/normacore-training-complete`)
1. Downloads checkpoint from Google Drive via `rclone`
2. Loads checkpoint into VLA bridge
3. Runs a 5-step smoke test
4. Sends deployment notification with test result

**Request body (Phase A):**
```json
{
  "dataset_path": "/home/venay/datasets/normacore",
  "output_dir": "/home/venay/smolvla_checkpoint",
  "steps": 5000,
  "batch_size": 32
}
```

**rclone setup** (optional, for automatic Google Drive sync):
```bash
sudo apt install rclone
rclone config  # Follow prompts to add "gdrive" remote
```

## Alert Endpoint

All workflows send alerts to `POST /api/n8n/alert` on the HTTP API. View alerts:

```bash
# Recent alerts
curl http://localhost:8080/api/n8n/alerts

# Last 5
curl http://localhost:8080/api/n8n/alerts?limit=5
```

The Lovable dashboard can poll this endpoint to display N8N workflow status.

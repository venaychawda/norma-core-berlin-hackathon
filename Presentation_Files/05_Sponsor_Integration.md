# Sponsor Technology Integration

## Hugging Face

### Role: AI Model Hub + Training Infrastructure

**How we use it:**

| Usage | Details |
|---|---|
| Base Model | `lerobot/smolvla_base` — 450M param VLA model (SmolVLM2 + action expert) |
| Pre-trained Checkpoint | `LBST/t01_pick_and_place` — SO-101 pick-place, fine-tuned from base |
| Public Datasets | `lerobot/svla_so101_pickplace` (50 episodes), `sebobo/pickplace` (50 episodes) |
| Model Download | `huggingface_hub.snapshot_download()` for checkpoint retrieval |
| Transformers | SmolVLM2-500M-Video-Instruct as the frozen vision-language backbone |
| Community | 29+ SmolVLA community fine-tunes for reference (garlic, monster truck, cube) |

**Impact:** Without HuggingFace's SmolVLA base model and the LeRobot community datasets, training a VLA from scratch would require 100x more data and compute. We fine-tune from a model that already understands robotic manipulation — our 50 demonstrations teach it our specific workspace.

**Code integration:**
```python
from huggingface_hub import snapshot_download
from smolvla import SmolVLAPolicy

# Download pre-trained checkpoint
path = snapshot_download('LBST/t01_pick_and_place')

# Load and fine-tune
policy = SmolVLAPolicy.from_pretrained(path, config_overrides={...})
```

---

## Lovable

### Role: Rapid Dashboard UI Generation

**How we use it:**

| Usage | Details |
|---|---|
| Dashboard Generation | Full React + TypeScript control dashboard generated from a prompt |
| GitHub Sync | Auto-synced to GitHub repo, cloned to Windows PC for local use |
| Real-time Monitoring | Joint positions, camera feed, motor health, connection status |
| Robot Control | Move joints, open/close gripper, emergency stop — all from browser |
| N8N Integration | Demo trigger button, training pipeline panel, alerts feed |
| VLA Status | Model loaded/unloaded, inference progress, task prompt input |

**Generated UI Features:**
- Live arm state visualization (8 joint positions with normalized bars)
- Camera image display (updates via WebSocket)
- Action history log
- N8N workflow trigger buttons
- Training dataset check panel
- Emergency stop button

**Impact:** Lovable generated a production-quality React dashboard in minutes that would have taken days to hand-code. The dashboard connects to our HTTP API (port 8080) and provides a non-technical interface to the entire robot system.

**Configuration:**
```
Robot API URL:     http://192.168.137.104:8080
N8N Webhook URL:   http://192.168.137.104:5678
Runs locally:      localhost:5173 (must be on same network as Pi)
```

---

## N8N

### Role: Workflow Automation + Orchestration

**How we use it:**

| Workflow | Trigger | Function |
|---|---|---|
| **Health Monitoring** | Cron (every 5 min) | Polls `/api/health` + `/api/connection`, sends alerts on failure |
| **Demo Task** | Webhook | Runs full VLA pick-and-place demo end-to-end via HTTP API |
| **Training Pipeline** | Webhook | Validates dataset → sends Colab instructions → deploys checkpoint |

**Architecture:**
```
N8N (Docker, port 5678)
  ↓ HTTP Request nodes
HTTP API (port 8080)
  ↓ TCP
Station Daemon (port 8888)
  ↓ USB
ElRobot
```

**Impact:** N8N provides automated monitoring without custom code, visual workflow design for non-developers, and webhook-triggered demo/training pipelines that can be invoked from the Lovable dashboard.

**Deployment:**
```bash
docker run -d --name n8n \
  -p 5678:5678 \
  -e N8N_SECURE_COOKIE=false \
  -e WEBHOOK_URL=http://192.168.137.104:5678/ \
  n8nio/n8n
```

**3 Workflows imported and tested:**
- `1_health_monitoring.json` — proactive alerting
- `2_demo_task.json` — one-click demo execution
- `3_training_pipeline.json` — dataset validation + training orchestration

---

## Integration Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    SPONSOR ECOSYSTEM                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐                                           │
│  │  HUGGING     │  SmolVLA base model                       │
│  │  FACE        │  Pre-trained checkpoints                  │
│  │              │  Community datasets                       │
│  │  (Training)  │  Model hosting                           │
│  └──────┬───────┘                                           │
│         │ fine-tune + deploy                                │
│         ▼                                                    │
│  ┌──────────────┐   triggers    ┌──────────────┐           │
│  │  N8N         │──────────────▶│  HTTP API    │           │
│  │              │               │  (Robot)     │           │
│  │  (Automation)│◀──────────────│              │           │
│  └──────┬───────┘   alerts      └──────────────┘           │
│         │                                                    │
│         │ webhook                                           │
│         ▼                                                    │
│  ┌──────────────┐                                           │
│  │  LOVABLE     │  Dashboard UI                             │
│  │              │  Real-time control                        │
│  │  (Interface) │  Status monitoring                       │
│  └──────────────┘                                           │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

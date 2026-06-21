# Sponsor Technology Integration

## Hugging Face

### Role: AI Model Hub + Training Infrastructure + GPU Compute

**How we use it:**

| Usage | Details |
|---|---|
| Base Model | `lerobot/smolvla_base` — 450M param VLA model (SmolVLM2 + action expert) |
| Pre-trained Checkpoint | `LBST/t01_pick_and_place` — SO-101 pick-place, fine-tuned from base |
| Dataset Hosting | `venaychawda/elrobot-pickplace` — our 12 episodes, 5,099 frames uploaded to HF Hub |
| GPU Training | HF Spaces with Nvidia L4 (24GB VRAM) — fine-tune SmolVLA in ~20 min for ~$0.27 |
| Model Download | `huggingface_hub.snapshot_download()` for checkpoint retrieval |
| Transformers | SmolVLM2-500M-Video-Instruct as the frozen vision-language backbone |
| Community | 29+ SmolVLA community fine-tunes for reference (garlic, monster truck, cube) |

### Training on HuggingFace Spaces

We use HF Spaces as our **GPU training infrastructure** — the Raspberry Pi 5 has no GPU, so training happens in the cloud:

```
┌─────────────────┐     ┌───────────────────┐     ┌─────────────────┐
│  Pi 5 (record)  │────▶│  HF Hub (dataset) │────▶│  HF Space (GPU) │
│  Teleoperation  │     │  12 parquets      │     │  L4 24GB VRAM   │
│  → Export       │     │  128 MB           │     │  Fine-tune 20m  │
└─────────────────┘     └───────────────────┘     └────────┬────────┘
                                                            │
┌─────────────────┐     ┌───────────────────┐              │
│  Pi 5 (deploy)  │◀────│  HF Hub (model)   │◀─────────────┘
│  CPU inference  │     │  Trained ckpt     │
│  → Robot moves  │     │  ~900 MB          │
└─────────────────┘     └───────────────────┘
```

| Step | Platform | Time | Cost |
|---|---|---|---|
| Upload dataset | HF Hub | 2 min | Free |
| Fine-tune (5K steps) | HF Space (L4) | ~20 min | ~$0.27 |
| Download checkpoint | HF Hub → Pi | 3 min | Free |
| **Total** | | **~25 min** | **~$0.27** |

**Why HF over Google Colab:**
- No session timeouts (Colab disconnects after 90 min idle)
- Guaranteed GPU availability (Colab free tier queues)
- Dataset + model + training in one ecosystem
- Auto-push trained checkpoint back to Hub

### Impact

HuggingFace provides the complete ML lifecycle for our project:
1. **Pre-training** — SmolVLA base model (trained by HF on community data)
2. **Transfer learning** — LBST checkpoint (community fine-tune on SO-101)
3. **Dataset hosting** — our ElRobot parquets versioned on Hub
4. **GPU compute** — L4 Spaces for fine-tuning ($0.27 per run)
5. **Model serving** — trained checkpoint hosted for download to Pi

Without HuggingFace, training a VLA from scratch would require 100x more data and thousands of dollars in compute. We fine-tune from a model that already understands robotic manipulation — our demonstrations teach it our specific arm and workspace.

**Code integration:**
```python
from huggingface_hub import snapshot_download
from smolvla import SmolVLAPolicy

# Download pre-trained checkpoint from HF Hub
path = snapshot_download('LBST/t01_pick_and_place')

# Load and fine-tune
policy = SmolVLAPolicy.from_pretrained(path, config_overrides={
    "image_keys": ["observation.images.cam0"],
    "state_dim": 8,   # ElRobot 8-DOF
    "action_dim": 8,
})
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

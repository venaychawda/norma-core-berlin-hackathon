# Results and Demo

## What Works Today

| Feature | Status | Evidence |
|---|---|---|
| Leader-follower teleoperation | Working | Real-time mirroring, deadband filtering, current protection |
| Station Web UI | Working | http://192.168.137.104:8889 — live joint viz + calibration |
| HTTP REST API (24 endpoints) | Working | Swagger at http://192.168.137.104:8080/docs |
| WebSocket real-time state | Working | 5Hz arm state + camera streaming |
| N8N health monitoring | Working | 5-min cron, alerts on failure |
| N8N demo workflow | Working | Webhook-triggered pick-and-place |
| Lovable dashboard | Working | Joint control, camera feed, N8N triggers |
| Data collection pipeline | Working | 12 parquet files, 5,099 frames, 4 tasks |
| Dataset-generator export | Working | Tag-based episode slicing, auto merge |
| SmolVLA zero-shot inference | Working | LBST checkpoint loaded, predictions validated |
| SmolVLA fine-tuning pipeline | Ready | Colab notebook + bundle prepared |

## Demo Flow

### Live Demo 1: Teleoperation
1. Move the leader arm by hand
2. Follower mirrors in real-time (100Hz servo loop)
3. Show deadband filtering and current protection

### Live Demo 2: AI-Controlled Pick & Place
1. Load trained SmolVLA checkpoint
2. Give task prompt: "pick up the block"
3. Model predicts joint goals from camera + state
4. Robot executes the motion autonomously

### Live Demo 3: Full Stack Integration
1. Open Lovable dashboard in browser
2. Click "Run Demo" button
3. N8N webhook fires → API → Station → Robot executes task
4. Dashboard shows real-time progress

## Performance Metrics

| Metric | Value |
|---|---|
| Servo loop frequency | 100 Hz |
| Teleop mirroring latency | <20ms |
| SmolVLA inference (Pi 5 CPU) | ~24s per tick (10 denoise steps) |
| SmolVLA inference (action chunking) | ~2s per 50-step chunk |
| API response time | <100ms (state/health endpoints) |
| Training time (5000 steps, T4) | ~30-60 min |
| Dataset recording to export | ~5 min per task |

## Training Data Collected

| Task | Episodes | Frames |
|---|---|---|
| Push block forward | 4 | 1,396 |
| Pick up the block | 4 | 2,025 |
| Pick up the pen | 2 | 1,072 |
| Pick up the block and put it down | 1 | 401 |
| Pick up the bottle cap | 1 | 205 |
| **Total** | **12** | **5,099** |

## Zero-Shot Inference Results

Pre-trained LBST checkpoint (no fine-tuning on our arm) produced coherent predictions:
- Small conservative deltas (±0.02–0.04 normalized)
- Gripper opening for "pick up" task (correct behavior)
- No wild/unsafe movements
- Confirms the model understands pick-and-place semantics

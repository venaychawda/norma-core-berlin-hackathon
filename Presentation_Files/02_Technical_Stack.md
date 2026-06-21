# Technical Stack

## Hardware

| Component | Specification |
|---|---|
| Robot | NormaCore ElRobot — 7 DOF + gripper (8 motors) |
| Servos | Feetech STS3215 x16 (8 leader + 8 follower) |
| Controller | Raspberry Pi 5 (8GB RAM, ARM64) |
| Cameras | 2x USB RGB cameras (224x224 inference resolution) |
| Cost | ~$440 total (leader + follower arms) |

## Software Stack

| Layer | Technology | Role |
|---|---|---|
| Station Daemon | Rust binary | Real-time servo control, 100Hz loop, USB serial, WebSocket |
| MCP Server | Python (FastMCP) | 25 AI-callable tools for robot control |
| HTTP API | Python (FastAPI + Uvicorn) | 24 REST endpoints + WebSocket for N8N/Dashboard |
| AI Agent | Claude CLI (Anthropic) | Natural language orchestrator, task decomposition |
| VLA Model | SmolVLA (450M params, HuggingFace) | Vision-to-motor neural network |
| Automation | N8N (Docker) | 3 workflows: health monitoring, demo, training |
| Dashboard | React + TypeScript (Lovable) | Real-time control UI |
| Training | Google Colab (T4 GPU) | Fine-tuning SmolVLA on teleoperation demos |

## Languages & Frameworks

- **Rust** — Station daemon (real-time motor control, WebSocket server)
- **Python** — MCP server, HTTP API, SmolVLA inference, data pipeline
- **TypeScript/React** — Dashboard (Lovable-generated) + Station Web Viewer
- **Go** — Protobuf code generation, dataset tools
- **Docker** — N8N container deployment

## Protocols & Communication

```
User → Lovable Dashboard (React)
         ↓ HTTP
       HTTP API (FastAPI, port 8080)
         ↓ TCP
       Station Daemon (Rust, port 8888)
         ↓ USB Serial (ST3215 protocol)
       ElRobot Hardware (8 servos)

User → Claude CLI (AI Agent)
         ↓ MCP (stdio)
       MCP Server (Python)
         ↓ TCP
       Station Daemon
         ↓ USB
       ElRobot

N8N (port 5678) → HTTP API → Station → Robot
```

## Key Libraries

| Library | Version | Purpose |
|---|---|---|
| PyTorch | 2.11 | Neural network inference |
| Transformers | 5.3.0 | SmolVLM2 vision-language model |
| FastAPI | latest | REST API |
| PyArrow | 16+ | Parquet dataset I/O |
| Protobuf (custom gremlin) | — | Binary protocol between Station and clients |
| huggingface_hub | 0.24+ | Model/dataset download |

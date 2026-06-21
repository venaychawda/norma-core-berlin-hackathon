# Design Approach

## Core Philosophy

**"AI controls intent, hardware controls motion"**

The AI agent (Claude) never directly writes servo positions. Instead, it orchestrates high-level actions through a verified tool chain, with safety limits enforced at every layer.

## Design Principles

### 1. Layered Safety

```
AI Agent     → can only call MCP tools (bounded actions)
MCP Server   → validates all inputs (range checks, timeouts)
Station      → current protection, deadband filtering, emergency stop
Hardware     → servo torque limits, EEPROM range constraints
```

No single-point-of-failure can cause unsafe motion.

### 2. Learn from Demonstration

Rather than hand-coding trajectories:
- Human demonstrates the task via teleoperation (leader→follower)
- Neural network learns the vision-to-action mapping
- AI agent handles task decomposition and error recovery

### 3. Modular Integration

Each component is independently testable:
- Station runs standalone (Web UI at port 8889)
- HTTP API is usable without AI (curl, N8N, dashboard)
- SmolVLA can be tested offline (zero-shot prediction without sending commands)
- Dashboard works without N8N; N8N works without dashboard

### 4. Edge-First Deployment

- All control runs on Raspberry Pi 5 (no cloud dependency at runtime)
- Training uses cloud GPU (Colab) but inference is fully local
- Sub-second motor loop (100Hz), acceptable VLA latency (~2s/chunk with action chunking)

## Key Technical Decisions

| Decision | Rationale |
|---|---|
| SmolVLA over OpenVLA/Pi0 | 450M params fits Pi 5 RAM; community SO-101 data; MIT license |
| LBST checkpoint as base | Pre-trained on SO-101 pick-place; same servo family; 6→8 DOF fine-tunable |
| Custom parquet format | Embedded JPEG + normalized joints = self-contained episodes, no video decoding |
| Rust station daemon | Real-time 100Hz loop; memory-safe; handles USB serial + WebSocket + NormFS queues |
| MCP protocol | Standard AI tool-calling interface; works with any LLM that supports MCP |
| N8N for automation | Visual workflow builder; Docker-deployable; webhook + cron triggers |
| Lovable for dashboard | Rapid React UI generation; GitHub sync; customizable |

## Data Pipeline Design

```
Teleoperation → Raw streams (motor + camera + inference)
             → Tagged episodes (start/end markers via Web UI)
             → Parquet export (dataset-generator binary)
             → Fine-tuning (Colab, LBST base, 5000 steps)
             → Checkpoint deployment (scp to Pi)
             → Live inference (run_policy.py)
```

All data stays in the NormaCore ecosystem — no external format conversion needed for the primary path.

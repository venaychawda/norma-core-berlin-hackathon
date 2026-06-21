# System Architecture

## High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER INTERFACES                              │
├──────────────────┬──────────────────────┬───────────────────────────┤
│  Lovable Dashboard│   Claude CLI Agent   │   Station Web UI          │
│  (React, Win PC)  │  (Natural Language)  │  (port 8889)              │
└────────┬─────────┴──────────┬───────────┴────────────┬──────────────┘
         │ HTTP                │ MCP (stdio)            │ WebSocket
         ▼                     ▼                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     RASPBERRY PI 5 (192.168.137.104)                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────────┐      │
│  │  HTTP API    │   │  MCP Server  │   │  N8N (Docker)      │      │
│  │  FastAPI     │   │  FastMCP     │   │  3 Workflows       │      │
│  │  Port 8080   │   │  25 Tools    │   │  Port 5678         │      │
│  └──────┬───────┘   └──────┬───────┘   └─────────┬──────────┘      │
│         │                   │                      │                  │
│         └───────────────────┼──────────────────────┘                  │
│                             ▼                                         │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │           Station Daemon (Rust, port 8888)                │       │
│  │  • NormFS queue system (inference, st3215, usbvideo)      │       │
│  │  • Motor mirroring (leader→follower teleoperation)        │       │
│  │  • Current protection & safety limits                     │       │
│  │  • 100Hz servo polling loop                               │       │
│  └──────────────────────────┬───────────────────────────────┘       │
│                             │ USB Serial                             │
└─────────────────────────────┼───────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      ELROBOT HARDWARE                                 │
├──────────────────┬──────────────────────┬───────────────────────────┤
│  Leader Arm      │   Follower Arm       │   2x USB Cameras          │
│  8x STS3215      │   8x STS3215         │   224x224 @ 10Hz          │
│  (teleoperation) │   (execution)        │   (observation)           │
└──────────────────┴──────────────────────┴───────────────────────────┘
```

## SmolVLA AI Pipeline

```
┌─────────────┐    ┌─────────────────────────────────────────────────┐
│   Camera    │───▶│              SmolVLA (450M params)                │
│  224x224    │    │                                                   │
└─────────────┘    │  ┌─────────┐   ┌────────────┐   ┌───────────┐  │
                   │  │ SigLIP  │──▶│ SmolVLM2   │──▶│  Action   │  │
┌─────────────┐    │  │ Vision  │   │ Language   │   │  Expert   │  │
│ Joint State │───▶│  │ Encoder │   │ Model      │   │  (Flow    │  │
│  8x norm    │    │  │(frozen) │   │ (frozen)   │   │  Matching)│  │
└─────────────┘    │  └─────────┘   └────────────┘   └─────┬─────┘  │
                   │                                         │        │
┌─────────────┐    │  "pick up the block"                    │        │
│Task Prompt  │───▶│  → tokenized                           ▼        │
└─────────────┘    │                              ┌──────────────┐   │
                   │                              │ 50 predicted │   │
                   │                              │ joint goals  │   │
                   │                              └──────┬───────┘   │
                   └─────────────────────────────────────┼───────────┘
                                                         │
                                                         ▼
                                              ┌──────────────────┐
                                              │  Sync-Write to   │
                                              │  Servo Motors    │
                                              └──────────────────┘
```

## Training Pipeline

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌───────────┐
│  Teleop     │────▶│   Station    │────▶│  Dataset     │────▶│  Google   │
│  (Leader→   │     │   Records    │     │  Generator   │     │  Colab    │
│   Follower) │     │   All Data   │     │  (Parquet)   │     │  (T4 GPU) │
└─────────────┘     └──────────────┘     └──────────────┘     └─────┬─────┘
                                                                      │
                    ┌──────────────┐     ┌──────────────┐            │
                    │  Run on Pi 5 │◀────│  Checkpoint  │◀───────────┘
                    │  (CPU infer) │     │  (.safetensors)│
                    └──────────────┘     └──────────────┘
```

## Task Decomposition (Claude Agent)

User: "Fetch me the yellow pen"

```
Step 1: capture_image         → confirm target visible
Step 2: vla_step(approach)    → move arm toward pen (30 ticks)
Step 3: open_gripper          → prepare to grasp
Step 4: vla_step(grasp)       → fine-position fingers (15 ticks)
Step 5: close_gripper         → grip the pen
Step 6: verify_gripper_grasp  → confirm hold
Step 7: vla_step(lift)        → raise the pen (10 ticks)
Step 8: move_arm_pose(home)   → return to base position
```

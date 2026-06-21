---
tags:
- robotics
- elrobot
- normacore
- smolvla
- pick-and-place
license: apache-2.0
---

# ElRobot Pick & Place Dataset

Teleoperation demonstrations recorded on NormaCore ElRobot (8-DOF + gripper).

## Robot
- **NormaCore ElRobot** — 7 rotational joints + 1 gripper (8 ST3215 servos)
- **Controller:** Raspberry Pi 5
- **Cameras:** 2x USB RGB (224x224)

## Dataset Format (NormaCore custom parquet)

One row = one frame. Schema:

| Column | Type | Description |
|---|---|---|
| episode_start_ns | uint64 | Episode identifier |
| timestamp_ns_since_episode_start | uint64 | Per-episode time |
| joints | list<struct> | 8 joints: position_norm, goal_norm, range_min, range_max, current_ma, velocity |
| images | list<struct{jpeg:binary}> | 2 embedded JPEG images per frame |
| task | string | Natural language task instruction |

## Tasks Recorded

| Task | Episodes | Frames |
|---|---|---|
| push the block forward | 4 | 1,396 |
| pick up the block | 4 | 2,025 |
| pick up the pen | 2 | 1,072 |
| pick up the block and put it down | 1 | 401 |
| pick up the bottle cap | 1 | 205 |
| **Total** | **12** | **5,099** |

## Stats
- **Joints:** 8 (normalized 0-1)
- **Images:** 2 per frame (224x224 JPEG)
- **Recording:** Leader-follower teleoperation via NormaCore Station

## Training

```bash
uv run python scripts/train_elrobot.py \
    --parquets data/*.parquet \
    --base-checkpoint LBST/t01_pick_and_place \
    --steps 5000 --batch-size 32
```

## Manual Upload Instructions

1. Create a new dataset repo on HuggingFace: https://huggingface.co/new-dataset
2. Name it `elrobot-pickplace`
3. Upload all `.parquet` files into a `data/` folder
4. Upload this README.md as the repo README

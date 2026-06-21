"""Zero-shot inference test with LBST pre-trained checkpoint on ElRobot.

Maps ElRobot 8 joints → SO-101 6 joints:
  ElRobot motor 1 (base)      → SO-101 joint 0
  ElRobot motor 2 (shoulder)  → SO-101 joint 1
  ElRobot motor 3 (elbow)     → SO-101 joint 2
  ElRobot motor 4 (wrist flex)→ SO-101 joint 3
  ElRobot motor 7 (wrist roll)→ SO-101 joint 4
  ElRobot motor 8 (gripper)   → SO-101 joint 5

Motors 5,6 (extra wrist DOFs) are held at current position.

Run from the smolvla_py directory:
    uv run python scripts/zero_shot_test.py
"""

from __future__ import annotations

import asyncio
import io
import logging
import sys
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[4]
sys.path.insert(0, str(_REPO / "software" / "station" / "shared"))
sys.path.insert(0, str(_REPO))

from station_py import new_station_client
from target.gen_python.protobuf.drivers.inferences import normvla

from smolvla import SmolVLAPolicy
from smolvla.normalize import normalize_state, unnormalize_action
from smolvla.stats import load_stats

QUEUE_ID = "inference/normvla"
CHECKPOINT = _REPO / "checkpoints" / "lbst-pick-place"
STATS_PATH = CHECKPOINT / "stats.safetensors"

ELROBOT_TO_SO101 = [0, 1, 2, 3, 6, 7]

IMAGE_KEY = "observation.images.front"


async def fetch_frame(client, timeout: float = 5.0):
    qr = client.read_from_tail(QUEUE_ID, offset=b"\x00", limit=1, step=1, buf_size=1)
    entry = await asyncio.wait_for(qr.data.get(), timeout=timeout)
    if entry is None:
        raise RuntimeError(f"Queue closed: {qr.err}")
    return normvla.FrameReader(memoryview(bytes(entry.Data)))


def frame_to_batch(frame, stats, device):
    joints = frame.get_joints() or []
    images = frame.get_images() or []

    if len(joints) < 8:
        raise RuntimeError(f"Expected 8 joints, got {len(joints)}")

    state_8 = [j.get_position_norm() for j in joints]
    state_6 = [state_8[i] for i in ELROBOT_TO_SO101]

    state = torch.tensor(state_6, dtype=torch.float32, device=device).unsqueeze(0)

    stats_6 = {
        "state_mean": stats["state_mean"][ELROBOT_TO_SO101],
        "state_std": stats["state_std"][ELROBOT_TO_SO101],
        "action_mean": stats["action_mean"][ELROBOT_TO_SO101],
        "action_std": stats["action_std"][ELROBOT_TO_SO101],
    }
    state_norm = normalize_state(state, stats_6)

    batch = {"observation.state": state_norm}

    if len(images) > 0:
        jpeg = bytes(images[0].get_jpeg())
        with Image.open(io.BytesIO(jpeg)) as im:
            arr = np.asarray(im.convert("RGB"), dtype=np.uint8)
        img_tensor = torch.from_numpy(arr.copy()).permute(2, 0, 1).float().unsqueeze(0).to(device) / 255.0
        batch[IMAGE_KEY] = img_tensor
    else:
        print("WARNING: No camera images in frame, using black image")
        batch[IMAGE_KEY] = torch.zeros(1, 3, 224, 224, device=device)

    ranges_8 = [(int(j.get_range_min()), int(j.get_range_max())) for j in joints]
    ranges_6 = [ranges_8[i] for i in ELROBOT_TO_SO101]

    return batch, stats_6, ranges_6, state_8, ranges_8


async def main():
    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger("zero-shot")
    device = torch.device("cpu")

    print(f"Loading stats from {STATS_PATH}")
    stats = {k: v.to(device) for k, v in load_stats(str(STATS_PATH)).items()}

    print(f"Loading checkpoint from {CHECKPOINT}")
    t0 = time.time()
    policy = SmolVLAPolicy.from_pretrained(
        str(CHECKPOINT),
        config_overrides={
            "load_vlm_weights": False,
            "image_keys": [IMAGE_KEY],
            "state_dim": 6,
            "action_dim": 6,
        },
        strict=False,
    ).to(device)
    policy.eval()
    print(f"Model loaded in {time.time()-t0:.1f}s ({sum(p.numel() for p in policy.parameters()):,} params)")

    print("Connecting to station...")
    client = await new_station_client("localhost", logger)
    print("Connected. Fetching frame...")

    frame = await fetch_frame(client)
    batch, stats_6, ranges_6, state_8, ranges_8 = frame_to_batch(frame, stats, device)

    print(f"\nCurrent ElRobot state (8 joints):")
    for i, s in enumerate(state_8):
        print(f"  motor {i+1}: position_norm={s:.4f}")

    print(f"\nMapped to SO-101 (6 joints):")
    for i, idx in enumerate(ELROBOT_TO_SO101):
        print(f"  SO-101 joint {i}: ElRobot motor {idx+1}, norm={state_8[idx]:.4f}")

    tokens, mask = policy.tokenize_task("pick up the block", device=device)
    batch["observation.language.tokens"] = tokens
    batch["observation.language.attention_mask"] = mask

    print(f"\nRunning inference (task: 'pick up the block')...")
    t0 = time.time()
    with torch.no_grad():
        pred = policy.predict_action_chunk(batch)
    dt = time.time() - t0
    print(f"Inference took {dt:.1f}s")

    pred_goal = unnormalize_action(pred[0], stats_6)
    next_goal = pred_goal[0].clamp(0.0, 1.0).numpy()

    print(f"\nPredicted actions (6 SO-101 joints):")
    print(f"  {'Joint':>8}  {'Current':>8}  {'Predicted':>10}  {'Delta':>8}  {'Raw ticks':>10}")
    joint_names = ["base", "shoulder", "elbow", "wrist_flex", "wrist_roll", "gripper"]
    for i, (gn, (rmin, rmax)) in enumerate(zip(next_goal, ranges_6)):
        cur = state_8[ELROBOT_TO_SO101[i]]
        delta = float(gn) - cur
        raw = int(round(rmin + float(gn) * (rmax - rmin)))
        print(f"  {joint_names[i]:>8}  {cur:>8.4f}  {float(gn):>10.4f}  {delta:>+8.4f}  {raw:>10}")

    print(f"\nZero-shot test complete. NOT sending commands to the robot.")
    print(f"Review the predictions above — if they look reasonable, we can proceed.")


if __name__ == "__main__":
    asyncio.run(main())

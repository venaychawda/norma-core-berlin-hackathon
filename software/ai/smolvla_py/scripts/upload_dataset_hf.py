"""Upload ElRobot parquet dataset to HuggingFace Hub.

Usage:
    uv run python scripts/upload_dataset_hf.py --repo-id YOUR_USERNAME/elrobot-pickplace

Requires: huggingface-cli login (write token)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import HfApi, create_repo


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--repo-id", required=True, help="HF dataset repo (e.g. venaychawda/elrobot-pickplace)")
    p.add_argument("--parquets-dir", type=Path, default=Path("/home/venay/datasets/normacore"),
                   help="Directory containing parquet files")
    p.add_argument("--private", action="store_true", help="Make the dataset private")
    return p.parse_args()


def main():
    args = parse_args()
    api = HfApi()

    parquets = sorted(args.parquets_dir.glob("*.parquet"))
    if not parquets:
        raise SystemExit(f"No parquet files in {args.parquets_dir}")

    print(f"Found {len(parquets)} parquet files:")
    total_bytes = 0
    for p in parquets:
        size = p.stat().st_size
        total_bytes += size
        print(f"  {p.name} ({size/1e6:.1f} MB)")
    print(f"  Total: {total_bytes/1e6:.1f} MB")

    print(f"\nCreating dataset repo: {args.repo_id}")
    create_repo(args.repo_id, repo_type="dataset", private=args.private, exist_ok=True)

    print("Uploading parquet files...")
    api.upload_folder(
        repo_id=args.repo_id,
        folder_path=str(args.parquets_dir),
        path_in_repo="data",
        repo_type="dataset",
        allow_patterns="*.parquet",
    )

    readme = f"""---
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
| images | list<struct{{jpeg:binary}}> | 2 embedded JPEG images per frame |
| task | string | Natural language task instruction |

## Tasks Recorded
- push the block forward (4 episodes)
- pick up the block (4 episodes)
- pick up the pen (2 episodes)
- pick up the block and put it down (1 episode)
- pick up the bottle cap (1 episode)

## Stats
- **Episodes:** 12
- **Frames:** 5,099
- **Joints:** 8 (normalized 0-1)
- **Images:** 2 per frame (224x224 JPEG)

## Training
```bash
uv run python scripts/train_elrobot.py \\
    --parquets data/*.parquet \\
    --base-checkpoint LBST/t01_pick_and_place \\
    --steps 5000 --batch-size 32
```
"""
    readme_path = args.parquets_dir.parent / "dataset_readme.md"
    readme_path.write_text(readme)
    api.upload_file(
        path_or_fileobj=str(readme_path),
        path_in_repo="README.md",
        repo_id=args.repo_id,
        repo_type="dataset",
    )
    readme_path.unlink()

    print(f"\nDataset uploaded: https://huggingface.co/datasets/{args.repo_id}")


if __name__ == "__main__":
    main()

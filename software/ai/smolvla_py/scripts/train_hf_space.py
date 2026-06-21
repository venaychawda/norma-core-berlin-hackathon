"""Training script for HuggingFace Spaces (GPU runtime).

Downloads dataset from HF Hub, trains SmolVLA, pushes checkpoint back to Hub.

Usage on HF Spaces (L4 GPU):
    python train_hf_space.py \
        --dataset-repo venaychawda/elrobot-pickplace \
        --output-repo venaychawda/elrobot-smolvla-pickplace \
        --steps 5000 --batch-size 32
"""

from __future__ import annotations

import argparse
import math
import time
from functools import partial
from pathlib import Path

import torch
from huggingface_hub import HfApi, snapshot_download, create_repo
from torch.utils.data import DataLoader

from smolvla import SmolVLAPolicy
from smolvla.dataset import PickAndPlaceDataset, collate_samples
from smolvla.normalize import normalize_action, normalize_state
from smolvla.stats import compute_stats, save_stats


IMAGE_KEYS = ("observation.images.cam0",)
STATE_DIM = 8
ACTION_DIM = 8


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset-repo", required=True, help="HF dataset repo (e.g. venaychawda/elrobot-pickplace)")
    p.add_argument("--output-repo", required=True, help="HF model repo to push checkpoint (e.g. venaychawda/elrobot-smolvla-pickplace)")
    p.add_argument("--base-checkpoint", type=str, default="LBST/t01_pick_and_place")
    p.add_argument("--steps", type=int, default=5000)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--weight-decay", type=float, default=1e-10)
    p.add_argument("--warmup-steps", type=int, default=500)
    p.add_argument("--decay-steps", type=int, default=10000)
    p.add_argument("--decay-lr", type=float, default=2.5e-6)
    p.add_argument("--grad-clip", type=float, default=10.0)
    p.add_argument("--save-every", type=int, default=500)
    p.add_argument("--log-every", type=int, default=20)
    p.add_argument("--num-workers", type=int, default=2)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--private", action="store_true")
    return p.parse_args()


def make_loader(ds, batch_size: int, shuffle: bool, num_workers: int) -> DataLoader:
    return DataLoader(
        ds,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        collate_fn=partial(collate_samples, image_keys=IMAGE_KEYS),
        pin_memory=True,
        drop_last=shuffle,
        persistent_workers=num_workers > 0,
    )


def move_batch(batch: dict, device: torch.device) -> dict:
    return {
        k: (v.to(device, non_blocking=True) if isinstance(v, torch.Tensor) else v)
        for k, v in batch.items()
    }


def build_train_batch(batch: dict, policy, stats, device) -> dict:
    batch = move_batch(batch, device)
    batch["observation.state"] = normalize_state(batch["observation.state"], stats)
    batch["action"] = normalize_action(batch["action"], stats)
    tokens, mask = policy.tokenize_task(batch.pop("task"), device=device)
    batch["observation.language.tokens"] = tokens
    batch["observation.language.attention_mask"] = mask
    return batch


def lr_lambda(step, nominal_warmup, nominal_decay, total_steps, decay_lr, peak_lr):
    if total_steps < nominal_decay:
        scale = total_steps / nominal_decay
        warmup = max(int(nominal_warmup * scale), 1)
        decay = total_steps
    else:
        warmup = max(nominal_warmup, 1)
        decay = nominal_decay
    if step < warmup:
        return (step + 1) / warmup
    s = min(step - warmup, decay - warmup)
    cos = 0.5 * (1 + math.cos(math.pi * s / max(decay - warmup, 1)))
    alpha = decay_lr / peak_lr
    return (1 - alpha) * cos + alpha


def main() -> None:
    args = parse_args()
    torch.manual_seed(args.seed)

    if not torch.cuda.is_available():
        raise SystemExit("CUDA required. Use a GPU-enabled HF Space (L4/A10G/T4).")
    device = torch.device("cuda")
    print(f"GPU: {torch.cuda.get_device_name()}")

    # Download dataset from HF Hub
    print(f"\nDownloading dataset from {args.dataset_repo}...")
    dataset_path = Path(snapshot_download(args.dataset_repo, repo_type="dataset"))
    data_dir = dataset_path / "data"
    parquets = sorted(data_dir.glob("*.parquet"))
    if not parquets:
        raise SystemExit(f"No parquet files in {data_dir}")
    print(f"Found {len(parquets)} parquet files")

    # Load dataset
    train_ds = PickAndPlaceDataset(parquets, image_keys=IMAGE_KEYS)
    print(f"Episodes: {train_ds.total_episodes}  Frames: {len(train_ds)}")

    # Compute stats
    output_dir = Path("checkpoints/elrobot-run")
    output_dir.mkdir(parents=True, exist_ok=True)
    stats = compute_stats(train_ds._state, train_ds._action)
    stats_path = output_dir / "stats.safetensors"
    save_stats(stats, stats_path)
    print(f"\nStats saved -> {stats_path}")
    for k, v in stats.items():
        print(f"  {k:12s}  {v.tolist()}")
    stats = {k: v.to(device) for k, v in stats.items()}

    # Load base model
    print(f"\nLoading base checkpoint {args.base_checkpoint}...")
    policy = SmolVLAPolicy.from_pretrained(
        args.base_checkpoint,
        config_overrides={
            "image_keys": list(IMAGE_KEYS),
            "state_dim": STATE_DIM,
            "action_dim": ACTION_DIM,
            "load_vlm_weights": False,
            "empty_cameras": 0,
        },
        strict=False,
    ).to(device)
    policy.train()

    trainable = [p for p in policy.parameters() if p.requires_grad]
    n_train = sum(p.numel() for p in trainable)
    n_total = sum(p.numel() for p in policy.parameters())
    print(f"Trainable params: {n_train:,} / {n_total:,} ({100*n_train/n_total:.1f}%)")

    opt = torch.optim.AdamW(trainable, lr=args.lr, betas=(0.9, 0.95), weight_decay=args.weight_decay)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lr_lambda=partial(
            lr_lambda,
            nominal_warmup=args.warmup_steps,
            nominal_decay=args.decay_steps,
            total_steps=args.steps,
            decay_lr=args.decay_lr,
            peak_lr=args.lr,
        )
    )

    train_loader = make_loader(train_ds, args.batch_size, shuffle=True, num_workers=args.num_workers)
    print(f"Batches/epoch: {len(train_loader)}")
    print(f"\n{'='*60}")
    print(f"Starting training: {args.steps} steps, batch_size={args.batch_size}")
    print(f"{'='*60}\n")

    step = 0
    t0 = time.time()
    running_loss = 0.0
    running_n = 0

    while step < args.steps:
        for raw_batch in train_loader:
            if step >= args.steps:
                break
            batch = build_train_batch(raw_batch, policy, stats, device)
            loss, info = policy.forward(batch)

            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable, args.grad_clip)
            opt.step()
            sched.step()

            running_loss += info["loss"]
            running_n += 1

            if (step + 1) % args.log_every == 0:
                dt = time.time() - t0
                avg = running_loss / running_n
                lr = sched.get_last_lr()[0]
                print(f"step {step+1:>6}/{args.steps}  loss {avg:.4f}  lr {lr:.2e}  "
                      f"({(step+1) / max(dt, 1e-9):.2f} step/s)")
                running_loss, running_n = 0.0, 0

            if (step + 1) % args.save_every == 0:
                out = output_dir / f"step-{step+1:06d}"
                policy.save_pretrained(out)
                (out / "stats.safetensors").write_bytes(stats_path.read_bytes())
                print(f"  [save] {out}")

            step += 1

    # Save final checkpoint
    final = output_dir / "final"
    policy.save_pretrained(final)
    (final / "stats.safetensors").write_bytes(stats_path.read_bytes())
    print(f"\nTraining complete. Final checkpoint: {final}")

    # Push to HF Hub
    print(f"\nPushing checkpoint to {args.output_repo}...")
    create_repo(args.output_repo, exist_ok=True, private=args.private)
    api = HfApi()
    api.upload_folder(
        repo_id=args.output_repo,
        folder_path=str(final),
        path_in_repo=".",
    )
    print(f"Checkpoint pushed: https://huggingface.co/{args.output_repo}")
    print(f"\nTotal training time: {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()

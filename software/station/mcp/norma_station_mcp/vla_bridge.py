"""SmolVLA model bridge — loads a checkpoint and runs vision-guided inference ticks."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("norma-station-mcp.vla")

_SMOLVLA_AVAILABLE = False
try:
    import numpy as np
    import torch
    from PIL import Image

    from smolvla import SmolVLAPolicy
    from smolvla.normalize import normalize_state, unnormalize_action
    from smolvla.stats import load_stats

    _SMOLVLA_AVAILABLE = True
except ImportError:
    pass

from .paths import setup_import_paths

setup_import_paths()

from target.gen_python.protobuf.drivers.inferences import normvla  # noqa: E402
from target.gen_python.protobuf.drivers.st3215 import st3215  # noqa: E402
from target.gen_python.protobuf.station import commands, drivers  # noqa: E402

ST3215_TARGET_POS_REGISTER = 0x2A

TASK_PROMPT_GUIDE = {
    "atomic_prompts": {
        "approach": [
            "move to the {object}",
            "reach toward the {object}",
            "move above the {object}",
        ],
        "grasp": [
            "grasp the {object}",
            "close on the {object}",
        ],
        "lift": [
            "lift the {object}",
            "raise the {object}",
        ],
        "place": [
            "place the {object} on the {target}",
            "put the {object} next to the {target}",
        ],
        "return": [
            "return to home",
            "move to rest position",
        ],
    },
    "decomposition_example": {
        "user_request": "Fetch me the yellow pen",
        "steps": [
            {"tool": "capture_image", "purpose": "confirm yellow pen is visible"},
            {"tool": "vla_step", "args": {"task": "move to the yellow pen", "n_steps": 30}, "purpose": "approach"},
            {"tool": "open_gripper", "purpose": "prepare to grasp"},
            {"tool": "vla_step", "args": {"task": "grasp the yellow pen", "n_steps": 15}, "purpose": "fine-position"},
            {"tool": "close_gripper", "purpose": "grip the pen"},
            {"tool": "verify_gripper_grasp", "purpose": "confirm hold"},
            {"tool": "vla_step", "args": {"task": "lift the yellow pen", "n_steps": 10}, "purpose": "lift"},
            {"tool": "move_arm_pose", "args": "base_positions", "purpose": "return home"},
        ],
    },
}


class VLABridge:
    """Manages SmolVLA model lifecycle and runs inference against the station."""

    def __init__(self):
        self.policy = None
        self.stats: dict | None = None
        self.device = None
        self.checkpoint_path: Path | None = None
        self.image_keys: tuple[str, ...] = ()
        self._load_time_s: float | None = None

    @property
    def loaded(self) -> bool:
        return self.policy is not None

    def status(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "smolvla_available": _SMOLVLA_AVAILABLE,
            "model_loaded": self.loaded,
            "checkpoint_path": str(self.checkpoint_path) if self.checkpoint_path else None,
            "device": str(self.device) if self.device else None,
            "image_keys": list(self.image_keys),
            "load_time_seconds": self._load_time_s,
        }
        if self.loaded:
            info["action_dim"] = self.policy.config.action_dim
            info["chunk_size"] = self.policy.config.chunk_size
            info["num_denoise_steps"] = self.policy.config.num_steps
        info["task_prompt_guide"] = TASK_PROMPT_GUIDE
        return info

    def load(self, checkpoint_path: str | Path, device: str | None = None) -> dict[str, Any]:
        if not _SMOLVLA_AVAILABLE:
            raise RuntimeError(
                "SmolVLA dependencies not installed. "
                "Install: torch, transformers, safetensors, pillow, huggingface_hub"
            )

        path = Path(checkpoint_path)
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {path}")
        for required in ("stats.safetensors", "config.json", "model.safetensors"):
            if not (path / required).exists():
                raise FileNotFoundError(f"Missing {required} in {path}")

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        t0 = time.monotonic()
        logger.info("Loading SmolVLA from %s on %s ...", path, self.device)

        self.stats = {
            k: v.to(self.device)
            for k, v in load_stats(path / "stats.safetensors").items()
        }

        self.policy = SmolVLAPolicy.from_pretrained(
            path,
            config_overrides={"load_vlm_weights": False},
            strict=False,
        ).to(self.device)
        self.policy.eval()

        self.checkpoint_path = path
        self.image_keys = tuple(self.policy.config.image_keys) or (
            "observation.images.cam0",
            "observation.images.cam1",
        )
        self._load_time_s = round(time.monotonic() - t0, 2)

        logger.info(
            "SmolVLA loaded in %.1fs — action_dim=%d, chunk=%d, images=%s",
            self._load_time_s,
            self.policy.config.action_dim,
            self.policy.config.chunk_size,
            self.image_keys,
        )
        return self.status()

    # ── Inference ───────────────────────────────────────────────────────────

    def _frame_to_batch(
        self, frame: normvla.FrameReader,
    ) -> tuple[dict, list[tuple[int, int]]]:
        joints = frame.get_joints() or []
        images = frame.get_images() or []
        if len(images) < len(self.image_keys):
            raise RuntimeError(
                f"Frame has {len(images)} images, model expects {len(self.image_keys)}"
            )

        state = torch.tensor(
            [j.get_position_norm() for j in joints],
            dtype=torch.float32, device=self.device,
        ).unsqueeze(0)

        batch = {"observation.state": normalize_state(state, self.stats)}
        for i, key in enumerate(self.image_keys):
            jpeg = bytes(images[i].get_jpeg())
            with Image.open(io.BytesIO(jpeg)) as im:
                arr = np.asarray(im.convert("RGB"), dtype=np.uint8)
            batch[key] = (
                torch.from_numpy(arr.copy())
                .permute(2, 0, 1).float().unsqueeze(0).to(self.device) / 255.0
            )

        ranges = [(int(j.get_range_min()), int(j.get_range_max())) for j in joints]
        return batch, ranges

    @torch.no_grad()
    def predict_one(
        self, frame_data: bytes, task: str,
    ) -> tuple[list[int], list[float], list[tuple[int, int]], dict[str, float]]:
        """Run one inference step. Returns (raw_goals, pred_norms, ranges, timing)."""
        if not self.loaded:
            raise RuntimeError("Model not loaded — call vla_load_model first")

        t0 = time.perf_counter()
        frame = normvla.FrameReader(memoryview(frame_data))
        batch, ranges = self._frame_to_batch(frame)

        tokens, mask = self.policy.tokenize_task(task, device=self.device)
        batch["observation.language.tokens"] = tokens
        batch["observation.language.attention_mask"] = mask

        t1 = time.perf_counter()
        pred_norm = self.policy.predict_action_chunk(batch)[0]
        pred_goal = unnormalize_action(pred_norm, self.stats)
        next_goal = pred_goal[0].cpu().clamp(0.0, 1.0).numpy()
        t2 = time.perf_counter()

        raws: list[int] = []
        for g_norm, (rmin, rmax) in zip(next_goal, ranges):
            raw = int(round(rmin + float(g_norm) * (rmax - rmin)))
            raws.append(max(rmin, min(rmax, raw)))

        timing = {
            "prep_ms": round((t1 - t0) * 1000, 1),
            "inference_ms": round((t2 - t1) * 1000, 1),
            "total_ms": round((t2 - t0) * 1000, 1),
        }
        return raws, [float(g) for g in next_goal], ranges, timing

    def _compute_deltas(self, frame_data: bytes, raw_goals: list[int]) -> tuple[list[int], int]:
        frame = normvla.FrameReader(memoryview(frame_data))
        joints = frame.get_joints() or []
        deltas = [abs(raw - int(j.get_position())) for raw, j in zip(raw_goals, joints)]
        return deltas, max(deltas) if deltas else 0

    @staticmethod
    def _build_sync_write(
        bus_serial: str, motor_ids: list[int], raw_goals: list[int],
    ) -> commands.DriverCommand:
        motors = [
            st3215.ST3215SyncWriteCommand_MotorWrite(
                motor_id=mid,
                value=raw.to_bytes(2, byteorder="little"),
            )
            for mid, raw in zip(motor_ids, raw_goals)
        ]
        return commands.DriverCommand(
            type=drivers.StationCommandType.STC_ST3215_COMMAND,
            body=st3215.Command(
                target_bus_serial=bus_serial,
                sync_write=st3215.ST3215SyncWriteCommand(
                    address=ST3215_TARGET_POS_REGISTER,
                    motors=motors,
                ),
            ).encode(),
        )

    # ── Multi-tick loop ─────────────────────────────────────────────────────

    async def run_steps(
        self,
        session,
        task: str,
        n_steps: int,
        bus_serial: str = "auto",
        max_delta_ticks: int = 200,
    ) -> dict[str, Any]:
        """Run N SmolVLA inference ticks, sending motor commands each tick."""
        if not self.loaded:
            raise RuntimeError("Model not loaded — call vla_load_model first")

        await session.ensure_connected()
        await session.wait_for_normvla(timeout_s=10.0)
        await session.wait_for_inference()

        from .motor_state import resolve_bus_serial, find_bus
        from .arm_model import detect_arm_profile

        resolved_serial = resolve_bus_serial(session.latest_inference, bus_serial)
        bus = find_bus(session.latest_inference, resolved_serial)
        if bus is None:
            raise RuntimeError(f"Bus '{resolved_serial}' not found")

        all_motor_ids = sorted(m.get_id() for m in (bus.get_motors() or []))
        action_dim = self.policy.config.action_dim
        motor_ids = all_motor_ids[:action_dim]

        tick_results: list[dict[str, Any]] = []
        last_frame_count = 0
        aborted_count = 0
        sent_count = 0
        total_t0 = time.monotonic()

        for tick in range(n_steps):
            frame_data = await self._wait_for_fresh_frame(
                session, last_frame_count, timeout_s=5.0,
            )
            last_frame_count = session.normvla_frame_count

            raw_goals, pred_norms, ranges, timing = self.predict_one(frame_data, task)
            raw_goals = raw_goals[:len(motor_ids)]

            deltas, max_delta = self._compute_deltas(frame_data, raw_goals)

            tick_info: dict[str, Any] = {
                "tick": tick + 1,
                "max_delta": max_delta,
                "timing": timing,
            }

            if max_delta_ticks > 0 and max_delta > max_delta_ticks:
                tick_info["action"] = "aborted"
                tick_info["reason"] = f"max|delta|={max_delta} > {max_delta_ticks}"
                aborted_count += 1
            else:
                cmd = self._build_sync_write(resolved_serial, motor_ids, raw_goals)
                await session._send_commands([cmd], label=f"vla_tick_{tick + 1}")
                tick_info["action"] = "sent"
                sent_count += 1

            tick_results.append(tick_info)

        total_elapsed = round(time.monotonic() - total_t0, 2)

        result: dict[str, Any] = {
            "task": task,
            "n_steps": n_steps,
            "ticks_sent": sent_count,
            "ticks_aborted": aborted_count,
            "total_seconds": total_elapsed,
            "bus_serial": resolved_serial,
            "motor_ids": motor_ids,
            "max_delta_ticks": max_delta_ticks,
            "ticks": tick_results,
        }

        try:
            result["final_arm_state"] = session.get_arm_state(resolved_serial)
        except Exception as exc:
            result["arm_state_error"] = str(exc)

        try:
            result["final_camera"] = session.get_camera_image()
        except Exception as exc:
            result["camera_error"] = str(exc)

        session._record_action(
            "vla_step",
            {"task": task, "n_steps": n_steps},
            {"sent": sent_count, "aborted": aborted_count},
            sent_count > 0,
        )

        return result

    async def _wait_for_fresh_frame(
        self, session, last_frame_count: int, timeout_s: float = 5.0,
    ) -> bytes:
        deadline = time.monotonic() + timeout_s
        while session.normvla_frame_count <= last_frame_count:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"No fresh normvla frame in {timeout_s}s — camera may be disconnected"
                )
            await asyncio.sleep(0.02)
        return session.latest_normvla_data


_bridge: VLABridge | None = None


def get_vla_bridge() -> VLABridge:
    global _bridge
    if _bridge is None:
        _bridge = VLABridge()
    return _bridge

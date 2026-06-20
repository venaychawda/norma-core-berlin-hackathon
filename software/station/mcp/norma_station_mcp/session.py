from __future__ import annotations

import asyncio
import base64
import collections
import logging
import os
import time
from typing import Any

from .arm_model import ArmProfile, annotate_motor, detect_arm_profile, motor_role
from .motor_state import (
    decode_error_flags,
    find_bus,
    normalized_to_steps,
    parse_motor_snapshot,
    resolve_bus_serial,
)
from .paths import setup_import_paths

setup_import_paths()

try:
    from station_py import new_station_client, send_commands
    from target.gen_python.protobuf.drivers.st3215 import st3215
    from target.gen_python.protobuf.drivers.inferences import normvla
    from target.gen_python.protobuf.station import commands, drivers
except ImportError as exc:
    raise ImportError(
        "Missing generated protobufs or station_py. "
        "From the repo root run: make protobuf"
    ) from exc


def _station_host() -> str:
    return os.environ.get("STATION_HOST", "localhost:8888")


class StationSession:
    """Persistent TCP client with a cached st3215/inference frame."""

    COMMAND_TIMEOUT_S = 5.0
    MIN_COMMAND_INTERVAL_S = 0.05
    FRAME_STALE_THRESHOLD_S = 5.0

    def __init__(self, host: str | None = None):
        self.host = host or _station_host()
        self.logger = logging.getLogger("norma-station-mcp")
        self.client = None
        self.latest_inference: st3215.InferenceStateReader | None = None
        self.latest_stamp_s: float | None = None
        self.frame_count = 0
        self._init_lock = asyncio.Lock()
        self._follow_task: asyncio.Task | None = None
        self._queue: asyncio.Queue | None = None
        self._last_error: str | None = None
        # normvla vision state
        self.latest_normvla_data: bytes | None = None
        self.latest_normvla_stamp_s: float | None = None
        self.normvla_frame_count = 0
        self._normvla_follow_task: asyncio.Task | None = None
        self._normvla_queue: asyncio.Queue | None = None
        self._normvla_last_error: str | None = None
        # action history for agent planning context
        self._action_history: collections.deque[dict[str, Any]] = collections.deque(maxlen=20)
        # rate limiting
        self._last_command_time: float = 0.0
        # connection tracking
        self._connect_count: int = 0
        self._connected_at: float | None = None

    def _connection_is_alive(self) -> bool:
        if self.client is None:
            return False
        if not getattr(self.client, "connected", False):
            return False
        inference_dead = (
            self._follow_task is not None and self._follow_task.done()
        )
        normvla_dead = (
            self._normvla_follow_task is not None
            and self._normvla_follow_task.done()
        )
        if inference_dead and normvla_dead:
            return False
        return True

    def _reset_connection(self) -> None:
        self.logger.info("Resetting connection state")
        if self._follow_task and not self._follow_task.done():
            self._follow_task.cancel()
        if self._normvla_follow_task and not self._normvla_follow_task.done():
            self._normvla_follow_task.cancel()
        self.client = None
        self.latest_inference = None
        self.latest_stamp_s = None
        self.latest_normvla_data = None
        self.latest_normvla_stamp_s = None
        self._follow_task = None
        self._normvla_follow_task = None
        self._queue = None
        self._normvla_queue = None
        self._last_error = None
        self._normvla_last_error = None

    async def ensure_connected(self) -> None:
        async with self._init_lock:
            if self._connection_is_alive():
                return

            if self.client is not None:
                self.logger.warning(
                    "Connection to %s lost (connect #%d), reconnecting",
                    self.host,
                    self._connect_count,
                )
                self._reset_connection()

            self.logger.info("Connecting to station at %s", self.host)
            self.client = await new_station_client(self.host, self.logger)
            self._queue = asyncio.Queue()
            self._follow_task = asyncio.create_task(self._follow_inference())
            self._normvla_queue = asyncio.Queue()
            self._normvla_follow_task = asyncio.create_task(self._follow_normvla())
            self._connect_count += 1
            self._connected_at = time.monotonic()
            self.logger.info(
                "Connected to station (connect #%d)", self._connect_count
            )

    async def _follow_inference(self) -> None:
        assert self.client is not None
        assert self._queue is not None

        error_queue = self.client.follow("st3215/inference", self._queue)

        while True:
            if not error_queue.empty():
                err = error_queue.get_nowait()
                self._last_error = str(err)
                self.logger.error("Inference stream error: %s", err)
                return

            entry = await self._queue.get()
            if entry is None:
                self._last_error = "Inference stream closed"
                return

            try:
                self.latest_inference = st3215.InferenceStateReader(entry.Data)
                self.latest_stamp_s = time.monotonic()
                self.frame_count += 1
            except Exception as exc:
                self.logger.exception("Failed to decode inference frame: %s", exc)

    async def _follow_normvla(self) -> None:
        assert self.client is not None
        assert self._normvla_queue is not None

        error_queue = self.client.follow("inference/normvla", self._normvla_queue)

        while True:
            if not error_queue.empty():
                err = error_queue.get_nowait()
                self._normvla_last_error = str(err)
                self.logger.error("Normvla stream error: %s", err)
                return

            entry = await self._normvla_queue.get()
            if entry is None:
                self._normvla_last_error = "Normvla stream closed"
                return

            try:
                self.latest_normvla_data = bytes(entry.Data)
                self.latest_normvla_stamp_s = time.monotonic()
                self.normvla_frame_count += 1
            except Exception as exc:
                self.logger.exception("Failed to store normvla frame: %s", exc)

    async def wait_for_inference(self, timeout_s: float = 10.0) -> None:
        await self.ensure_connected()
        deadline = time.monotonic() + timeout_s
        while self.latest_inference is None:
            if self._last_error:
                raise RuntimeError(self._last_error)
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"No st3215/inference frames received within {timeout_s}s. "
                    "Is station running with --tcp and the ST3215 driver enabled?"
                )
            await asyncio.sleep(0.05)

    def connection_info(self) -> dict[str, Any]:
        now = time.monotonic()
        inference_age = (
            round(now - self.latest_stamp_s, 3) if self.latest_stamp_s else None
        )
        normvla_age = (
            round(now - self.latest_normvla_stamp_s, 3)
            if self.latest_normvla_stamp_s
            else None
        )
        uptime = (
            round(now - self._connected_at, 1) if self._connected_at else None
        )
        return {
            "host": self.host,
            "connected": self._connection_is_alive(),
            "setup_done": self.client.setup_done if self.client else False,
            "connect_count": self._connect_count,
            "uptime_seconds": uptime,
            "frame_count": self.frame_count,
            "normvla_frame_count": self.normvla_frame_count,
            "has_latest_inference": self.latest_inference is not None,
            "inference_age_seconds": inference_age,
            "inference_stale": (
                inference_age is not None
                and inference_age > self.FRAME_STALE_THRESHOLD_S
            ),
            "normvla_age_seconds": normvla_age,
            "inference_stream_alive": (
                self._follow_task is not None and not self._follow_task.done()
            ),
            "normvla_stream_alive": (
                self._normvla_follow_task is not None
                and not self._normvla_follow_task.done()
            ),
            "last_error": self._last_error,
            "last_normvla_error": self._normvla_last_error,
        }

    async def wait_for_normvla(self, timeout_s: float = 10.0) -> None:
        await self.ensure_connected()
        deadline = time.monotonic() + timeout_s
        while self.latest_normvla_data is None:
            if self._normvla_last_error:
                raise RuntimeError(self._normvla_last_error)
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"No inference/normvla frames received within {timeout_s}s. "
                    "Camera may not be connected or torque is not enabled on any motor."
                )
            await asyncio.sleep(0.05)

    async def _send_commands(self, cmd_list: list, label: str = "command") -> None:
        """Send commands with timeout and rate limiting."""
        now = time.monotonic()
        elapsed = now - self._last_command_time
        if elapsed < self.MIN_COMMAND_INTERVAL_S:
            await asyncio.sleep(self.MIN_COMMAND_INTERVAL_S - elapsed)

        try:
            await asyncio.wait_for(
                send_commands(self.client, cmd_list),
                timeout=self.COMMAND_TIMEOUT_S,
            )
            self._last_command_time = time.monotonic()
            self.logger.debug("Sent %s (%d cmds)", label, len(cmd_list))
        except asyncio.TimeoutError:
            self.logger.error(
                "Command timed out after %.1fs: %s", self.COMMAND_TIMEOUT_S, label
            )
            raise TimeoutError(
                f"Station did not acknowledge {label} within "
                f"{self.COMMAND_TIMEOUT_S}s. Station may be unresponsive."
            )
        except Exception:
            self.logger.exception("Command failed: %s", label)
            raise

    def _check_frame_freshness(self) -> None:
        """Log a warning if inference frames are stale."""
        if self.latest_stamp_s is None:
            return
        age = time.monotonic() - self.latest_stamp_s
        if age > self.FRAME_STALE_THRESHOLD_S:
            self.logger.warning(
                "Inference frame is %.1fs old (threshold %.1fs) — "
                "station may be lagging or disconnected",
                age,
                self.FRAME_STALE_THRESHOLD_S,
            )

    def get_camera_image(self) -> dict[str, Any]:
        if self.latest_normvla_data is None:
            raise RuntimeError(
                "No normvla frames available. Camera may not be connected "
                "or torque is not enabled on any motor."
            )

        frame = normvla.FrameReader(memoryview(self.latest_normvla_data))
        images = frame.get_images()
        if not images:
            raise RuntimeError("Latest normvla frame contains no camera images")

        image = images[0]
        jpeg_bytes = bytes(image.get_jpeg())
        if not jpeg_bytes:
            raise RuntimeError("Camera image JPEG data is empty")

        age_s = round(time.monotonic() - self.latest_normvla_stamp_s, 3) if self.latest_normvla_stamp_s else None

        return {
            "image_base64": base64.b64encode(jpeg_bytes).decode("ascii"),
            "format": "jpeg",
            "width": 224,
            "height": 224,
            "image_count": len(images),
            "frame_age_seconds": age_s,
            "normvla_frame_count": self.normvla_frame_count,
        }

    def get_full_observation(self, bus_serial: str = "auto") -> dict[str, Any]:
        """Combined arm state + camera image in a single call."""
        result: dict[str, Any] = {}

        try:
            result["arm"] = self.get_arm_state(bus_serial)
        except Exception as exc:
            result["arm_error"] = str(exc)

        try:
            result["camera"] = self.get_camera_image()
        except Exception as exc:
            result["camera_error"] = str(exc)

        return result

    def get_motor_health(self, bus_serial: str = "auto") -> dict[str, Any]:
        """Per-motor health: current draw, error flags, torque, position tracking."""
        resolved_serial, bus, profile = self._resolve_bus(bus_serial)
        motors_health = []
        warnings = []

        for motor in bus.get_motors() or []:
            snapshot = parse_motor_snapshot(motor)
            errors = decode_error_flags(snapshot.error_status)

            position_error = abs(snapshot.present_position - snapshot.target_position)

            health: dict[str, Any] = {
                "motor_id": snapshot.motor_id,
                "role": motor_role(profile, snapshot.motor_id),
                "torque_enabled": snapshot.torque_enabled,
                "present_current_ma": snapshot.present_current,
                "error_status": snapshot.error_status,
                "error_flags": errors,
                "present_position": snapshot.present_position,
                "target_position": snapshot.target_position,
                "position_error_steps": position_error,
            }
            motors_health.append(health)

            if errors:
                warnings.append(
                    f"Motor {snapshot.motor_id} ({motor_role(profile, snapshot.motor_id)}): "
                    f"errors={errors}"
                )
            if snapshot.present_current > 500:
                warnings.append(
                    f"Motor {snapshot.motor_id} ({motor_role(profile, snapshot.motor_id)}): "
                    f"high current {snapshot.present_current}mA"
                )

        return {
            "bus_serial": resolved_serial,
            "arm_type": profile.name,
            "motor_count": len(motors_health),
            "motors": motors_health,
            "warnings": warnings,
            "healthy": len(warnings) == 0,
        }

    async def emergency_stop(self, bus_serial: str = "auto") -> dict[str, Any]:
        """Immediately disable torque on all motors. Uses cached state to avoid delays."""
        await self.ensure_connected()

        if self.latest_inference is None:
            raise RuntimeError(
                "No inference data — cannot determine which motors to stop. "
                "Use station_connection_status to diagnose."
            )

        resolved_serial = resolve_bus_serial(self.latest_inference, bus_serial)
        bus = find_bus(self.latest_inference, resolved_serial)
        if bus is None:
            raise RuntimeError(f"Bus '{resolved_serial}' not found")

        motor_ids = [m.get_id() for m in (bus.get_motors() or [])]
        if not motor_ids:
            raise RuntimeError("No motors found on bus")

        value = b"\x00"
        cmd = commands.DriverCommand(
            type=drivers.StationCommandType.STC_ST3215_COMMAND,
            body=st3215.Command(
                target_bus_serial=resolved_serial,
                sync_write=st3215.ST3215SyncWriteCommand(
                    address=0x28,
                    motors=[
                        st3215.ST3215SyncWriteCommand_MotorWrite(
                            motor_id=mid,
                            value=value,
                        )
                        for mid in motor_ids
                    ],
                ),
            ).encode(),
        )
        await self._send_commands([cmd], label="emergency_stop")

        return {
            "bus_serial": resolved_serial,
            "motor_ids": motor_ids,
            "torque_enabled": False,
            "action": "emergency_stop",
        }

    def _resolve_bus(self, bus_serial: str = "auto") -> tuple[str, Any, ArmProfile]:
        if self.latest_inference is None:
            raise RuntimeError("No inference data available yet")

        self._check_frame_freshness()
        resolved_serial = resolve_bus_serial(self.latest_inference, bus_serial)
        bus = find_bus(self.latest_inference, resolved_serial)
        if bus is None:
            raise RuntimeError(f"Bus '{resolved_serial}' missing from latest frame")

        motor_ids = [m.get_id() for m in (bus.get_motors() or [])]
        profile = detect_arm_profile(motor_ids)
        return resolved_serial, bus, profile

    def get_arm_state(self, bus_serial: str = "auto") -> dict[str, Any]:
        """Return arm-oriented view: joints, gripper, and detected arm type."""
        resolved_serial, bus, profile = self._resolve_bus(bus_serial)

        joints = []
        gripper = None
        other = []

        for motor in bus.get_motors() or []:
            snapshot = annotate_motor(parse_motor_snapshot(motor).to_dict(), profile)
            role = snapshot["role"]
            if role == "gripper":
                gripper = snapshot
            elif role.startswith("joint_"):
                joints.append(snapshot)
            else:
                other.append(snapshot)

        joints.sort(key=lambda item: item["motor_id"])

        return {
            "bus_serial": resolved_serial,
            "arm_type": profile.name,
            "arm_label": profile.label,
            "joint_motor_ids": list(profile.joint_motor_ids),
            "gripper_motor_id": profile.gripper_motor_id,
            "joints": joints,
            "gripper": gripper,
            "other_motors": other,
            "note": (
                "Positions are joint-space (per-motor normalized 0.0-1.0), "
                "not Cartesian XYZ. Use move_joint / move_arm_pose for motion."
            ),
        }

    def list_buses(self) -> list[dict[str, Any]]:
        if self.latest_inference is None:
            return []

        buses = []
        for bus_state in self.latest_inference.get_buses() or []:
            info = bus_state.get_bus()
            if info is None:
                continue
            motors = [
                parse_motor_snapshot(motor).to_dict()
                for motor in (bus_state.get_motors() or [])
            ]
            buses.append(
                {
                    "serial": info.get_serial_number(),
                    "motor_count": len(motors),
                    "motors": motors,
                }
            )
        return buses

    def get_motor(
        self, bus_serial: str = "auto", motor_id: int = 1
    ) -> dict[str, Any]:
        if self.latest_inference is None:
            raise RuntimeError("No inference data available yet")

        resolved_serial = resolve_bus_serial(self.latest_inference, bus_serial)
        bus = find_bus(self.latest_inference, resolved_serial)
        if bus is None:
            raise RuntimeError(f"Bus '{resolved_serial}' missing from latest frame")

        for motor in bus.get_motors() or []:
            if motor.get_id() == motor_id:
                snapshot = parse_motor_snapshot(motor)
                return {
                    "bus_serial": resolved_serial,
                    **snapshot.to_dict(),
                }

        available = [m.get_id() for m in (bus.get_motors() or [])]
        raise RuntimeError(
            f"Motor {motor_id} not found on bus '{resolved_serial}'. "
            f"Available motor ids: {available}"
        )

    def _sync_write_command(
        self, bus_serial: str, address: int, motor_writes: list[tuple[int, bytes]]
    ) -> commands.DriverCommand:
        return commands.DriverCommand(
            type=drivers.StationCommandType.STC_ST3215_COMMAND,
            body=st3215.Command(
                target_bus_serial=bus_serial,
                sync_write=st3215.ST3215SyncWriteCommand(
                    address=address,
                    motors=[
                        st3215.ST3215SyncWriteCommand_MotorWrite(
                            motor_id=motor_id,
                            value=value,
                        )
                        for motor_id, value in motor_writes
                    ],
                ),
            ).encode(),
        )

    async def move_motors_normalized(
        self,
        positions: dict[int, float],
        bus_serial: str = "auto",
    ) -> dict[str, Any]:
        """Move multiple motors in one sync_write batch."""
        await self.ensure_connected()
        await self.wait_for_inference()

        if not positions:
            raise ValueError("positions must not be empty")

        resolved_serial, _, profile = self._resolve_bus(bus_serial)
        goal_writes: list[tuple[int, bytes]] = []
        resolved_targets: dict[str, dict[str, Any]] = {}

        for motor_id, position in sorted(positions.items()):
            if position < 0.0 or position > 1.0:
                raise ValueError(
                    f"position for motor {motor_id} must be between 0.0 and 1.0"
                )
            motor = self.get_motor(resolved_serial, motor_id)
            steps = normalized_to_steps(
                position, motor["range_min"], motor["range_max"]
            )
            goal_writes.append((motor_id, steps.to_bytes(2, byteorder="little")))
            resolved_targets[str(motor_id)] = {
                "role": motor_role(profile, motor_id),
                "position_normalized": position,
                "sent_steps": steps,
            }

        motor_ids_str = ",".join(str(k) for k in sorted(positions))
        await self._send_commands(
            [self._sync_write_command(resolved_serial, 0x2A, goal_writes)],
            label=f"move_motors[{motor_ids_str}]",
        )

        return {
            "bus_serial": resolved_serial,
            "arm_type": profile.name,
            "motors": resolved_targets,
        }

    async def move_joint(
        self,
        joint_id: int,
        position: float,
        bus_serial: str = "auto",
    ) -> dict[str, Any]:
        """Move one arm joint (joint id equals motor id on SO-101 / ElRobot)."""
        _, _, profile = self._resolve_bus(bus_serial)
        if joint_id not in profile.joint_motor_ids:
            raise ValueError(
                f"Joint {joint_id} is not an arm joint for {profile.label}. "
                f"Valid joints: {list(profile.joint_motor_ids)}. "
                f"Use set_gripper / open_gripper / close_gripper for the gripper."
            )
        result = await self.move_motors_normalized({joint_id: position}, bus_serial)
        result["joint_id"] = joint_id
        return result

    async def move_arm_pose(
        self,
        joint_positions: dict[int, float],
        bus_serial: str = "auto",
    ) -> dict[str, Any]:
        """Move multiple arm joints at once. Keys are joint ids (motor ids 1-5 or 1-7)."""
        _, _, profile = self._resolve_bus(bus_serial)
        invalid = [
            joint_id
            for joint_id in joint_positions
            if joint_id not in profile.joint_motor_ids
        ]
        if invalid:
            raise ValueError(
                f"Invalid joint ids {invalid} for {profile.label}. "
                f"Valid joints: {list(profile.joint_motor_ids)}. "
                "Gripper is controlled separately."
            )
        result = await self.move_motors_normalized(joint_positions, bus_serial)
        result["joint_positions"] = joint_positions
        return result

    async def set_gripper(
        self,
        position: float,
        bus_serial: str = "auto",
    ) -> dict[str, Any]:
        """Set gripper opening. 0.0 = fully closed, 1.0 = fully open (calibrated range)."""
        _, _, profile = self._resolve_bus(bus_serial)
        if profile.gripper_motor_id is None:
            raise RuntimeError("No gripper motor detected on this bus")

        result = await self.move_motors_normalized(
            {profile.gripper_motor_id: position},
            bus_serial,
        )
        result["gripper_motor_id"] = profile.gripper_motor_id
        result["gripper_position"] = position
        result["gripper_state"] = "open" if position >= 0.9 else "closed" if position <= 0.1 else "partial"
        return result

    async def open_gripper(self, bus_serial: str = "auto") -> dict[str, Any]:
        return await self.set_gripper(1.0, bus_serial)

    async def close_gripper(self, bus_serial: str = "auto") -> dict[str, Any]:
        return await self.set_gripper(0.0, bus_serial)

    async def enable_arm_torque(self, bus_serial: str = "auto") -> dict[str, Any]:
        _, bus, _profile = self._resolve_bus(bus_serial)
        motor_ids = [m.get_id() for m in (bus.get_motors() or [])]
        return await self.set_torque(motor_ids, True, bus_serial)

    async def disable_arm_torque(self, bus_serial: str = "auto") -> dict[str, Any]:
        _, bus, _profile = self._resolve_bus(bus_serial)
        motor_ids = [m.get_id() for m in (bus.get_motors() or [])]
        return await self.set_torque(motor_ids, False, bus_serial)

    async def move_motor_steps(
        self,
        motor_id: int,
        goal_steps: int,
        bus_serial: str = "auto",
    ) -> dict[str, Any]:
        await self.ensure_connected()
        await self.wait_for_inference()

        resolved_serial = resolve_bus_serial(self.latest_inference, bus_serial)
        motor = self.get_motor(resolved_serial, motor_id)
        range_min = motor["range_min"]
        range_max = motor["range_max"]

        if range_min > 0 or range_max > 0:
            clamped = max(range_min, min(range_max, goal_steps))
        else:
            clamped = goal_steps

        cmd = commands.DriverCommand(
            type=drivers.StationCommandType.STC_ST3215_COMMAND,
            body=st3215.Command(
                target_bus_serial=resolved_serial,
                write=st3215.ST3215WriteCommand(
                    motor_id=motor_id,
                    address=0x2A,
                    value=clamped.to_bytes(2, byteorder="little"),
                ),
            ).encode(),
        )
        await self._send_commands(
            [cmd], label=f"move_motor_steps[{motor_id}→{clamped}]"
        )

        return {
            "bus_serial": resolved_serial,
            "motor_id": motor_id,
            "requested_steps": goal_steps,
            "sent_steps": clamped,
        }

    async def move_motor_normalized(
        self,
        motor_id: int,
        position: float,
        bus_serial: str = "auto",
    ) -> dict[str, Any]:
        await self.wait_for_inference()
        resolved_serial = resolve_bus_serial(self.latest_inference, bus_serial)
        motor = self.get_motor(resolved_serial, motor_id)
        goal_steps = normalized_to_steps(
            position, motor["range_min"], motor["range_max"]
        )
        result = await self.move_motor_steps(motor_id, goal_steps, resolved_serial)
        result["position_normalized"] = position
        return result

    # ── Verification ────────────────────────────────────────────────────────

    POSITION_TOLERANCE_STEPS = 30
    GRIPPER_GRASP_CURRENT_MA = 200
    SETTLE_DELAY_S = 0.3

    async def verify_arm_position(
        self,
        tolerance_steps: int | None = None,
        bus_serial: str = "auto",
    ) -> dict[str, Any]:
        """Check whether each joint has reached its target position."""
        await self.ensure_connected()
        await self.wait_for_inference()

        tol = tolerance_steps if tolerance_steps is not None else self.POSITION_TOLERANCE_STEPS
        resolved_serial, bus, profile = self._resolve_bus(bus_serial)
        joints: list[dict[str, Any]] = []
        all_ok = True

        for motor in bus.get_motors() or []:
            snapshot = parse_motor_snapshot(motor)
            role = motor_role(profile, snapshot.motor_id)
            if role == "gripper":
                continue

            error = abs(snapshot.present_position - snapshot.target_position)
            reached = error <= tol
            if not reached:
                all_ok = False

            joints.append({
                "motor_id": snapshot.motor_id,
                "role": role,
                "present_position": snapshot.present_position,
                "target_position": snapshot.target_position,
                "error_steps": error,
                "tolerance_steps": tol,
                "reached": reached,
            })

        joints.sort(key=lambda j: j["motor_id"])
        return {
            "bus_serial": resolved_serial,
            "arm_type": profile.name,
            "all_reached": all_ok,
            "tolerance_steps": tol,
            "joints": joints,
        }

    async def verify_gripper_grasp(
        self,
        bus_serial: str = "auto",
    ) -> dict[str, Any]:
        """Detect whether the gripper is holding an object.

        Heuristics:
        - Current draw on gripper motor above threshold → motor is stalling against object.
        - Position gap: gripper didn't fully close → something is between the fingers.
        """
        await self.ensure_connected()
        await self.wait_for_inference()

        resolved_serial, bus, profile = self._resolve_bus(bus_serial)
        if profile.gripper_motor_id is None:
            raise RuntimeError("No gripper motor detected on this bus")

        gripper_motor = None
        for motor in bus.get_motors() or []:
            if motor.get_id() == profile.gripper_motor_id:
                gripper_motor = motor
                break
        if gripper_motor is None:
            raise RuntimeError(f"Gripper motor {profile.gripper_motor_id} not found on bus")

        snapshot = parse_motor_snapshot(gripper_motor)
        errors = decode_error_flags(snapshot.error_status)

        position_gap = abs(snapshot.present_position - snapshot.target_position)
        high_current = snapshot.present_current >= self.GRIPPER_GRASP_CURRENT_MA
        position_blocked = position_gap > self.POSITION_TOLERANCE_STEPS

        object_detected = high_current or position_blocked

        return {
            "bus_serial": resolved_serial,
            "gripper_motor_id": profile.gripper_motor_id,
            "object_detected": object_detected,
            "present_position": snapshot.present_position,
            "target_position": snapshot.target_position,
            "position_gap_steps": position_gap,
            "present_current_ma": snapshot.present_current,
            "current_threshold_ma": self.GRIPPER_GRASP_CURRENT_MA,
            "high_current": high_current,
            "position_blocked": position_blocked,
            "torque_enabled": snapshot.torque_enabled,
            "error_flags": errors,
        }

    async def verify_action(
        self,
        tolerance_steps: int | None = None,
        settle_s: float | None = None,
        bus_serial: str = "auto",
    ) -> dict[str, Any]:
        """Full post-action verification: positions + gripper + fresh camera image."""
        delay = settle_s if settle_s is not None else self.SETTLE_DELAY_S
        if delay > 0:
            await asyncio.sleep(delay)

        await self.ensure_connected()
        await self.wait_for_inference()

        result: dict[str, Any] = {}

        result["position"] = await self.verify_arm_position(tolerance_steps, bus_serial)

        try:
            result["gripper"] = await self.verify_gripper_grasp(bus_serial)
        except RuntimeError as exc:
            result["gripper_error"] = str(exc)

        try:
            result["camera"] = self.get_camera_image()
        except Exception as exc:
            result["camera_error"] = str(exc)

        position_ok = result["position"]["all_reached"]
        gripper = result.get("gripper", {})
        gripper_ok = not gripper.get("error_flags")

        result["summary"] = {
            "position_ok": position_ok,
            "gripper_ok": gripper_ok,
            "object_detected": gripper.get("object_detected"),
            "action_ok": position_ok and gripper_ok,
        }
        return result

    # ── Action history ───────────────────────────────────────────────────────

    def _record_action(
        self,
        action: str,
        params: dict[str, Any],
        result: dict[str, Any],
        success: bool,
    ) -> None:
        self._action_history.append({
            "action": action,
            "params": params,
            "success": success,
            "timestamp": time.time(),
            "frame_count": self.frame_count,
        })

    def get_action_history(self, limit: int = 10) -> list[dict[str, Any]]:
        items = list(self._action_history)
        return items[-limit:]

    # ── Agent planning loop primitives ───────────────────────────────────────

    MAX_RETRIES = 1

    async def move_and_verify(
        self,
        joint_positions: dict[int, float],
        tolerance_steps: int | None = None,
        settle_s: float | None = None,
        bus_serial: str = "auto",
    ) -> dict[str, Any]:
        """Move joints and verify they reached target, with one auto-retry on failure."""
        delay = settle_s if settle_s is not None else self.SETTLE_DELAY_S
        tol = tolerance_steps if tolerance_steps is not None else self.POSITION_TOLERANCE_STEPS

        move_result = await self.move_arm_pose(joint_positions, bus_serial)
        await asyncio.sleep(delay)
        verify_result = await self.verify_arm_position(tol, bus_serial)

        if not verify_result["all_reached"]:
            self.logger.warning("move_and_verify: first attempt failed, retrying")
            move_result = await self.move_arm_pose(joint_positions, bus_serial)
            await asyncio.sleep(delay * 2)
            verify_result = await self.verify_arm_position(tol, bus_serial)

        success = verify_result["all_reached"]
        result = {
            "move": move_result,
            "verification": verify_result,
            "success": success,
        }
        self._record_action("move_and_verify", {"joint_positions": joint_positions}, result, success)
        return result

    async def pick_object(
        self,
        approach_positions: dict[int, float],
        grasp_positions: dict[int, float] | None = None,
        lift_positions: dict[int, float] | None = None,
        bus_serial: str = "auto",
    ) -> dict[str, Any]:
        """Full pick sequence: approach → open gripper → move to grasp → close → verify → lift.

        approach_positions: joint positions above the object
        grasp_positions: joint positions at grasp height (defaults to approach_positions)
        lift_positions: joint positions after grasping (defaults to approach_positions)
        """
        steps: list[dict[str, Any]] = []
        grasp = grasp_positions or approach_positions
        lift = lift_positions or approach_positions

        step = await self.move_and_verify(approach_positions, bus_serial=bus_serial)
        steps.append({"name": "approach", **step})
        if not step["success"]:
            result = {"success": False, "failed_at": "approach", "steps": steps}
            self._record_action("pick_object", {"approach": approach_positions}, result, False)
            return result

        await self.open_gripper(bus_serial)
        await asyncio.sleep(self.SETTLE_DELAY_S)
        steps.append({"name": "open_gripper", "success": True})

        if grasp != approach_positions:
            step = await self.move_and_verify(grasp, bus_serial=bus_serial)
            steps.append({"name": "grasp_approach", **step})
            if not step["success"]:
                result = {"success": False, "failed_at": "grasp_approach", "steps": steps}
                self._record_action("pick_object", {"approach": approach_positions}, result, False)
                return result

        await self.close_gripper(bus_serial)
        await asyncio.sleep(self.SETTLE_DELAY_S)

        grasp_check = await self.verify_gripper_grasp(bus_serial)
        steps.append({"name": "grasp_verify", **grasp_check})

        step = await self.move_and_verify(lift, bus_serial=bus_serial)
        steps.append({"name": "lift", **step})

        grasp_after_lift = await self.verify_gripper_grasp(bus_serial)
        object_held = grasp_after_lift.get("object_detected", False)
        steps.append({"name": "lift_grasp_verify", **grasp_after_lift})

        try:
            camera = self.get_camera_image()
        except Exception:
            camera = None

        success = step["success"] and object_held
        result = {
            "success": success,
            "object_held": object_held,
            "steps": steps,
            "camera": camera,
        }
        self._record_action("pick_object", {"approach": approach_positions}, result, success)
        return result

    async def place_object(
        self,
        place_positions: dict[int, float],
        retreat_positions: dict[int, float] | None = None,
        bus_serial: str = "auto",
    ) -> dict[str, Any]:
        """Full place sequence: move to position → open gripper → verify release → retreat.

        place_positions: joint positions where the object should be placed
        retreat_positions: joint positions to retract to after placing (defaults to place_positions)
        """
        steps: list[dict[str, Any]] = []
        retreat = retreat_positions or place_positions

        step = await self.move_and_verify(place_positions, bus_serial=bus_serial)
        steps.append({"name": "place_approach", **step})
        if not step["success"]:
            result = {"success": False, "failed_at": "place_approach", "steps": steps}
            self._record_action("place_object", {"place": place_positions}, result, False)
            return result

        await self.open_gripper(bus_serial)
        await asyncio.sleep(self.SETTLE_DELAY_S)

        release_check = await self.verify_gripper_grasp(bus_serial)
        object_released = not release_check.get("object_detected", True)
        steps.append({"name": "release_verify", "object_released": object_released, **release_check})

        if retreat != place_positions:
            step = await self.move_and_verify(retreat, bus_serial=bus_serial)
            steps.append({"name": "retreat", **step})

        try:
            camera = self.get_camera_image()
        except Exception:
            camera = None

        success = object_released
        result = {
            "success": success,
            "object_released": object_released,
            "steps": steps,
            "camera": camera,
        }
        self._record_action("place_object", {"place": place_positions}, result, success)
        return result

    async def get_planning_state(self, bus_serial: str = "auto") -> dict[str, Any]:
        """Complete world state snapshot for the AI agent to plan from."""
        await self.ensure_connected()
        await self.wait_for_inference()

        state: dict[str, Any] = {}

        try:
            state["arm"] = self.get_arm_state(bus_serial)
        except Exception as exc:
            state["arm_error"] = str(exc)

        try:
            state["gripper"] = await self.verify_gripper_grasp(bus_serial)
        except Exception as exc:
            state["gripper_error"] = str(exc)

        try:
            state["health"] = self.get_motor_health(bus_serial)
        except Exception as exc:
            state["health_error"] = str(exc)

        try:
            state["camera"] = self.get_camera_image()
        except Exception as exc:
            state["camera_error"] = str(exc)

        state["connection"] = self.connection_info()
        state["recent_actions"] = self.get_action_history(5)

        arm = state.get("arm", {})
        gripper = state.get("gripper", {})
        health = state.get("health", {})

        state["summary"] = {
            "arm_type": arm.get("arm_type"),
            "joint_count": len(arm.get("joints", [])),
            "torque_enabled": any(
                j.get("torque_enabled", False) for j in arm.get("joints", [])
            ),
            "object_held": gripper.get("object_detected"),
            "healthy": health.get("healthy"),
            "camera_available": "camera" in state,
            "recent_action_count": len(state["recent_actions"]),
        }
        return state

    async def set_torque(
        self,
        motor_ids: list[int],
        enable: bool,
        bus_serial: str = "auto",
    ) -> dict[str, Any]:
        await self.ensure_connected()
        await self.wait_for_inference()

        resolved_serial = resolve_bus_serial(self.latest_inference, bus_serial)
        if not motor_ids:
            raise ValueError("motor_ids must not be empty")

        value = b"\x01" if enable else b"\x00"
        cmd = commands.DriverCommand(
            type=drivers.StationCommandType.STC_ST3215_COMMAND,
            body=st3215.Command(
                target_bus_serial=resolved_serial,
                sync_write=st3215.ST3215SyncWriteCommand(
                    address=0x28,
                    motors=[
                        st3215.ST3215SyncWriteCommand_MotorWrite(
                            motor_id=motor_id,
                            value=value,
                        )
                        for motor_id in motor_ids
                    ],
                ),
            ).encode(),
        )
        action = "enable_torque" if enable else "disable_torque"
        ids_str = ",".join(str(m) for m in motor_ids)
        await self._send_commands([cmd], label=f"{action}[{ids_str}]")

        return {
            "bus_serial": resolved_serial,
            "motor_ids": motor_ids,
            "torque_enabled": enable,
        }


_session: StationSession | None = None


def get_session() -> StationSession:
    global _session
    if _session is None:
        _session = StationSession()
    return _session

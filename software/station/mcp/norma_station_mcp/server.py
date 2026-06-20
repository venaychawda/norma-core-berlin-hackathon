from __future__ import annotations

import json
import logging
import os

from fastmcp import FastMCP

from .session import get_session
from .vla_bridge import get_vla_bridge

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("norma-station-mcp")

mcp = FastMCP(
    name="NormaCore Station",
    instructions=(
        "NormaCore robotics MCP server. Station must run with `--tcp` (port 8888).\n\n"
        "Prefer high-level tools:\n"
        "- get_full_observation: arm state + camera image in one call (start here)\n"
        "- capture_image: get a 224x224 JPEG camera image of the workspace\n"
        "- get_arm_state: read joints + gripper with roles\n"
        "- move_joint / move_arm_pose: joint-space motion (0.0-1.0 per joint)\n"
        "- open_gripper / close_gripper / set_gripper: gripper control\n"
        "- enable_arm_torque / disable_arm_torque: power all motors\n"
        "- emergency_stop: immediately disable all motors (safety)\n"
        "- get_motor_health: check current draw, errors, warnings\n"
        "- verify_arm_position: check joints reached target after a move\n"
        "- verify_gripper_grasp: detect if gripper is holding an object\n"
        "- verify_action: full post-action check (positions + grasp + camera)\n"
        "- move_and_verify: reliable move with auto-retry (preferred over move_arm_pose)\n"
        "- pick_object: full pick sequence with grasp verification\n"
        "- place_object: full place sequence with release verification\n"
        "- get_planning_state: complete world snapshot for deciding next action\n\n"
        "## SmolVLA Vision-Language-Action (requires loaded model)\n"
        "- vla_status: check if SmolVLA model is loaded and ready\n"
        "- vla_load_model: load a trained SmolVLA checkpoint\n"
        "- vla_step: run SmolVLA inference — model sees camera and moves arm toward a goal\n\n"
        "### Object Manipulation via VLA\n"
        "When a user asks to manipulate objects ('fetch me X', 'pick up Y', 'move Z'),\n"
        "decompose into sub-tasks using vla_step + gripper tools:\n"
        "  1. capture_image — confirm target object is visible\n"
        "  2. vla_step('move to the {object}', n_steps=30) — approach\n"
        "  3. open_gripper — prepare to grasp\n"
        "  4. vla_step('grasp the {object}', n_steps=15) — fine-position\n"
        "  5. close_gripper — grip the object\n"
        "  6. verify_gripper_grasp — confirm hold\n"
        "  7. vla_step('lift the {object}', n_steps=10) — lift\n"
        "  8. move_arm_pose(base positions) — return home\n"
        "After each vla_step, check the returned image to verify progress.\n\n"
        "Joint ids match motor ids (SO-101: joints 1-5, gripper 6; ElRobot: joints 1-7, gripper 8).\n"
        "Positions are normalized within each motor's calibrated range, not Cartesian XYZ.\n"
        "Low-level advanced_* tools exist for debugging."
    ),
)


def _json(data: object) -> str:
    return json.dumps(data, indent=2)


# ── Discovery & state ─────────────────────────────────────────────────────────


@mcp.tool
async def station_connection_status() -> str:
    """Check connectivity to the NormaCore Station TCP server."""
    session = get_session()
    try:
        await session.ensure_connected()
        await session.wait_for_inference(timeout_s=5.0)
    except Exception as exc:
        info = session.connection_info()
        info["error"] = str(exc)
        return _json(info)

    info = session.connection_info()
    info["bus_count"] = len(session.list_buses())
    return _json(info)


@mcp.tool
async def get_arm_state(bus_serial: str = "auto") -> str:
    """Read the full arm: detected type (SO-101 / ElRobot), joint positions, and gripper state.

    Start here before moving the robot. Returns normalized positions (0.0-1.0) per joint.
    """
    session = get_session()
    await session.ensure_connected()
    await session.wait_for_inference()
    return _json(session.get_arm_state(bus_serial))


# ── Camera / Vision ──────────────────────────────────────────────────────────


@mcp.tool
async def capture_image(bus_serial: str = "auto") -> str:
    """Capture a camera image from the robot's workspace (224x224 JPEG, base64-encoded).

    Requires a connected camera and at least one motor with torque enabled.
    Use this to observe the workspace before and after robot actions.
    Returns base64 JPEG in the 'image_base64' field.
    """
    session = get_session()
    await session.ensure_connected()
    await session.wait_for_normvla(timeout_s=10.0)
    return _json(session.get_camera_image())


@mcp.tool
async def get_full_observation(bus_serial: str = "auto") -> str:
    """Get arm state and camera image in a single call — the complete world view.

    Returns both the arm joint/gripper state and a 224x224 JPEG camera image.
    Use this for observe-plan-act-verify cycles.
    """
    session = get_session()
    await session.ensure_connected()
    await session.wait_for_inference()
    return _json(session.get_full_observation(bus_serial))


# ── Safety ───────────────────────────────────────────────────────────────────


@mcp.tool
async def emergency_stop(bus_serial: str = "auto") -> str:
    """EMERGENCY STOP — immediately disable torque on all motors.

    The arm will go limp. Use when something is wrong: unexpected motion,
    collision risk, or motor errors. Skips the normal inference wait for speed.
    After calling this, use enable_arm_torque to re-enable the arm.
    """
    session = get_session()
    return _json(await session.emergency_stop(bus_serial))


@mcp.tool
async def get_motor_health(bus_serial: str = "auto") -> str:
    """Check motor health: current draw, error flags, and position tracking per motor.

    Returns warnings for motors with errors (overload, overheat, angle limit, etc.)
    or unusually high current draw (>500mA). Use this to diagnose issues before
    or after moving the arm.
    """
    session = get_session()
    await session.ensure_connected()
    await session.wait_for_inference()
    return _json(session.get_motor_health(bus_serial))


# ── Verification ─────────────────────────────────────────────────────────────


@mcp.tool
async def verify_arm_position(
    tolerance_steps: int = 30,
    bus_serial: str = "auto",
) -> str:
    """Check whether each arm joint has reached its target position.

    Call this after move_joint or move_arm_pose to confirm the arm arrived.
    Each joint reports reached=true/false based on the step-error tolerance.
    Default tolerance is 30 encoder steps (~2.6 degrees on ST3215).
    """
    session = get_session()
    return _json(await session.verify_arm_position(tolerance_steps, bus_serial))


@mcp.tool
async def verify_gripper_grasp(bus_serial: str = "auto") -> str:
    """Detect whether the gripper is holding an object.

    Call after close_gripper or set_gripper. Uses two heuristics:
    - Current spike: gripper motor stalling against an object (>=200mA).
    - Position gap: gripper didn't reach target (something blocks it).
    Returns object_detected=true if either heuristic fires.
    """
    session = get_session()
    return _json(await session.verify_gripper_grasp(bus_serial))


@mcp.tool
async def verify_action(
    tolerance_steps: int = 30,
    settle_seconds: float = 0.3,
    bus_serial: str = "auto",
) -> str:
    """Full post-action verification: arm positions + gripper grasp + camera image.

    Call after any robot action to get a complete verification snapshot.
    Waits settle_seconds (default 0.3s) for the arm to stabilize, then checks:
    - All joint positions within tolerance of their targets
    - Gripper grasp detection (current + position gap)
    - Fresh camera image of the workspace
    Returns a summary with action_ok=true if everything checks out.
    """
    session = get_session()
    return _json(
        await session.verify_action(tolerance_steps, settle_seconds, bus_serial)
    )


# ── Agent planning loop ──────────────────────────────────────────────────────


@mcp.tool
async def move_and_verify(
    joint_positions: dict[int, float],
    tolerance_steps: int = 30,
    settle_seconds: float = 0.3,
    bus_serial: str = "auto",
) -> str:
    """Move arm joints and verify they reached target. Retries once on failure.

    Combines move_arm_pose + verify_arm_position into a single reliable call.
    Use this instead of separate move + verify when you need guaranteed arrival.
    Returns success=true only if all joints are within tolerance after settling.
    """
    session = get_session()
    return _json(
        await session.move_and_verify(
            joint_positions, tolerance_steps, settle_seconds, bus_serial
        )
    )


@mcp.tool
async def pick_object(
    approach_positions: dict[int, float],
    grasp_positions: dict[int, float] | None = None,
    lift_positions: dict[int, float] | None = None,
    bus_serial: str = "auto",
) -> str:
    """Full pick sequence: approach → open gripper → lower to grasp → close gripper → verify grasp → lift.

    approach_positions: joint positions above the object (also used as lift target if lift_positions omitted).
    grasp_positions: joint positions at grasp height (defaults to approach_positions).
    lift_positions: joint positions after grasping (defaults to approach_positions).

    Returns success=true and object_held=true if the gripper grasped an object.
    Each step is verified — the sequence stops early and reports which step failed.
    Includes a camera image of the final state.
    """
    session = get_session()
    return _json(
        await session.pick_object(
            approach_positions, grasp_positions, lift_positions, bus_serial
        )
    )


@mcp.tool
async def place_object(
    place_positions: dict[int, float],
    retreat_positions: dict[int, float] | None = None,
    bus_serial: str = "auto",
) -> str:
    """Full place sequence: move to position → open gripper → verify release → retreat.

    place_positions: joint positions where the object should be placed.
    retreat_positions: joint positions to retract to after placing (defaults to place_positions).

    Returns success=true and object_released=true if the gripper released successfully.
    Each step is verified. Includes a camera image of the final state.
    """
    session = get_session()
    return _json(
        await session.place_object(place_positions, retreat_positions, bus_serial)
    )


@mcp.tool
async def get_planning_state(bus_serial: str = "auto") -> str:
    """Get complete world state for planning the next action.

    Returns everything the agent needs to decide what to do next:
    - Arm state: joint positions, arm type, detected profile
    - Gripper: position, current, whether holding an object
    - Motor health: errors, warnings, current draw
    - Camera: fresh workspace image (base64 JPEG)
    - Recent actions: last 5 actions with outcomes
    - Summary: quick-read flags (torque_enabled, object_held, healthy, etc.)

    Call this at the start of a task and after each action to observe the result.
    """
    session = get_session()
    return _json(await session.get_planning_state(bus_serial))


# ── Gripper ───────────────────────────────────────────────────────────────────


@mcp.tool
async def open_gripper(bus_serial: str = "auto") -> str:
    """Fully open the gripper (position 0.0 on the gripper motor's calibrated range)."""
    session = get_session()
    return _json(await session.open_gripper(bus_serial))


@mcp.tool
async def close_gripper(bus_serial: str = "auto") -> str:
    """Fully close the gripper (position 1.0 on the gripper motor's calibrated range)."""
    session = get_session()
    return _json(await session.close_gripper(bus_serial))


@mcp.tool
async def set_gripper(position: float, bus_serial: str = "auto") -> str:
    """Set gripper opening. 0.0 = open, 1.0 = closed, values in between = partial grasp."""
    session = get_session()
    return _json(await session.set_gripper(position, bus_serial))


# ── Arm motion (joint space) ──────────────────────────────────────────────────


@mcp.tool
async def move_joint(joint_id: int, position: float, bus_serial: str = "auto") -> str:
    """Move one arm joint to a normalized position (0.0 = min, 1.0 = max).

    Joint id equals motor id: SO-101 joints are 1-5, ElRobot joints are 1-7.
    Does not move the gripper — use open_gripper / close_gripper for that.
    """
    session = get_session()
    return _json(await session.move_joint(joint_id, position, bus_serial))


@mcp.tool
async def move_arm_pose(
    joint_positions: dict[int, float],
    bus_serial: str = "auto",
) -> str:
    """Move multiple arm joints at once. Example: {1: 0.5, 2: 0.3, 3: 0.8}.

    Keys are joint ids (motor ids). Values are normalized 0.0-1.0 within each
    joint's calibrated range. Gripper is not included — control it separately.
    """
    session = get_session()
    return _json(await session.move_arm_pose(joint_positions, bus_serial))


@mcp.tool
async def enable_arm_torque(bus_serial: str = "auto") -> str:
    """Enable torque on all motors (required before the arm can hold position)."""
    session = get_session()
    return _json(await session.enable_arm_torque(bus_serial))


@mcp.tool
async def disable_arm_torque(bus_serial: str = "auto") -> str:
    """Disable torque on all motors (arm goes limp — use with care)."""
    session = get_session()
    return _json(await session.disable_arm_torque(bus_serial))


# ── Advanced / low-level ─────────────────────────────────────────────────────


@mcp.tool
async def advanced_list_motor_buses() -> str:
    """Low-level: raw ST3215 bus list with unlabeled motor registers."""
    session = get_session()
    await session.ensure_connected()
    await session.wait_for_inference()
    return _json({"buses": session.list_buses()})


@mcp.tool
async def advanced_get_motor_state(bus_serial: str = "auto", motor_id: int = 1) -> str:
    """Low-level: read one motor by id without arm role labels."""
    session = get_session()
    await session.ensure_connected()
    await session.wait_for_inference()
    return _json(session.get_motor(bus_serial, motor_id))


@mcp.tool
async def advanced_move_motor_normalized(
    motor_id: int,
    position: float,
    bus_serial: str = "auto",
) -> str:
    """Low-level: move any motor by id to normalized position 0.0-1.0."""
    session = get_session()
    return _json(await session.move_motor_normalized(motor_id, position, bus_serial))


@mcp.tool
async def advanced_move_motor_steps(
    motor_id: int,
    goal_steps: int,
    bus_serial: str = "auto",
) -> str:
    """Low-level: move any motor to absolute encoder steps."""
    session = get_session()
    return _json(await session.move_motor_steps(motor_id, goal_steps, bus_serial))


@mcp.tool
async def advanced_set_motor_torque(
    motor_ids: list[int],
    enable: bool,
    bus_serial: str = "auto",
) -> str:
    """Low-level: enable/disable torque on specific motor ids."""
    session = get_session()
    return _json(await session.set_torque(motor_ids, enable, bus_serial))


# ── SmolVLA Vision-Language-Action ──────────────────────────────────────────


@mcp.tool
async def vla_status() -> str:
    """Check SmolVLA model status — whether dependencies are installed and model is loaded.

    Call this first to see if SmolVLA is available before attempting inference.
    Returns the task prompt guide showing how to decompose user requests into sub-tasks.
    """
    bridge = get_vla_bridge()
    return _json(bridge.status())


@mcp.tool
async def vla_load_model(checkpoint_path: str = "", device: str = "") -> str:
    """Load a trained SmolVLA checkpoint for vision-guided motor control.

    The checkpoint directory must contain: config.json, model.safetensors, stats.safetensors.
    These are produced by scripts/train.py in software/ai/smolvla_py.

    Args:
        checkpoint_path: Path to checkpoint directory. Defaults to SMOLVLA_CHECKPOINT env var.
        device: 'cpu' or 'cuda'. Auto-detected if empty.

    Note: model loading takes 10-60s depending on device. On Raspberry Pi (CPU),
    expect ~30s load time and ~10-30s per inference tick.
    """
    bridge = get_vla_bridge()
    path = checkpoint_path or os.environ.get("SMOLVLA_CHECKPOINT", "")
    if not path:
        raise ValueError(
            "No checkpoint path provided. Pass checkpoint_path or set "
            "SMOLVLA_CHECKPOINT environment variable."
        )
    return _json(bridge.load(path, device or None))


@mcp.tool
async def vla_step(
    task: str,
    n_steps: int = 10,
    bus_serial: str = "auto",
    max_delta_ticks: int = 200,
) -> str:
    """Run SmolVLA vision-language-action inference — the model sees the camera and moves the arm.

    Each tick: fetch camera frame → run neural network → predict joint goals → send motor command.
    The model is conditioned on the task prompt to decide WHERE to move.

    Args:
        task: Natural language task prompt. Use action-oriented phrases:
              - "move to the {object}" — approach an object
              - "move above the {object}" — position above for pre-grasp
              - "grasp the {object}" — fine-position for grasping
              - "lift the {object}" — raise a grasped object
              - "place the {object} on the {target}" — place at location
              - "return to home" — go to rest position
              Replace {object} with the actual object name + color (e.g. "yellow pen").
        n_steps: Number of inference ticks (each tick = see + predict + move).
                 More steps = more time to reach the target.
                 Typical: 20-40 for approach, 10-20 for fine adjustments, 5-15 for lift.
        bus_serial: ST3215 bus serial (default "auto").
        max_delta_ticks: Safety limit — skip a tick if predicted motion exceeds this
                         many encoder steps on any joint. Prevents large jumps. 0 = disabled.

    Returns the final arm state and camera image so you can verify whether the
    sub-task succeeded before moving to the next step.

    Example — "Fetch me the yellow pen":
      1. capture_image() — confirm pen is visible
      2. vla_step("move to the yellow pen", n_steps=30) — approach
      3. Check returned image — is arm near the pen?
      4. open_gripper()
      5. vla_step("grasp the yellow pen", n_steps=15) — fine-position
      6. close_gripper()
      7. verify_gripper_grasp() — confirm hold
      8. vla_step("lift the yellow pen", n_steps=10) — lift
      9. move_arm_pose({base positions}) — return home
    """
    bridge = get_vla_bridge()
    session = get_session()
    return _json(
        await bridge.run_steps(
            session, task, n_steps, bus_serial,
            max_delta_ticks=max_delta_ticks,
        )
    )


def main() -> None:
    logger.info("Starting NormaCore Station MCP server (stdio)")
    mcp.run()


if __name__ == "__main__":
    main()

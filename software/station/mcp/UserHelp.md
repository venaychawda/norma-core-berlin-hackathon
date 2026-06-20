# NormaCore Station MCP — Tool Reference

Complete guide to all 25 MCP tools for controlling your robot arm through an AI agent.

> **Prerequisites:** Station running with `--tcp` on port 8888, MCP server configured in your editor. See [README.md](README.md) for setup.

---

## Quick Start

If you're new, follow this sequence:

```
1. station_connection_status     → confirm the station is reachable
2. get_arm_state                 → see joints, gripper, and arm type
3. enable_arm_torque             → power the motors (required before moving)
4. get_planning_state            → full world view (arm + gripper + camera + health)
5. move_and_verify {1: 0.5}     → move joint 1 to midpoint, verify it arrived
6. close_gripper                 → close the gripper
7. verify_gripper_grasp          → check if something was grasped
```

---

## Tool Categories

| Category | Tools | When to use |
|----------|-------|-------------|
| [Discovery & State](#discovery--state) | `station_connection_status`, `get_arm_state`, `get_full_observation` | Starting a session, reading current state |
| [Camera / Vision](#camera--vision) | `capture_image`, `get_full_observation` | Observing the workspace visually |
| [Safety](#safety) | `emergency_stop`, `get_motor_health` | Something goes wrong, diagnosing issues |
| [Gripper](#gripper) | `open_gripper`, `close_gripper`, `set_gripper` | Grasping and releasing objects |
| [Arm Motion](#arm-motion) | `move_joint`, `move_arm_pose`, `enable_arm_torque`, `disable_arm_torque` | Moving the robot arm |
| [Verification](#verification) | `verify_arm_position`, `verify_gripper_grasp`, `verify_action` | Confirming actions succeeded |
| [Planning Loop](#planning-loop) | `move_and_verify`, `pick_object`, `place_object`, `get_planning_state` | Autonomous task execution |
| [Advanced / Low-level](#advanced--low-level) | `advanced_list_motor_buses`, `advanced_get_motor_state`, `advanced_move_motor_normalized`, `advanced_move_motor_steps`, `advanced_set_motor_torque` | Debugging, raw motor access |

---

## Discovery & State

### `station_connection_status`

Check whether the MCP server can reach the NormaCore Station.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| *(none)* | | | |

**Returns:** host, connected status, frame count, bus count, stream health, uptime, errors.

**Use when:** Starting a session, diagnosing connection problems.

```
→ station_connection_status
← { "host": "localhost:8888", "connected": true, "bus_count": 1, ... }
```

---

### `get_arm_state`

Read the full arm: detected type, all joint positions, and gripper state.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bus_serial` | string | `"auto"` | Serial number of the motor bus. `"auto"` picks the only bus or uses `DEFAULT_BUS_SERIAL`. |

**Returns:** arm type (SO-101 / ElRobot), joint list with normalized positions (0.0-1.0), gripper state, motor ids.

**Use when:** Before moving the robot, to know where every joint is.

```
→ get_arm_state
← {
    "arm_type": "elrobot",
    "arm_label": "ElRobot (7 DoF + gripper on motor 8)",
    "joints": [
      { "motor_id": 1, "role": "joint_1", "present_position_normalized": 0.52, ... },
      ...
    ],
    "gripper": { "motor_id": 8, "role": "gripper", ... }
  }
```

---

### `get_full_observation`

Arm state + camera image in a single call.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bus_serial` | string | `"auto"` | Motor bus serial. |

**Returns:** Combined `arm` (same as `get_arm_state`) and `camera` (same as `capture_image`) fields.

**Use when:** You need both the arm position and a workspace image in one round-trip.

---

## Camera / Vision

### `capture_image`

Capture a 224x224 JPEG image from the robot's workspace camera.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bus_serial` | string | `"auto"` | Motor bus serial. |

**Returns:** Base64-encoded JPEG in `image_base64`, image dimensions, frame age.

**Requires:** Camera connected and at least one motor with torque enabled (the vision pipeline activates when torque is on).

```
→ capture_image
← { "image_base64": "/9j/4AAQ...", "format": "jpeg", "width": 224, "height": 224, ... }
```

---

## Safety

### `emergency_stop`

Immediately disable torque on all motors. The arm goes limp.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bus_serial` | string | `"auto"` | Motor bus serial. |

**Use when:** Unexpected motion, collision risk, motor errors, or anything unsafe.

**Recovery:** Call `enable_arm_torque` to re-enable after the situation is resolved.

> This tool skips the normal inference wait for speed. It uses cached motor data to act as fast as possible.

---

### `get_motor_health`

Per-motor diagnostics: current draw, error flags, position tracking.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bus_serial` | string | `"auto"` | Motor bus serial. |

**Returns:** Per-motor health data, aggregated warnings, and `healthy: true/false`.

**Warnings are generated for:**
- Error flags: voltage, angle_limit, overheat, range, checksum, overload, instruction
- High current draw (>500mA)

```
→ get_motor_health
← {
    "healthy": true,
    "warnings": [],
    "motors": [
      { "motor_id": 1, "role": "joint_1", "torque_enabled": true, "present_current_ma": 120, "error_flags": [], ... },
      ...
    ]
  }
```

---

## Gripper

### `open_gripper`

Fully open the gripper (position 0.0).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bus_serial` | string | `"auto"` | Motor bus serial. |

---

### `close_gripper`

Fully close the gripper (position 1.0).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bus_serial` | string | `"auto"` | Motor bus serial. |

---

### `set_gripper`

Set the gripper to a specific opening.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `position` | float | *(required)* | 0.0 = fully open, 1.0 = fully closed, values in between = partial grasp. |
| `bus_serial` | string | `"auto"` | Motor bus serial. |

```
→ set_gripper(position=0.5)
← { "gripper_position": 0.5, "gripper_state": "partial", ... }
```

---

## Arm Motion

### `move_joint`

Move a single arm joint to a normalized position.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `joint_id` | int | *(required)* | Joint id (equals motor id). SO-101: 1-5, ElRobot: 1-7. |
| `position` | float | *(required)* | Normalized position: 0.0 = min, 1.0 = max of calibrated range. |
| `bus_serial` | string | `"auto"` | Motor bus serial. |

> Does **not** move the gripper. Use `open_gripper` / `close_gripper` / `set_gripper` for that.

```
→ move_joint(joint_id=3, position=0.7)
← { "joint_id": 3, "motors": { "3": { "role": "joint_3", "position_normalized": 0.7, ... } } }
```

---

### `move_arm_pose`

Move multiple arm joints simultaneously.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `joint_positions` | dict | *(required)* | Map of joint id to normalized position. Example: `{1: 0.5, 2: 0.3, 3: 0.8}` |
| `bus_serial` | string | `"auto"` | Motor bus serial. |

> For reliable motion with arrival confirmation, prefer `move_and_verify` instead.

```
→ move_arm_pose(joint_positions={1: 0.5, 2: 0.3, 3: 0.8})
← { "arm_type": "elrobot", "motors": { "1": {...}, "2": {...}, "3": {...} } }
```

---

### `enable_arm_torque`

Power on all motors. Required before the arm can hold position or move.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bus_serial` | string | `"auto"` | Motor bus serial. |

> Always call this before sending any move commands. Without torque, the arm is limp.

---

### `disable_arm_torque`

Power off all motors. The arm goes limp.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bus_serial` | string | `"auto"` | Motor bus serial. |

> Use with care. The arm will drop to wherever gravity takes it.

---

## Verification

### `verify_arm_position`

Check whether each joint has reached its target position.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tolerance_steps` | int | `30` | Maximum allowed error in encoder steps (~2.6 degrees on ST3215). |
| `bus_serial` | string | `"auto"` | Motor bus serial. |

**Returns:** Per-joint `reached: true/false` and overall `all_reached: true/false`.

```
→ verify_arm_position(tolerance_steps=30)
← {
    "all_reached": true,
    "joints": [
      { "motor_id": 1, "role": "joint_1", "error_steps": 5, "reached": true },
      ...
    ]
  }
```

---

### `verify_gripper_grasp`

Detect whether the gripper is holding an object.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bus_serial` | string | `"auto"` | Motor bus serial. |

**Detection heuristics:**
- **Current spike:** Gripper motor drawing >= 200mA (stalling against object).
- **Position gap:** Gripper didn't reach its target (object blocking closure).

```
→ verify_gripper_grasp
← {
    "object_detected": true,
    "high_current": true,
    "position_blocked": true,
    "present_current_ma": 350,
    "position_gap_steps": 120
  }
```

---

### `verify_action`

Full post-action verification: positions + gripper + camera image.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tolerance_steps` | int | `30` | Position tolerance in encoder steps. |
| `settle_seconds` | float | `0.3` | Wait time before checking (lets the arm stabilize). |
| `bus_serial` | string | `"auto"` | Motor bus serial. |

**Returns:** Position verification, gripper grasp state, camera image, and a summary with `action_ok: true/false`.

---

## Planning Loop

These are the high-level tools for autonomous observe-plan-act-verify cycles. They combine lower-level tools with built-in verification, retries, and action history tracking.

### `get_planning_state`

Complete world snapshot for the AI agent to plan from.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bus_serial` | string | `"auto"` | Motor bus serial. |

**Returns all of:**
- `arm` — full arm state (joints, gripper, type)
- `gripper` — grasp detection (object held?)
- `health` — motor errors, warnings, current draw
- `camera` — fresh workspace image (base64 JPEG)
- `recent_actions` — last 5 actions with outcomes
- `summary` — quick-read flags: `torque_enabled`, `object_held`, `healthy`, `camera_available`

**Use when:** At the start of a task, and after each action to observe the outcome.

```
→ get_planning_state
← {
    "summary": {
      "arm_type": "elrobot",
      "joint_count": 7,
      "torque_enabled": true,
      "object_held": false,
      "healthy": true,
      "camera_available": true,
      "recent_action_count": 2
    },
    "arm": { ... },
    "gripper": { ... },
    "health": { ... },
    "camera": { "image_base64": "...", ... },
    "recent_actions": [ ... ]
  }
```

---

### `move_and_verify`

Move arm joints and verify arrival. Retries once on failure.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `joint_positions` | dict | *(required)* | Map of joint id to normalized position. Example: `{1: 0.5, 2: 0.3}` |
| `tolerance_steps` | int | `30` | Position tolerance in encoder steps. |
| `settle_seconds` | float | `0.3` | Wait time before verifying. |
| `bus_serial` | string | `"auto"` | Motor bus serial. |

**Returns:** `success: true/false`, move result, and verification details.

> Preferred over `move_arm_pose` for any motion that needs to be reliable.

```
→ move_and_verify(joint_positions={1: 0.5, 3: 0.8})
← {
    "success": true,
    "move": { ... },
    "verification": { "all_reached": true, "joints": [...] }
  }
```

---

### `pick_object`

Full pick sequence with verification at every step.

**Sequence:** approach position → open gripper → lower to grasp position → close gripper → verify grasp → lift.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `approach_positions` | dict | *(required)* | Joint positions above the object. Also used as lift target if `lift_positions` is omitted. |
| `grasp_positions` | dict or null | `null` | Joint positions at grasp height. Defaults to `approach_positions` if omitted. |
| `lift_positions` | dict or null | `null` | Joint positions after grasping. Defaults to `approach_positions` if omitted. |
| `bus_serial` | string | `"auto"` | Motor bus serial. |

**Returns:** `success: true/false`, `object_held: true/false`, step-by-step results, camera image.

**Stops early** if any step fails, reporting which step failed in `failed_at`.

```
→ pick_object(
    approach_positions={1: 0.5, 2: 0.3, 3: 0.8, 4: 0.5, 5: 0.6, 6: 0.4, 7: 0.5},
    grasp_positions={1: 0.5, 2: 0.3, 3: 0.9, 4: 0.5, 5: 0.6, 6: 0.4, 7: 0.5}
  )
← {
    "success": true,
    "object_held": true,
    "steps": [
      { "name": "approach", "success": true, ... },
      { "name": "open_gripper", "success": true },
      { "name": "grasp_approach", "success": true, ... },
      { "name": "grasp_verify", "object_detected": true, ... },
      { "name": "lift", "success": true, ... },
      { "name": "lift_grasp_verify", "object_detected": true, ... }
    ],
    "camera": { "image_base64": "...", ... }
  }
```

---

### `place_object`

Full place sequence with verification at every step.

**Sequence:** move to place position → open gripper → verify release → retreat.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `place_positions` | dict | *(required)* | Joint positions where the object should be placed. |
| `retreat_positions` | dict or null | `null` | Joint positions to retract to after placing. Defaults to `place_positions`. |
| `bus_serial` | string | `"auto"` | Motor bus serial. |

**Returns:** `success: true/false`, `object_released: true/false`, step-by-step results, camera image.

```
→ place_object(
    place_positions={1: 0.3, 2: 0.5, 3: 0.9, 4: 0.5, 5: 0.6, 6: 0.4, 7: 0.5},
    retreat_positions={1: 0.3, 2: 0.5, 3: 0.5, 4: 0.5, 5: 0.6, 6: 0.4, 7: 0.5}
  )
← {
    "success": true,
    "object_released": true,
    "steps": [
      { "name": "place_approach", "success": true, ... },
      { "name": "release_verify", "object_released": true, ... },
      { "name": "retreat", "success": true, ... }
    ],
    "camera": { "image_base64": "...", ... }
  }
```

---

## Advanced / Low-level

These tools give raw motor access without arm role labels or safety abstractions. Use them for debugging or when the high-level tools don't cover your use case.

### `advanced_list_motor_buses`

List all ST3215 buses with raw motor register data.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| *(none)* | | | |

---

### `advanced_get_motor_state`

Read one motor by id without arm role labels.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bus_serial` | string | `"auto"` | Motor bus serial. |
| `motor_id` | int | `1` | Motor id to read. |

---

### `advanced_move_motor_normalized`

Move any motor by id to a normalized position (0.0-1.0).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `motor_id` | int | *(required)* | Motor id. |
| `position` | float | *(required)* | Normalized position 0.0-1.0. |
| `bus_serial` | string | `"auto"` | Motor bus serial. |

> Unlike `move_joint`, this can move any motor including the gripper by id.

---

### `advanced_move_motor_steps`

Move any motor to an absolute encoder step position.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `motor_id` | int | *(required)* | Motor id. |
| `goal_steps` | int | *(required)* | Absolute encoder steps (0-4095 on ST3215). Clamped to calibrated range. |
| `bus_serial` | string | `"auto"` | Motor bus serial. |

---

### `advanced_set_motor_torque`

Enable or disable torque on specific motor ids.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `motor_ids` | list[int] | *(required)* | List of motor ids. |
| `enable` | bool | *(required)* | `true` to enable, `false` to disable. |
| `bus_serial` | string | `"auto"` | Motor bus serial. |

---

## Common Workflows

### Observe-Plan-Act-Verify Cycle

The recommended pattern for autonomous robot control:

```
1. get_planning_state              → observe the world
2. (AI agent decides what to do)   → plan
3. move_and_verify / pick_object   → act
4. get_planning_state              → verify outcome, plan next step
```

### Pick and Place

```
1. enable_arm_torque
2. get_planning_state                      → see where the arm is, what's in view
3. pick_object(approach=..., grasp=...)    → pick up the target object
4. place_object(place=..., retreat=...)    → place it at the destination
5. get_planning_state                      → confirm the workspace looks right
```

### Diagnostics

```
1. station_connection_status    → is the station reachable?
2. get_motor_health             → any motor errors or high current?
3. verify_arm_position          → are joints where they should be?
4. capture_image                → what does the camera see?
```

### Recovery After Emergency Stop

```
1. emergency_stop               → arm goes limp
2. (resolve the issue)
3. get_motor_health             → check for errors before re-enabling
4. enable_arm_torque            → re-enable motors
5. get_arm_state                → confirm positions before moving
```

---

## Joint Reference

| Arm Type | Joint Motor IDs | Gripper Motor ID | Total Motors |
|----------|-----------------|------------------|--------------|
| SO-101   | 1, 2, 3, 4, 5  | 6                | 6            |
| ElRobot  | 1, 2, 3, 4, 5, 6, 7 | 8           | 8            |

All positions are **normalized 0.0 to 1.0** within each motor's calibrated range. They are **not** Cartesian XYZ coordinates.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STATION_HOST` | `localhost:8888` | Address of the NormaCore Station TCP server. |
| `DEFAULT_BUS_SERIAL` | *(none)* | Bus serial to use when `bus_serial="auto"` and multiple buses exist. |

---

## Error Reference

| Error | Cause | Fix |
|-------|-------|-----|
| `No ST3215 buses reported` | Station not detecting the robot | Check USB connection, station logs |
| `No st3215/inference frames within Xs` | Station running but not streaming motor data | Verify `st3215.enabled: true` in station.yaml |
| `No inference/normvla frames within Xs` | Camera not connected or torque not enabled | Connect camera, call `enable_arm_torque` |
| `Station did not acknowledge ... within 5s` | Command timed out | Station may be overloaded or disconnected |
| `motor is not calibrated` | Motor range_min and range_max both 0 | Re-calibrate the motor via station |
| `Joint X is not an arm joint` | Tried to move the gripper via `move_joint` | Use `set_gripper` / `open_gripper` / `close_gripper` instead |
| `Bus 'X' not found` | Wrong bus_serial or bus disconnected | Use `advanced_list_motor_buses` to see available buses |

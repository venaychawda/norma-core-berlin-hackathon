# NormaCore Robot Dashboard — Lovable Prompt

Build a modern, single-page React dashboard for controlling a robotic arm. The dashboard connects to a REST API running on a Raspberry Pi. The user enters the API base URL once (e.g. `http://192.168.1.100:8080`) and it's saved in localStorage.

## Design

- **Dark mode** with a soft, eye-soothing color palette: deep charcoal background (`#1a1a2e`), card backgrounds (`#16213e`), accent blue (`#0f3460`), accent teal (`#00b4d8`), success green (`#06d6a0`), warning amber (`#ffd166`), danger red (`#ef476f`), text white (`#e0e0e0`)
- **Modern glassmorphism** cards with subtle backdrop blur and soft borders
- **Smooth animations** on state changes (framer-motion or CSS transitions)
- **Responsive** — works on desktop and tablet
- Use **shadcn/ui** components, **Tailwind CSS**, and **Lucide icons**
- Clean sans-serif font (Inter or system default)

## Layout

Header bar at the top with:
- App title "NormaCore" with a robot icon
- Connection status indicator (green dot = connected, red = disconnected)
- API URL config button (opens a modal to set the base URL)

Below that, a **grid layout with 4 main panels**:

### Panel 1 — Camera Feed (top-left, large)
- Displays the live camera image from the robot's workspace
- Poll `GET /api/camera` every 500ms when connected
- The response has `image_base64` field (JPEG) — display as `<img src="data:image/jpeg;base64,{image_base64}" />`
- Show "No Camera" placeholder with camera-off icon when unavailable
- Show frame age from `frame_age_seconds` as a small badge

### Panel 2 — Robot State (top-right)
- **Arm type** badge (e.g. "ElRobot" or "SO-101") from `GET /api/state` field `arm_type`
- **Joint positions** — vertical list of joints with:
  - Joint label (e.g. "Joint 1", "Joint 2", etc.) from `joints[].role`
  - Horizontal progress bar showing `present_position_normalized` value (0.0 to 1.0)
  - Numeric value displayed next to the bar
  - Color the bar teal for normal, amber if position error > 50 steps
- **Gripper status** — separate section:
  - Visual gripper icon (open/closed/partial based on `gripper.present_position_normalized`)
  - Current draw indicator from `gripper.present_current`
  - Torque on/off badge
- Poll `GET /api/state` every 500ms when connected

### Panel 3 — Control Panel (bottom-left)
Split into tabs:

**Tab 1 — Natural Language Control**
- Large text input: "Tell the robot what to do..."
- "Execute" button that sends the task to `POST /api/vla/step` with body `{"task": "<user text>", "n_steps": 20}`
- Preset quick-action buttons below the input:
  - "Pick up object" → sends `{"task": "move to the object", "n_steps": 30}`
  - "Open Gripper" → `POST /api/gripper/open` with empty body `{}`
  - "Close Gripper" → `POST /api/gripper/close` with empty body `{}`
  - "Home Position" → `POST /api/move/pose` with body `{"joint_positions": {"1": 0.5, "2": 0.5, "3": 0.5, "4": 0.5, "5": 0.5}}`
- Show loading spinner during API calls
- Show result/error as a toast notification

**Tab 2 — Joint Control**
- Slider for each joint (0.0 to 1.0, step 0.01)
- Initialize slider values from current arm state
- "Move" button next to each slider → `POST /api/move/joint` with `{"joint_id": N, "position": value}`
- Gripper slider (0.0 = open, 1.0 = closed) → `POST /api/gripper` with `{"position": value}`

**Tab 3 — System**
- **Enable Torque** button (green) → `POST /api/torque/enable` with body `{}`
- **Disable Torque** button (amber) → `POST /api/torque/disable` with body `{}`
- **EMERGENCY STOP** button (large, red, prominent) → `POST /api/emergency-stop` with body `{}`
- **VLA Status** section:
  - Shows model loaded/not loaded from `GET /api/vla/status` field `model_loaded`
  - If not loaded: text input for checkpoint path + "Load Model" button → `POST /api/vla/load` with `{"checkpoint_path": "..."}`
- **Motor Health** summary from `GET /api/health`:
  - Green checkmark if `healthy` is true
  - List of warnings if any

### Panel 4 — Action Log (bottom-right)
- Scrolling feed showing recent actions from `GET /api/history`
- Poll every 2 seconds
- Each entry shows:
  - Action name (bold)
  - Timestamp (relative, e.g. "5s ago")
  - Success/failure badge (green/red)
  - Expandable details (params)
- Auto-scroll to latest entry
- Max 20 entries visible

## API Reference

All endpoints are relative to the configurable base URL. All POST endpoints accept JSON body with `Content-Type: application/json`.

### GET endpoints
| Endpoint | Returns | Key fields |
|----------|---------|------------|
| `/api/connection` | Connection status | `connected`, `frame_count`, `uptime_seconds` |
| `/api/state` | Arm state | `arm_type`, `joints[]` (each has `motor_id`, `role`, `present_position_normalized`, `torque_enabled`), `gripper` |
| `/api/camera` | Camera image | `image_base64` (JPEG), `frame_age_seconds` |
| `/api/health` | Motor health | `healthy`, `warnings[]`, `motors[]` |
| `/api/history` | Action log | Array of `{action, params, success, timestamp}` |
| `/api/vla/status` | VLA model info | `model_loaded`, `smolvla_available`, `checkpoint_path` |
| `/api/buses` | Bus list | Array of `{serial, motor_count, motors[]}` |

### POST endpoints
| Endpoint | Body | Returns |
|----------|------|---------|
| `/api/move/joint` | `{joint_id: int, position: float}` | Move result |
| `/api/move/pose` | `{joint_positions: {id: pos, ...}}` | Move result |
| `/api/gripper` | `{position: float}` | Gripper state |
| `/api/gripper/open` | `{}` | Gripper state |
| `/api/gripper/close` | `{}` | Gripper state |
| `/api/torque/enable` | `{}` | Torque result |
| `/api/torque/disable` | `{}` | Torque result |
| `/api/emergency-stop` | `{}` | Stop result |
| `/api/vla/step` | `{task: string, n_steps?: int}` | VLA result with ticks |
| `/api/vla/load` | `{checkpoint_path: string}` | Model status |

### Error responses
All errors return `{"error": "message"}` with appropriate HTTP status codes (400, 404, 500, 502, 504).

## Technical Notes

- Use `fetch()` for API calls — no axios needed
- Handle CORS — the API has `Access-Control-Allow-Origin: *`
- Store the API base URL in `localStorage` under key `normacore_api_url`
- On first load, show a setup modal asking for the API URL
- Add a connection check on startup: `GET /api/connection` — if it fails, show a "Disconnected" banner
- All polling should stop when the tab is not visible (use `document.hidden`)
- Add error boundaries so one failed panel doesn't crash the whole app

# NormaCore Station — Robot Connection & MCP Setup

Step-by-step guide to connect an ST3215 robot arm to a Raspberry Pi 5, verify it works, and control it from Claude Code / Cursor via MCP.

Tested on **Raspberry Pi 5** (Debian Trixie, aarch64) with **SO-101** arms (5 joints + gripper on motor 6).

---

## Prerequisites

- Raspberry Pi 5 running Debian/Raspberry Pi OS (64-bit)
- Robot connected via USB **and powered on** (ST3215 servos need external 6-8V power to respond — USB alone only powers the controller board)
- User in the `dialout` group for serial access:

```bash
# Check membership
groups $USER | grep dialout

# Add if missing (reboot required after)
sudo usermod -aG dialout $USER
```

- [uv](https://docs.astral.sh/uv/) installed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

- Generated protobufs (from repo root):

```bash
make protobuf
```

---

## 1. Connect the robot

Plug the robot into the Pi over USB. Confirm Linux sees the serial port:

```bash
ls /dev/ttyACM* /dev/ttyUSB*
```

You should see something like `/dev/ttyACM0`. To identify the device:

```bash
ls /dev/serial/by-id/
```

This shows the serial number, e.g. `usb-1a86_USB_Single_Serial_5B3E089716-if00`.

For **multiple robots**, each gets its own `/dev/ttyACM*` device (e.g. `ttyACM0` and `ttyACM1`). The station auto-discovers all of them.

---

## 2. Start NormaCore Station

Station bridges the USB motors to a TCP API on port **8888**. The MCP server talks to that port.

### Option A — Prebuilt binary (recommended)

Download the Linux ARM64 release binary:

```bash
mkdir -p .tmp/station && cd .tmp/station

curl -L -o station-linux-arm64.tar.gz \
  "https://github.com/norma-core/norma-core/releases/download/v0.1.0-beta.8/station-linux-arm64.tar.gz"

tar -xzf station-linux-arm64.tar.gz
cp ../../software/station/bin/station/station.yaml .
```

Start station with TCP and web UI:

```bash
RUST_LOG=info ./station --tcp --web --config station.yaml
```

Leave this terminal running.

### Option B — Build from source

```bash
cd software/station/bin/station
make client          # builds web UI assets (required)
cargo build --release
./../../../../target/release/station --tcp --web
```

---

## 3. Verify the connection

### Web UI

Open **http://localhost:8889** (or `http://<pi-ip>:8889` from another machine) in your browser. You should see the arm with live motor data.

### Station logs

In the station terminal, look for:

```
Successfully opened ST3215 port: /dev/ttyACM0
Detected new ST3215 motor ID on port: ... 1
Detected new ST3215 motor ID on port: ... 2
...
NormFS server listening on 0.0.0.0:8888
```

For an SO-101 you should see **6 motors** (joints 1-5, gripper 6). For an ElRobot you should see **8 motors** (joints 1-7, gripper 8).

### Python connection test

From the repo root:

```bash
uv run --project software/station/mcp python -c "
import asyncio, json
from norma_station_mcp.session import StationSession

async def main():
    s = StationSession('localhost:8888')
    await s.ensure_connected()
    await s.wait_for_inference(timeout_s=15.0)
    info = s.connection_info()
    info['bus_count'] = len(s.list_buses())
    state = s.get_arm_state()
    print(json.dumps(info, indent=2))
    print(json.dumps({
        'arm_type': state['arm_type'],
        'arm_label': state['arm_label'],
        'bus_serial': state['bus_serial'],
        'joint_count': len(state['joints']),
        'joint_ids': [j['motor_id'] for j in state['joints']],
        'gripper_motor_id': state['gripper_motor_id'],
    }, indent=2))

asyncio.run(main())
"
```

Expected output:

```json
{
  "host": "localhost:8888",
  "connected": true,
  "setup_done": true,
  "has_latest_inference": true,
  "bus_count": 1
}
```

---

## 4. Enable MCP in Claude Code / Cursor

### Claude Code

Add to your Claude Code MCP config (`~/.claude.json` or project `.claude/settings.json`):

```json
{
  "mcpServers": {
    "norma-station": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "software/station/mcp",
        "python",
        "-m",
        "norma_station_mcp"
      ],
      "env": {
        "STATION_HOST": "localhost:8888",
        "DEFAULT_BUS_SERIAL": "5B3E089716"
      }
    }
  }
}
```

### Cursor

The project includes `.cursor/mcp.json` with the same configuration. Reload MCP servers in Cursor (Settings > MCP > refresh, or restart Cursor).

### Remote access

If the Pi runs the station and you connect from another machine, change `STATION_HOST` to the Pi's IP:

```json
"STATION_HOST": "192.168.1.100:8888"
```

### Multiple robots

When multiple robots are connected, each appears as a separate bus with its own serial number. Set `DEFAULT_BUS_SERIAL` to the one you want as default, or pass `bus_serial` explicitly in each MCP tool call.

---

## 5. Control the robot

Recommended order:

1. **`get_arm_state`** — read current joint and gripper positions (start here).
2. **`enable_arm_torque`** — power motors so the arm holds position.
3. **`move_joint`** / **`move_arm_pose`** — move joints (values 0.0-1.0, normalized per motor).
4. **`open_gripper`** / **`close_gripper`** / **`set_gripper`** — gripper control.
5. **`disable_arm_torque`** — release the arm (use with care).

### Joint reference

| Arm | Joints | Gripper |
|-----|--------|---------|
| SO-101 | motors 1-5 | motor 6 |
| ElRobot | motors 1-7 | motor 8 |

Positions are **normalized 0.0-1.0** within each motor's calibrated range, not Cartesian XYZ.

---

## 6. Stop station

In the terminal where station is running, press **Ctrl+C**.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Nothing listening on 8888` | Start station with `--tcp` (step 2). |
| No `/dev/ttyACM*` device | Replug USB cable; try a different port. Check `dmesg \| tail` for USB errors. |
| Port opens but no motors detected | Robot power supply must be on. ST3215 servos need external 6-8V — USB alone only powers the controller board. |
| `Permission denied: /dev/ttyACM0` | Add user to dialout group: `sudo usermod -aG dialout $USER` then reboot. |
| `No st3215/inference frames` | Confirm `st3215.enabled: true` in `station.yaml`; check station logs for port errors. |
| `Skip: no_bus (torque=false)` | The normvla inference stream requires torque enabled on at least one motor. Run `enable_arm_torque` first. |
| MCP tools fail to connect | Station must be running first; reload MCP in Claude Code / Cursor. |
| `Missing generated protobufs` | Run `make protobuf` from repo root. |
| Arm detected but won't move | Run `enable_arm_torque` before sending move commands. |
| USB EMI disconnects (`disabled by hub (EMI?)`) | Use a shorter/shielded USB cable, or a powered USB hub. |
| Build fails on `Asset::get` | Run `make client` in `software/station/bin/station` before `cargo build`. |

---

## Quick reference

```bash
# Repo root
make protobuf

# Check USB devices
ls /dev/ttyACM* /dev/serial/by-id/

# Start station (prebuilt)
cd .tmp/station && RUST_LOG=info ./station --tcp --web --config station.yaml

# Test connection
uv run --project software/station/mcp python -c "..."   # see step 3

# Web UI (local)
xdg-open http://localhost:8889

# Web UI (from another machine)
# http://<pi-ip>:8889
```

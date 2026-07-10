# NormaCore — Engineering Task Backlog

Prioritized bottleneck fixes and improvements from the Berlin hackathon.
Merged from the P0–P3 bottleneck analysis (compiled 2026-06-29) with
`Presentation_Files/07_Challenges_and_Learnings.md` and `08_Future_Roadmap.md`.

Priority key: **P0** blocks every session · **P1** daily friction · **P2** faster iteration · **P3** scale/roadmap.
Status key: ☐ todo · ◐ partial · ☑ done.

---

## Priority Table

| Priority | Task | Impact | Effort | Status |
|---|---|---|---|---|
| P0 | Calibration reliability + validation | Blocks everything | Medium | ◐ |
| P0 | USB permission persistence (udev) | Blocks every reboot | Low | ◐ |
| P1 | Dataset tagging UI | Blocks clean training data | Medium | ◐ |
| P1 | Local training support (CUDA/MPS) | Removes Colab dependency | Low | ☐ |
| P1 | Single startup script | Daily friction | Low | ☐ |
| P2 | Episode review + quality scoring | Better data quality | Medium | ☐ |
| P2 | Checkpoint versioning + OTA deploy | Faster iteration | Medium | ☐ |
| P2 | Observability dashboard | Faster debugging | Medium | ◐ |
| P3 | Data augmentation pipeline | Reduces teleop burden | High | ☐ |
| P3 | Sim-to-real bootstrapping | Reduces teleop burden | High | ☐ |

---

## P0 — Blocks Every Session

### 1. Calibration Reliability + Validation  ◐
EEPROM writes fail silently and corrupt motor ranges (`range_min == range_max`);
no rollback, must recalibrate from scratch. Also root cause of the 6x
leader→follower amplification (leader motor 2: 340 steps vs follower: 2176).

- [x] Nuclear recovery documented (delete `station_data`, power-cycle, recalibrate)
- [x] Manual fix scripts to write matching ranges (raw sync-write, hardcoded)
- [ ] Pre-write EEPROM validation (verify before commit)
- [ ] Post-write read-back / verify that value stuck (silent-corruption guard)
- [ ] Calibration snapshot / restore to JSON (rollback support)
- [ ] Motor range health check — flag any range < 500 steps
- [ ] GUI wizard with per-motor calibration status

_Related: `software/station/mcp/calibrate_follower.py`, `calibrate_leader_fix.py` (uncommitted)._
_Both are one-shot raw sync-write scripts with hardcoded bus serials + ranges and no read-back — the manual remediation, not reliability infra._

### 2. USB Permission Persistence (udev)  ◐
Station uses raw USB (libuvc, not V4L2); camera perms reset on every reboot and
bus/device numbers change, so paths can't be hardcoded.

- [x] Manual workaround: `sudo chmod 666 /dev/bus/usb/XXX/YYY` after reboot
- [ ] Persistent udev rules keyed on vendor:product ID
- [ ] Fix station so it doesn't require sudo
- [ ] systemd service that sets permissions at startup

---

## P1 — Daily Friction

### 3. Dataset Tagging UI  ◐
No UI for tagging episode start/stop; identifying freeze frames is manual.
Frame-gap discards killed 10 of 22 recordings (>500ms gaps from USB bandwidth).

- [x] Tag-based recording + `list_tags.py` automation
- [ ] Web episode editor: video scrubber + keyboard shortcuts
- [ ] Auto-detect episode boundaries via motor-velocity threshold
- [ ] Batch tagging workflow
- [ ] Camera-stability check before recording (prevent frame-gap discards)

### 4. Local Training Support (CUDA / MPS)  ☐
Colab session timeouts + parquet/checkpoint upload-download friction.

- [ ] Document + support NVIDIA Windows CUDA target (`train.py --device cuda`)
- [ ] Document + support Apple Silicon MPS target (`train.py --device mps`)
- [ ] Checkpoint versioning with rollback

### 5. Single Startup Script  ☐
Station startup is a multi-step manual process (ports 8888, 8889, 8080).

- [ ] One systemd service / startup script for all layers
- [ ] Health check validating each layer before declaring ready

---

## P2 — Faster Iteration

### 6. Episode Review + Quality Scoring  ☐
- [ ] Live quality score during teleop (smoothness, velocity variance)
- [ ] Episode playback with accept/reject before committing to dataset

### 7. Checkpoint Versioning + OTA Deploy  ☐
- [ ] OTA deploy command (training machine → Pi)
- [ ] Checkpoint registry with task + arm + workspace metadata
- [ ] A/B testing mode
- [ ] Action-chunking optimization — execute full 50-step chunks for real-time control

### 8. Observability Dashboard  ◐
- [x] Lovable dashboard (React) with N8N demo/training/alerts panels
- [ ] Live view: camera + motor positions + inference confidence + MCP call log
- [ ] Structured logging tied to episode IDs
- [ ] Failure detection (dropped objects, silent inference failures)
- [ ] Package dashboard as Electron app or serve from Pi

---

## P3 — Scale & Roadmap

### 9. Data Augmentation Pipeline  ☐
- [ ] Background randomization, color jitter, lighting variation

### 10. Sim-to-Real Bootstrapping  ☐
- [ ] Generate synthetic demos in MuJoCo (URDF provided) to bootstrap training

---

## Standing Blocker — SmolVLA Checkpoint
`vla_step` has no model until a checkpoint is fine-tuned on THIS arm + workspace.
Pipeline: teleop demos → export parquet → train 5K steps → scp to Pi → `vla_load_model` + `vla_step`.

- [ ] Complete 50-episode recording (38 more demos needed)
- [ ] Train checkpoint (batch 32, 5000 steps, lr 1e-4, base `lerobot/smolvla_base`)
- [ ] Deploy + live inference test

---

## Hardware Upgrade Path (roadmap)
| Current | Upgrade | Benefit |
|---|---|---|
| Pi 5 (CPU only) | + Hailo-10H PCIe | 26 TOPS vision-encoder offload |
| 224x224 cameras | 640x480 stereo | Better object discrimination |
| SD card (29GB) | NVMe SSD | Larger datasets, faster I/O |
| Single workspace | Multiple cameras | Wider manipulation boundary |

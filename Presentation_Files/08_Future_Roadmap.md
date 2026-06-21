# Future Roadmap

## Immediate Next Steps (Post-Hackathon)

1. **Complete 50 episode recording** — 38 more demos needed for standard fine-tuning quality
2. **Deploy trained checkpoint** — Colab training → scp to Pi → live inference
3. **Action chunking optimization** — execute full 50-step chunks for real-time control
4. **Hailo-10H NPU integration** — offload SigLIP vision encoder to 26 TOPS accelerator

## Short-Term (1-2 weeks)

| Goal | Approach |
|---|---|
| Multi-task model | Record stacking, sorting, placing demos; train unified model |
| ACT fallback | 52M param model, 182ms inference — deploy if SmolVLA too slow |
| Permanent camera permissions | udev rules for USB cameras |
| Dashboard deployment | Package Lovable dashboard as Electron app or serve from Pi |

## Medium-Term (1-2 months)

| Goal | Approach |
|---|---|
| Sim-to-real | Train in MuJoCo (URDF provided), transfer to hardware |
| Multi-robot | Scale to 2+ arms with shared station daemon |
| Voice control | Integrate whisper → Claude → MCP pipeline |
| Continuous learning | Auto-record successful demos, periodic retraining |

## Long-Term Vision

A platform where:
- Non-experts teach robots new tasks by showing, not programming
- Robots learn incrementally from every demonstration
- The AI agent handles error recovery and re-planning autonomously
- Fleet of arms share learned skills via a common model hub

## Hardware Upgrade Path

| Current | Upgrade | Benefit |
|---|---|---|
| Pi 5 (CPU only) | + Hailo-10H PCIe | 26 TOPS vision encoder offload |
| 224x224 cameras | 640x480 stereo | Better object discrimination |
| SD card (29GB) | NVMe SSD | Larger datasets, faster I/O |
| Single workspace | Multiple cameras | Wider manipulation boundary |

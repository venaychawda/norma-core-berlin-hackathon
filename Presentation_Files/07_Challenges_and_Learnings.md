# Challenges and Learnings

## Technical Challenges Overcome

### 1. EEPROM Calibration Failures
**Problem:** ST3215 servo EEPROM writes failed silently, corrupting motor ranges.  
**Solution:** Used Station Web UI auto-calibration instead of raw sync-write commands. Nuclear recovery: delete `station_data`, power cycle servos, recalibrate from scratch.

### 2. Leader-Follower Sensitivity (6x Amplification)
**Problem:** Small leader movements caused huge follower movements.  
**Root cause:** Calibration range mismatch — leader motor 2 had 340 steps vs follower's 2176 steps.  
**Solution:** Recalibrated leader to match follower ranges. Wrote diagnostic script to compare ranges.

### 3. Disk Space on Pi 5 (29GB SD card)
**Problem:** SmolVLA model (865MB) + torch (4.7GB) + station_data (8GB) filled the disk.  
**Solution:** Systematic cleanup — cleared pip/uv caches, trimmed station_data queues after parquet export. Freed 7.7GB.

### 4. N8N Docker Gotchas on Pi 5
**Problem:** `host.docker.internal` doesn't resolve, `executeCommand` node unavailable, secure cookie blocks access.  
**Solution:** Hardcode Pi IP in workflows, use HTTP request nodes instead of shell exec, disable secure cookie.

### 5. Action Space Mismatch (6 vs 8 DOF)
**Problem:** Pre-trained SO-101 models expect 6 joints, ElRobot has 8.  
**Solution:** Joint mapping (motors 1,2,3,4,7,8 → SO-101 joints 0-5) for zero-shot testing. Fine-tuning natively on 8 joints for production.

### 6. Camera USB Permissions After Reboot
**Problem:** Station uses raw USB (libuvc), not V4L2. Permissions reset on reboot.  
**Solution:** `sudo chmod 666 /dev/bus/usb/XXX/YYY` after each reboot. Udev rule for permanent fix.

### 7. Frame Gap Discards in Dataset Export
**Problem:** 10 of 22 recordings were discarded due to "frame gap > 500ms".  
**Root cause:** Camera dropped frames during recording (USB bandwidth sharing).  
**Learning:** Ensure camera is stable before starting teleoperation recording.

## Key Learnings

1. **Collect demos natively** — converting between 6-DOF and 8-DOF datasets adds complexity and degrades quality. Always record on the target hardware.

2. **50 episodes is the magic number** — community standard across 16K+ LeRobot datasets. More helps but has diminishing returns.

3. **Pre-trained models work** — zero-shot predictions from LBST were coherent even on a different robot. Transfer learning is real.

4. **Action chunking is essential** — 24s per single-step inference is unusable, but predicting 50 steps at once (2s) and executing the chunk over 3s is workable.

5. **Tag-based recording** is much better than manual frame number tracking — the list_tags.py script automates what would be tedious manual work.

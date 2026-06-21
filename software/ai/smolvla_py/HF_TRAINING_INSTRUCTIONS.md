# HuggingFace Training Instructions

## Quick Start (3 commands)

### Step 1: Login to HuggingFace
```bash
cd software/ai/smolvla_py
.venv/bin/huggingface-cli login
# Paste your write token from https://huggingface.co/settings/tokens
```

### Step 2: Upload Dataset
```bash
.venv/bin/python scripts/upload_dataset_hf.py \
    --repo-id venaychawda/elrobot-pickplace
```
This uploads your 12 parquets (124 MB) as a HF dataset.

### Step 3: Train on HF (two options)

#### Option A: HF Space with L4 GPU ($0.80/hr, ~20 min = ~$0.27)

1. Go to https://huggingface.co/new-space
2. Create a Space with:
   - Name: `elrobot-training`
   - SDK: Docker
   - Hardware: Nvidia L4
3. Upload the files from `hf_training_space/` directory
4. Add these secrets in Space settings:
   - `HF_TOKEN` = your write token
   - `DATASET_REPO` = `venaychawda/elrobot-pickplace`
   - `OUTPUT_REPO` = `venaychawda/elrobot-smolvla-pickplace`
5. The Space auto-runs training on startup

#### Option B: Run training script from any GPU machine
```bash
# On any machine with a GPU (Colab, Paperspace, Lambda, etc.)
pip install uv && uv sync
uv run python scripts/train_hf_space.py \
    --dataset-repo venaychawda/elrobot-pickplace \
    --output-repo venaychawda/elrobot-smolvla-pickplace \
    --steps 5000 --batch-size 32
```
The script downloads data from HF Hub, trains, and pushes the checkpoint back.

---

## After Training: Deploy to Pi 5

```bash
# On Pi 5
cd software/ai/smolvla_py
.venv/bin/python -c "
from huggingface_hub import snapshot_download
snapshot_download('venaychawda/elrobot-smolvla-pickplace', 
                  local_dir='../../checkpoints/elrobot-trained')
"

# Test inference
.venv/bin/python scripts/run_policy.py \
    --checkpoint ../../checkpoints/elrobot-trained \
    --task "pick up the block" \
    --bus-serial 5B61037157 \
    --motor-ids 1,2,3,4,5,6,7,8
```

---

## Timeline Estimate

| Step | Time | Cost |
|---|---|---|
| Upload dataset | 2 min | Free |
| Training (L4) | ~20 min | ~$0.27 |
| Download checkpoint to Pi | 3 min | Free |
| **Total** | **~25 min** | **~$0.27** |

vs Google Colab: 60+ min with timeout risk, free but unreliable.

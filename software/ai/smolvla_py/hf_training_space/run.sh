#!/bin/bash
set -e

echo "=== ElRobot SmolVLA Training ==="
echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo 'none')"
echo "Dataset: ${DATASET_REPO:-venaychawda/elrobot-pickplace}"
echo "Output: ${OUTPUT_REPO:-venaychawda/elrobot-smolvla-pickplace}"
echo "Steps: ${STEPS:-5000}"
echo ""

uv run python scripts/train_hf_space.py \
    --dataset-repo "${DATASET_REPO:-venaychawda/elrobot-pickplace}" \
    --output-repo "${OUTPUT_REPO:-venaychawda/elrobot-smolvla-pickplace}" \
    --base-checkpoint "${BASE_CHECKPOINT:-LBST/t01_pick_and_place}" \
    --steps "${STEPS:-5000}" \
    --batch-size "${BATCH_SIZE:-32}" \
    --save-every 500

echo ""
echo "=== Training Complete ==="
echo "Checkpoint at: https://huggingface.co/${OUTPUT_REPO:-venaychawda/elrobot-smolvla-pickplace}"

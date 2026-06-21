"""Entry point for HF Space: starts health server then trains."""
import http.server
import socketserver
import subprocess
import threading
import time

# Start health check server immediately
handler = http.server.SimpleHTTPRequestHandler
server = socketserver.TCPServer(("0.0.0.0", 7860), handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
print("Health check server running on port 7860", flush=True)

time.sleep(2)

# Run training
print("Starting training...", flush=True)
r = subprocess.run(
    ["uv", "run", "python", "scripts/train_elrobot.py",
     "--parquets", "datasets/pick-up-block.parquet", "datasets/pick-up-block1.parquet",
     "datasets/pick-up-block2.parquet", "datasets/pick-up-block3.parquet",
     "datasets/pick-up-bottle-cap2.parquet", "datasets/pick-up-pen.parquet",
     "datasets/pick-up-pen1.parquet", "datasets/pick-up-put-down-block2.parquet",
     "datasets/push-block-forward.parquet", "datasets/push-block-forward1.parquet",
     "datasets/push-block-forward2.parquet", "datasets/push-block-forward3.parquet",
     "--base-checkpoint", "LBST/t01_pick_and_place",
     "--steps", "5000", "--batch-size", "8",
     "--output", "checkpoints/elrobot-run"],
)

if r.returncode != 0:
    print(f"Training failed with code {r.returncode}", flush=True)
else:
    print("Training complete. Pushing to HF Hub...", flush=True)
    subprocess.run(
        ["uv", "run", "python", "-c",
         "from huggingface_hub import HfApi,create_repo;"
         "create_repo('venayc/elrobot-smolvla-pickplace',exist_ok=True);"
         "HfApi().upload_folder(repo_id='venayc/elrobot-smolvla-pickplace',"
         "folder_path='checkpoints/elrobot-run/final');"
         "print('PUSHED to https://huggingface.co/venayc/elrobot-smolvla-pickplace')"],
    )

print("DONE. Sleeping to keep Space alive.", flush=True)
time.sleep(86400)

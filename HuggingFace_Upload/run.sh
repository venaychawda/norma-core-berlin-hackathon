#!/bin/bash

# Start dummy HTTP server on port 7860 so HF health check passes
python -c "
import http.server, socketserver, threading

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'<h1>ElRobot Training Running...</h1>')

server = socketserver.TCPServer(('0.0.0.0', 7860), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
print('Health check server started on port 7860')
" &

sleep 2
echo "=== ElRobot SmolVLA Training ==="
echo "Starting training..."

# Run training
uv run python scripts/train_elrobot.py \
    --parquets datasets/*.parquet \
    --base-checkpoint LBST/t01_pick_and_place \
    --steps 5000 --batch-size 8 \
    --output checkpoints/elrobot-run

echo "=== Training Complete ==="
echo "Pushing checkpoint to HF Hub..."

# Push checkpoint to HF Hub
uv run python -c "
from huggingface_hub import HfApi, create_repo
create_repo('venayc/elrobot-smolvla-pickplace', exist_ok=True)
HfApi().upload_folder(repo_id='venayc/elrobot-smolvla-pickplace', folder_path='checkpoints/elrobot-run/final')
print('SUCCESS: Pushed to https://huggingface.co/venayc/elrobot-smolvla-pickplace')
"

echo "=== ALL DONE ==="
echo "Model available at: https://huggingface.co/venayc/elrobot-smolvla-pickplace"

# Keep container alive so Space doesn't restart
sleep 86400

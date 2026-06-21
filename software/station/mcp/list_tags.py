"""List all inference tags with their frame numbers from the station.

Usage:
    .venv/bin/python list_tags.py
    .venv/bin/python list_tags.py --csv   # output as CSV for pasting into training_tasks.csv
"""

import asyncio
import logging
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "station" / "shared"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from station_py import new_station_client

from target.gen_python.protobuf.station import inference_tags


TAGS_QUEUE = "inference-tags/rx"
MAX_TAGS = 1000


def frame_from_bytes(b: bytes) -> int:
    if len(b) == 0:
        return 0
    if len(b) <= 8:
        return int.from_bytes(b, byteorder="little")
    return int.from_bytes(b[:8], byteorder="little")


async def main():
    csv_mode = "--csv" in sys.argv

    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger("list-tags")

    client = await new_station_client("localhost", logger)

    offset = MAX_TAGS.to_bytes(8, byteorder="little")
    qr = client.read_from_tail(TAGS_QUEUE, offset, limit=MAX_TAGS, step=1, buf_size=100)

    tags = []
    while True:
        entry = await qr.data.get()
        if entry is None:
            break
        try:
            envelope = inference_tags.RxEnvelopeReader(entry.Data)
            tag_name = envelope.get_tag()
            frame = frame_from_bytes(envelope.get_inference_queue_ptr())
            tag_type = envelope.get_type()
            removed = tag_type == inference_tags.CommandType.CT_REMOVE_TAG
            if not removed and tag_name:
                tags.append((tag_name, frame))
        except Exception as e:
            print(f"Warning: failed to decode tag entry: {e}", file=sys.stderr)

    if not tags:
        print("No tags found.")
        return

    if csv_mode:
        print("tag_name,frame_number")
        for name, frame in tags:
            print(f"{name},{frame}")
    else:
        print(f"{'Tag Name':<40} {'Frame Number':>15}")
        print("-" * 57)
        for name, frame in tags:
            print(f"{name:<40} {frame:>15}")
        print(f"\nTotal: {len(tags)} tags")


if __name__ == "__main__":
    asyncio.run(main())

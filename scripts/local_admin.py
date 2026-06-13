from __future__ import annotations

import argparse
import json

from app.config import get_settings
from app.queue_store import QueueStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Local-only print server administration")
    parser.add_argument("command", choices=["status", "pause", "resume"])
    parser.add_argument("--reason", default="本机命令行手动暂停")
    args = parser.parse_args()

    settings = get_settings()
    store = QueueStore(settings.database_path)
    store.initialize()

    if args.command == "pause":
        state = store.set_paused(True, args.reason)
    elif args.command == "resume":
        state = store.set_paused(False, None)
    else:
        state = store.get_state()

    print(json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

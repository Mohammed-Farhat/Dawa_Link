"""The worker container's health check: python -m dawalink.worker.alive (exit 0 = alive)."""

import sys

from dawalink.config import load_settings
from dawalink.worker.heartbeat import is_alive


def main() -> None:
    sys.exit(0 if is_alive(load_settings().worker_heartbeat_file) else 1)


if __name__ == "__main__":
    main()

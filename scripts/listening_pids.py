"""Print Linux process IDs listening on a TCP port without external utilities."""
from __future__ import annotations

import argparse
from pathlib import Path


def listening_socket_inodes(port: int, proc_root: Path = Path("/proc")) -> set[str]:
    expected_port = f"{port:04X}"
    inodes: set[str] = set()
    for name in ("tcp", "tcp6"):
        table = proc_root / "net" / name
        try:
            lines = table.read_text(encoding="ascii").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            columns = line.split()
            if len(columns) < 10:
                continue
            local_address = columns[1]
            state = columns[3]
            if state == "0A" and local_address.rsplit(":", 1)[-1].upper() == expected_port:
                inodes.add(columns[9])
    return inodes


def listening_pids(port: int, proc_root: Path = Path("/proc")) -> list[int]:
    inodes = listening_socket_inodes(port, proc_root)
    if not inodes:
        return []
    targets = {f"socket:[{inode}]" for inode in inodes}
    process_ids: set[int] = set()
    for process_dir in proc_root.glob("[0-9]*"):
        try:
            process_id = int(process_dir.name)
        except ValueError:
            continue
        try:
            descriptors = (process_dir / "fd").iterdir()
            if any(descriptor.readlink().as_posix() in targets for descriptor in descriptors):
                process_ids.add(process_id)
        except (OSError, PermissionError):
            continue
    return sorted(process_ids)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("port", type=int)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    for process_id in listening_pids(args.port):
        print(process_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

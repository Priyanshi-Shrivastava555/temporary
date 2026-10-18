from pathlib import Path

from scripts.listening_pids import listening_pids, listening_socket_inodes


def write_tcp_table(proc_root: Path, *rows: str) -> None:
    network = proc_root / "net"
    network.mkdir(parents=True, exist_ok=True)
    header = "sl local_address rem_address st tx_queue:rx_queue tr tm->when retrnsmt uid timeout inode"
    (network / "tcp").write_text("\n".join((header, *rows)), encoding="ascii")


def test_finds_only_listening_socket_on_requested_port(tmp_path):
    write_tcp_table(
        tmp_path,
        "0: 0100007F:1EB4 00000000:0000 0A 0:0 00:0 0 1000 0 54321",
        "1: 0100007F:1F40 00000000:0000 0A 0:0 00:0 0 1000 0 99999",
        "2: 0100007F:1EB4 00000000:0000 01 0:0 00:0 0 1000 0 77777",
    )

    assert listening_socket_inodes(7860, tmp_path) == {"54321"}


def test_maps_listener_inode_to_process_id(tmp_path, monkeypatch):
    write_tcp_table(tmp_path, "0: 0100007F:1EB4 00000000:0000 0A 0:0 00:0 0 1000 0 54321")
    descriptor = tmp_path / "1234" / "fd" / "7"
    descriptor.parent.mkdir(parents=True)
    descriptor.touch()
    original_readlink = Path.readlink

    def fake_readlink(path: Path) -> Path:
        if path == descriptor:
            return Path("socket:[54321]")
        return original_readlink(path)

    monkeypatch.setattr(Path, "readlink", fake_readlink)

    assert listening_pids(7860, tmp_path) == [1234]

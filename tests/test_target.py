from pathlib import Path
import hashlib
import struct

ROOT = Path(__file__).resolve().parents[1]
EXE_SHA = "917d14e7ef7ce492b665fea7d0c87c9a39b549e2a43b09883d2a786988e7c02c"


def test_pinned_exe_if_present():
    exe = ROOT / "original/retail/MXReflex.exe"
    if not exe.exists():
        return
    data = exe.read_bytes()
    assert hashlib.sha256(data).hexdigest() == EXE_SHA
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe:pe + 4] == b"PE\0\0"
    assert struct.unpack_from("<H", data, pe + 4)[0] == 0x14C
    opt = pe + 24
    assert struct.unpack_from("<H", data, opt)[0] == 0x10B
    base = struct.unpack_from("<I", data, opt + 28)[0]
    entry = struct.unpack_from("<I", data, opt + 16)[0]
    assert base == 0x00400000
    assert base + entry == 0x009006A7


def test_sentinels_stay_in_reserved_padding():
    sentinels = [
        0x00DCFE00, 0x00DCFE10, 0x00DCFE14, 0x00DCFE18,
        0x00DCFE20, 0x00DCFE24, 0x00DCFE30, 0x00DCFE34,
        0x00DCFE40, 0x00DCFE44, 0x00DCFE48, 0x00DCFE50,
        0x00DCFE60, 0x00DCFE64, 0x00DCFE70,
    ]
    assert all(0x00DCF76C <= address < 0x00DD0000 for address in sentinels)
    assert max(sentinels) < 0x01000000

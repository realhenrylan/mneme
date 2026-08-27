"""P1.1-E 采集期巡检命令契约：只读、零内容泄露、篡改非零退出。

owner 锁定 ``PATROL_INTERVAL = every_50_traces``：巡检只看完整性结论
（计数 / verify_integrity / 磁盘占用），不看语义、不改策略、不打印任何
事件内容。退出码约定：0 = 全部通过（含零 trace）、1 = 存在完整性失败、
2 = 用法/路径非法（含仓库内 root 被防泄漏守卫拒绝）。
"""
import hashlib
import json
import os
from pathlib import Path

from src import production_observability as obs
from src.production_observability import ConsentLevel, TraceStore, main


def _repo_root() -> Path:
    return Path(obs.__file__).resolve().parents[1]


def _seed_traces(root: Path, count: int) -> list[str]:
    """经产品同一封存路径合法生成 count 条完整 trace。"""
    store = TraceStore(root)
    assert store.set_consent(ConsentLevel.MINIMAL, confirmed=True) is True
    ids: list[str] = []
    for i in range(count):
        trace_id = store.begin_trace("sync", 20)
        store.emit_sensitive("rewrite.decided", f"P11E_SECRET_MARKER_{i}",
                             trace_id=trace_id)
        assert store.finish_trace(trace_id) is True
        ids.append(trace_id)
    return ids


def _tree_snapshot(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            path = Path(dirpath) / filename
            key = path.relative_to(root).as_posix()
            snapshot[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def test_patrol_reports_count_integrity_bytes(tmp_path, capsys):
    root = tmp_path / "traces"
    _seed_traces(root, 2)
    before = _tree_snapshot(root)

    code = main(["patrol", "--root", str(root)])
    out = capsys.readouterr().out

    assert code == 0
    report = json.loads(out)
    assert report["trace_count"] == 2
    assert report["verified"] == 2
    assert report["failed"] == []
    assert report["total_bytes"] > 0
    assert report["integrity"] == "ok"
    assert "P11E_SECRET_MARKER" not in out, "巡检输出不得包含任何事件内容"
    assert _tree_snapshot(root) == before, "巡检必须严格只读"


def test_patrol_nonzero_exit_on_tampered_trace(tmp_path, capsys):
    root = tmp_path / "traces"
    ids = _seed_traces(root, 1)
    segment = root / f"{ids[0]}.jsonl"
    segment.write_bytes(segment.read_bytes() + b"\x00")

    code = main(["patrol", "--root", str(root)])
    out = capsys.readouterr().out

    assert code != 0
    report = json.loads(out)
    assert report["integrity"] == "failed"
    assert any(item["trace_id"] == ids[0] for item in report["failed"])
    assert "P11E_SECRET_MARKER" not in out


def test_patrol_graceful_with_zero_traces(tmp_path, capsys):
    root = tmp_path / "not_yet_created" / "traces"

    code = main(["patrol", "--root", str(root)])
    out = capsys.readouterr().out

    assert code == 0
    report = json.loads(out)
    assert report["trace_count"] == 0
    assert report["integrity"] == "ok"


def test_patrol_refuses_root_inside_repo(capsys):
    repo = _repo_root()
    inside = repo / ".tmp_p11e_patrol_probe" / "traces"

    code = main(["patrol", "--root", str(inside)])

    assert code == 2
    assert not inside.exists()

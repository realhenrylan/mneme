"""P1.1-E 防泄漏守卫契约：traces root 落在仓库工作树内时 capture 必须 fail-closed。

背景（owner PUSH_SAFETY 决策）：trace 数据与 consent.json 是 owner 个人本地
数据，任何情况下不得出现在 git 工作树内。本组测试锁定两条边界：

1. 仓库内 root（含 evaluation/** 受保护树）→ TraceStore 构造即拒绝，
   且在任何目录创建之前失败；
2. 仓库外 root 行为零变化（Off 零写入 / Minimal 正常采集不受影响）。

守卫的仓库根由模块物理位置推导，不依赖进程 CWD；不提供任何绕过开关。
"""
from pathlib import Path

import pytest

from src import production_observability as obs
from src.production_observability import ConsentLevel, TraceStore


def _repo_root() -> Path:
    """仓库工作树根：观测模块位于 <repo>/src/ 下，parents[1] 即仓库根。"""
    return Path(obs.__file__).resolve().parents[1]


def test_tracestore_rejects_root_inside_repo_working_tree():
    repo = _repo_root()
    inside = repo / ".tmp_p11e_guard_probe" / "traces"
    with pytest.raises(ValueError, match="仓库"):
        TraceStore(inside)
    assert not inside.exists(), "守卫必须在创建任何目录之前拒绝"


def test_guard_message_names_reason_and_config_fix():
    repo = _repo_root()
    inside = repo / ".tmp_p11e_guard_probe2" / "traces"
    with pytest.raises(ValueError, match="MNEME_DATA_DIR"):
        TraceStore(inside)


def test_evaluation_tree_remains_rejected():
    repo = _repo_root()
    with pytest.raises(ValueError):
        TraceStore(repo / "evaluation" / "p11e-probe" / "traces")


def test_construction_off_is_zero_write(tmp_path):
    root = tmp_path / "traces"
    store = TraceStore(root)
    assert store.consent.level is ConsentLevel.OFF
    assert not root.exists(), "Off 状态下构造 store 不得创建任何目录"


def test_outside_repo_root_behavior_unchanged(tmp_path):
    root = tmp_path / "traces"
    store = TraceStore(root)
    assert store.set_consent(ConsentLevel.MINIMAL, confirmed=True) is True
    assert (root / "consent.json").is_file()
    trace_id = store.begin_trace("sync", 20)
    assert trace_id
    assert store.emit_sensitive("rewrite.decided", "P11E_SECRET_MARKER",
                                trace_id=trace_id) is True
    assert store.finish_trace(trace_id) is True
    assert (root / f"{trace_id}.jsonl").is_file()
    assert store.verify_integrity(trace_id) is True


def test_default_environment_root_outside_repo(monkeypatch):
    """现状核验的可执行证据：默认配置下 traces root 必须解析到仓库外。"""
    monkeypatch.delenv("MNEME_DATA_DIR", raising=False)
    store = TraceStore.from_environment()
    repo = _repo_root()
    assert store.root.name == "traces"
    assert store.root != repo and repo not in store.root.parents

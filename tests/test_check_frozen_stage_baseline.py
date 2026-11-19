"""tests for scripts.check_frozen_stage_baseline.

为什么这个脚本需要测试：它是 CI 中 `frozen-stage-known-red` job 的唯一判定逻辑。
脚本本身腐化（解析失效、编码假设变化）时，job 会静默失去信号——这正是该 job
改造前的老问题，不能在新实现里重演。

覆盖重点：
- 真实 pytest 摘要行的解析（含 pytest 省略零值字段的行为）；
- 编码兼容（Windows PowerShell 重定向写 UTF-16LE，CI 写 UTF-8）；
- 基线一致 → 退出 0；任一单项漂移 → 退出 1（按项而非按总数比较）；
- 用法错误 / 文件缺失 → 退出 2，与「发现漂移」区分开。
"""

from __future__ import annotations

import scripts.check_frozen_stage_baseline as checker


# 真实读数：本地与 CI 两处观测一致（2026-10-31 归档日志 + 2026-11-18 复跑）。
REAL_TAIL = "240 failed, 2720 deselected, 78 errors in 24.07s"


def test_parse_counts_reads_real_pytest_summary() -> None:
    counts = checker.parse_counts(REAL_TAIL)
    assert counts == {"failed": 240, "errors": 78, "passed": 0}


def test_parse_counts_treats_missing_passed_as_zero() -> None:
    # pytest 在 passed == 0 时不输出该字段，解析必须把缺失当成 0 而非解析失败。
    assert checker.parse_counts("1 failed in 0.10s")["passed"] == 0


def test_parse_counts_reads_nonzero_passed() -> None:
    counts = checker.parse_counts("240 failed, 78 errors, 285 passed in 30.61s")
    assert counts == {"failed": 240, "errors": 78, "passed": 285}


def test_parse_counts_ignores_counts_outside_summary_tail() -> None:
    # 只统计尾部摘要，避免把用例名或进度行里的数字当成读数。
    text = "\n".join(["999 failed"] + ["." * 10] * 20 + [REAL_TAIL])
    assert checker.parse_counts(text)["failed"] == 240


def test_decode_log_handles_utf16le_bom() -> None:
    # PowerShell 的 `>` 重定向默认 UTF-16LE；首版脚本按 UTF-8 读会得到空内容。
    raw = REAL_TAIL.encode("utf-16-le")
    assert checker._decode_log(b"\xff\xfe" + raw).strip() == REAL_TAIL


def test_decode_log_handles_utf8() -> None:
    assert checker._decode_log(REAL_TAIL.encode("utf-8")).strip() == REAL_TAIL


def test_decode_log_handles_utf8_bom() -> None:
    raw = b"\xef\xbb\xbf" + REAL_TAIL.encode("utf-8")
    assert checker._decode_log(raw).strip() == REAL_TAIL


def test_main_returns_zero_on_matching_baseline(tmp_path, capsys) -> None:
    log = tmp_path / "frozen-stage.log"
    log.write_text(REAL_TAIL, encoding="utf-8")

    assert checker.main(["prog", str(log)]) == 0
    assert "Known-red baseline unchanged" in capsys.readouterr().out


def test_main_detects_failed_drift(tmp_path, capsys) -> None:
    # 239 failed：一个 known-red 用例开始通过，属真实信号，必须报出来。
    log = tmp_path / "frozen-stage.log"
    log.write_text("239 failed, 2720 deselected, 78 errors in 20.00s", encoding="utf-8")

    assert checker.main(["prog", str(log)]) == 1
    assert "KNOWN-RED BASELINE CHANGED" in capsys.readouterr().out


def test_main_detects_failure_mode_drift(tmp_path, capsys) -> None:
    # 总数不变但 1 个 failed 变 error：只比总数会漏掉这类漂移。
    log = tmp_path / "frozen-stage.log"
    log.write_text("240 failed, 2720 deselected, 79 errors in 20.00s", encoding="utf-8")

    assert checker.main(["prog", str(log)]) == 1
    assert "KNOWN-RED BASELINE CHANGED" in capsys.readouterr().out


def test_main_returns_usage_error_without_argument(capsys) -> None:
    assert checker.main(["prog"]) == 2
    assert "usage:" in capsys.readouterr().err


def test_main_returns_usage_error_when_log_missing(tmp_path) -> None:
    missing = tmp_path / "nope.log"
    assert checker.main(["prog", str(missing)]) == 2

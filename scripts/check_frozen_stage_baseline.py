"""Assert that the frozen_stage suite still matches its recorded known-red baseline.

背景：`frozen_stage` 是固定在 2026-08-29 之前语料快照上的历史阶段门禁测试。
这些用例的输入 SHA 指向已冻结的 sealed 资产，一旦活的 v2 draft 演进就会
fail-closed。因此它们**按设计永远全红**（240 failed / 78 errors / 0 passed），
见 docs/STATUS.md P0-1。

问题：一个永远红的 CI job 不提供任何回归信号——真实回归发生时读数不变，
无人能察觉。

本脚本把"预期全红"变成"读数必须等于基线"：
- 读数与基线逐项一致 → 退出 0（绿），含义是"历史套件行为与记录一致"；
- 读数有任何偏差 → 退出 1（红），含义是"冻结资产或 known-red 集合变了，
  需要人工分诊"。

为什么按项比较而不是只看总数：240 failed / 78 errors 是两类不同的失败模式
（断言失败 vs fixture/setup 抛错）。只比总数会让"1 个 failed 变成 error"
这类漂移被掩盖。

用法：
    python -m pytest -q --tb=line -m frozen_stage > frozen-stage.log 2>&1
    python scripts/check_frozen_stage_baseline.py frozen-stage.log
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# 基线来自 results/regression/2026-10-31-frozen-stage.log 与 2026-11-18 本地复跑，
# 两次读数逐项一致。改动此基线等同于重新裁定 P0-1，须另立记录。
EXPECTED = {"failed": 240, "errors": 78, "passed": 0}

# pytest 的 -q 摘要只统计尾部几行；0 passed 时该字段不出现，因此缺失按 0 处理。
_SUMMARY_TAIL_LINES = 5


def _decode_log(raw: bytes) -> str:
    """按 BOM 解码日志，兼容 Windows 重定向与 CI 输出。

    PowerShell 的 `>` 重定向默认写 UTF-16LE（带 BOM），而 CI 的 shell 与
    pytest 自身输出 UTF-8。不做 BOM 检测会让日志被解成空内容、计数全 0，
    从而把"基线未变"误判为"基线改变"。
    """
    if raw.startswith(b"\xff\xfe"):
        # 跳过 BOM 字节本身，否则解码结果会以 U+FEFF 开头（虽不影响尾部正则，
        # 但会让日志首行带隐形字符，发布到 CI 日志里很难排查）。
        return raw[2:].decode("utf-16-le", errors="replace")
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-16-le", errors="replace")


def parse_counts(log_text: str) -> dict[str, int]:
    """从 pytest 摘要行解析 failed / errors / passed 三项计数。

    参数:
        log_text: pytest 的完整标准输出（stderr 已合并）。

    返回:
        三项计数；日志中未出现的项按 0 处理（pytest 省略零值字段）。
    """
    tail = "\n".join(log_text.strip().splitlines()[-_SUMMARY_TAIL_LINES:])
    counts = {"failed": 0, "errors": 0, "passed": 0}
    for name in counts:
        match = re.search(rf"(\d+) {name}\b", tail)
        if match:
            counts[name] = int(match.group(1))
    return counts


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_frozen_stage_baseline.py <pytest-log>", file=sys.stderr)
        return 2

    log_path = Path(argv[1])
    if not log_path.is_file():
        print(f"log not found: {log_path}", file=sys.stderr)
        return 2

    counts = parse_counts(_decode_log(log_path.read_bytes()))
    print(f"known-red baseline: expected {EXPECTED}, observed {counts}")

    if counts != EXPECTED:
        print(
            "KNOWN-RED BASELINE CHANGED: the frozen_stage suite no longer matches "
            "its recorded state. Triage whether a pinned corpus snapshot moved, a "
            "known-red test started passing, or a new failure appeared."
        )
        return 1

    print("Known-red baseline unchanged (240 failed / 78 errors / 0 passed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

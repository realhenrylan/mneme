"""M5b al3 runner 测试：探针读取、跑批注入、密封产物自哈希。

路径拼接一律经 ``_safe_child``（resolve 后必须仍在 base 内），拒绝穿越。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from evaluation.refusal_judge_runner import (
    load_probe_rows,
    run_refusal_judge,
    write_sealed,
)


def _safe_child(base, *parts: str) -> Path:
    """在 base 内安全拼接路径（resolve 后必须仍位于 base 内，否则拒绝）。"""
    base_path = Path(base).resolve()
    candidate = base_path.joinpath(*parts).resolve()
    if candidate != base_path and base_path not in candidate.parents:
        raise ValueError(f"路径穿越拒绝: {candidate} 不在 {base_path} 内")
    return candidate


def _write_source(tmp_path, rows) -> Path:
    src = _safe_child(tmp_path, "source")
    src.mkdir(parents=True, exist_ok=True)
    content = "".join(
        json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    _safe_child(src, "outcomes.jsonl").write_text(content, encoding="utf-8")
    return src


class TestSafeChildGuard:
    def test_rejects_traversal(self, tmp_path):
        with pytest.raises(ValueError, match="路径穿越拒绝"):
            _safe_child(tmp_path, os.pardir, "escape")

    def test_allows_child(self, tmp_path):
        child = _safe_child(tmp_path, "inside")
        assert Path(child).parent == Path(tmp_path).resolve()


class TestLoadProbeRows:
    def test_only_probes_loaded(self, tmp_path):
        src = _write_source(tmp_path, [
            {"case_id": "a", "query": "q1", "answer": "a1", "should_refuse": True,
             "citation_metrics": {"correctly_refused": False}},
            {"case_id": "b", "query": "q2", "answer": "a2", "should_refuse": False,
             "citation_metrics": {"correctly_refused": True}},
        ])
        rows = load_probe_rows(src)
        assert len(rows) == 1
        assert rows[0]["case_id"] == "a"
        assert rows[0]["lexical_verdict"] is False

    def test_missing_source_raises(self, tmp_path):
        with pytest.raises(RuntimeError, match="密封产物不存在"):
            load_probe_rows(_safe_child(tmp_path, "nope"))


class TestRunRefusalJudge:
    def test_injected_call_fn(self):
        rows = [
            {"case_id": "a", "query": "q", "answer": "没有找到相关内容",
             "lexical_verdict": False},
            {"case_id": "b", "query": "q", "answer": "是的，文档提到 X",
             "lexical_verdict": False},
        ]

        def fake(messages, max_tokens):
            if "没有找到" in messages[1]["content"]:
                return json.dumps({"verdict": "refused", "evidence": "没有找到相关内容"})
            return json.dumps({"verdict": "answered", "evidence": "文档提到 X"})

        results = run_refusal_judge(rows, call_fn=fake, progress=False)
        assert len(results) == 2
        assert results[0].semantic_verdict == "refused"
        assert results[1].semantic_verdict == "answered"
        assert results[0].lexical_verdict is False


class TestWriteSealed:
    def _results(self):
        from evaluation.refusal_judge import RefusalJudgeResult
        return [
            RefusalJudgeResult(
                case_id="a", query="q", semantic_verdict="refused",
                evidence="没有找到", attempts=1, contract_error=False,
                should_refuse=True, lexical_verdict=False),
        ]

    def test_sealed_files_and_selfhash(self, tmp_path):
        src = _write_source(tmp_path, [
            {"case_id": "a", "query": "q", "answer": "x", "should_refuse": True,
             "citation_metrics": {}}])
        out = _safe_child(tmp_path, "out")
        write_sealed(
            out, results=self._results(),
            aggregate={"semantic_refusal_accuracy": 1.0},
            token_summary={"calls": 1},
            source_dir=src,
            source_sha256="abc",
            judge_model="deepseek-chat",
        )
        assert _safe_child(out, "outcomes-refusal-judge.jsonl").exists()
        assert _safe_child(out, "report.json").exists()
        manifest = json.loads(
            _safe_child(out, "manifest.json").read_text(encoding="utf-8"))
        body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        expect = hashlib.sha256(
            (json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
            .encode("utf-8")).hexdigest()
        assert manifest["manifest_sha256"] == expect

    def test_existing_dir_fail_closed(self, tmp_path):
        src = _write_source(tmp_path, [
            {"case_id": "a", "query": "q", "answer": "x", "should_refuse": True,
             "citation_metrics": {}}])
        out = _safe_child(tmp_path, "out")
        out.mkdir(parents=True, exist_ok=True)
        with pytest.raises(RuntimeError, match="fail-closed"):
            write_sealed(
                out, results=self._results(), aggregate={},
                token_summary={}, source_dir=src, source_sha256="abc",
                judge_model="m")

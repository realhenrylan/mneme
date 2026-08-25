"""Tests for scripts.corpus_v2_automated_review_reconcile.

对账断言（以 canonical automated-review.jsonl 为唯一事实来源）：
1. canonical 恰 150 行、case_id 唯一；
2. 每个 case 恰有一个合法 decision：confirmed / reject / needs_followup；
3. confirmed + reject + needs_followup == 150；
4. issues JSONL case_id 集合 == canonical 中 reject ∪ needs_followup（无重复/遗漏/额外）；
5. summary / gate report / review report / manifest 统计与 case 清单逐项 == canonical 复算；
6. 报告列出的每个 case_id 属于对应 decision；不得出现"显示 17 条但列出 19 条"矛盾；
7. canonical 重复 case / 非法 decision / JSON 损坏 / SHA 漂移 → fail-closed 零派生产物更新；
8. 对账前后 canonical / pack / evidence SHA 不变；
9. 存在 reject/needs_followup 时严禁 overlay，gate verdict 保持阻断。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

import scripts.corpus_v2_automated_review_reconcile as rc

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_DIR = REPO_ROOT / "evaluation" / "datasets" / "v2" / "automated-review"

DECISIONS = ("confirmed", "reject", "needs_followup")


# ── helpers ────────────────────────────────────────────────────────────

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _line(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _make_canonical(tmp: Path, rows: list[dict]) -> Path:
    """Write synthetic canonical review jsonl; returns path."""
    p = tmp / "automated-review.jsonl"
    p.write_text("\n".join(_line(r) for r in rows) + "\n", encoding="utf-8")
    return p


def _base_row(cid: str, decision: str = "confirmed") -> dict:
    return {
        "case_id": cid,
        "evidence_sha256": "a" * 64,
        "reviewer_type": "LLM_ASSISTED_OWNER_AUTHORIZED",
        "review_decision": decision,
        "confidence": "high",
        "rationale": "ok",
        "issue_categories": [],
        "model": "deepseek-v4-pro",
        "temperature": 0.0,
        "max_tokens": 8000,
        "evidence_summary": [],
        "prompt_sha256": "b" * 64,
        "response_sha256": "c" * 64,
        "raw_response_sha256": "d" * 64,
        "transport_retries": 0,
        "parse_retries": 0,
    }


# ── 真实产物断言（integration） ────────────────────────────────────────

@pytest.mark.skipif(not (REAL_DIR / "automated-review.jsonl").is_file(),
                    reason="real automated-review artifacts not present")
class TestRealCanonical:
    """对真实 150 条 canonical 的集成断言。"""

    def test_canonical_150_rows_unique(self):
        rows, sha = rc.load_canonical(REAL_DIR / "automated-review.jsonl")
        assert len(rows) == 150
        ids = [r["case_id"] for r in rows]
        assert len(set(ids)) == 150
        assert sha == _sha256_file(REAL_DIR / "automated-review.jsonl")

    def test_each_case_single_valid_decision(self):
        rows, _ = rc.load_canonical(REAL_DIR / "automated-review.jsonl")
        errs = rc.validate_canonical(rows)
        assert errs == []

    def test_counts_sum_to_150(self):
        rows, _ = rc.load_canonical(REAL_DIR / "automated-review.jsonl")
        stats = rc.recount(rows)
        assert stats["confirmed"] + stats["reject"] + \
            stats["needs_followup"] == 150
        assert stats["non_confirmed"] == stats["reject"] + \
            stats["needs_followup"]

    def test_issues_matches_reject_union_needs_followup(self):
        rows, _ = rc.load_canonical(REAL_DIR / "automated-review.jsonl")
        stats = rc.recount(rows)
        issues_path = REAL_DIR / "automated-review-issues.jsonl"
        errs = rc.check_issues_file(issues_path, stats)
        assert errs == []

    def test_summary_matches_canonical_recount(self):
        rows, _ = rc.load_canonical(REAL_DIR / "automated-review.jsonl")
        stats = rc.recount(rows)
        errs = rc.check_summary_file(
            REAL_DIR / "automated-review-summary.json", stats)
        assert errs == []

    def test_reports_listed_cases_match_canonical(self):
        """报告表格中每个 case_id 属于对应 decision；无 17/19 矛盾。"""
        rows, _ = rc.load_canonical(REAL_DIR / "automated-review.jsonl")
        stats = rc.recount(rows)
        errs = rc.check_reports(
            gate_path=REAL_DIR / "automated-review-gate-report.md",
            review_path=REAL_DIR / "automated-review-report.md",
            stats=stats)
        assert errs == []
        # 显式断言：needs_followup 恰 17 条且不含 en-054 / mixed-028
        assert stats["needs_followup"] == 17
        assert "en-054" not in stats["needs_followup_ids"]
        assert "mixed-028" not in stats["needs_followup_ids"]
        assert "en-054" in stats["confirmed_ids"]
        assert "mixed-028" in stats["confirmed_ids"]

    def test_manifest_decision_counts_and_sha_chain(self):
        rows, _ = rc.load_canonical(REAL_DIR / "automated-review.jsonl")
        stats = rc.recount(rows)
        errs = rc.check_manifest_file(
            manifest_path=REAL_DIR / "manifest.json",
            review_dir=REAL_DIR, stats=stats)
        assert errs == []

    def test_reconcile_no_overlay_when_issues_exist(self):
        """存在 reject/needs_followup → 不生成 overlay，gate 保持阻断。"""
        rows, _ = rc.load_canonical(REAL_DIR / "automated-review.jsonl")
        stats = rc.recount(rows)
        assert stats["non_confirmed"] > 0
        assert stats["overlay_eligible"] is False
        overlay_dir = REPO_ROOT / "evaluation" / "datasets" / "v2" / \
            "automated-reviewed-truth"
        overlay = overlay_dir / "automated-reviewed-truth-overlay.json"
        assert not overlay.exists(), "overlay must not exist while issues remain"

    def test_canonical_sha_unchanged_after_reconcile(self, tmp_path: Path):
        """对账后 canonical / pack / evidence SHA 不变（只读）。"""
        before = {
            "canonical": _sha256_file(REAL_DIR / "automated-review.jsonl"),
            "pack": _sha256_file(REAL_DIR / "automated-review-pack.jsonl"),
            "evidence": _sha256_file(
                REAL_DIR / "automated-review-evidence.jsonl"),
        }
        out = tmp_path / "reconciliation"
        rc.reconcile(review_dir=REAL_DIR, out_dir=out)
        after = {
            "canonical": _sha256_file(REAL_DIR / "automated-review.jsonl"),
            "pack": _sha256_file(REAL_DIR / "automated-review-pack.jsonl"),
            "evidence": _sha256_file(
                REAL_DIR / "automated-review-evidence.jsonl"),
        }
        assert before == after

    def test_reconcile_outputs_artifacts(self, tmp_path: Path):
        out = tmp_path / "reconciliation"
        rc.reconcile(review_dir=REAL_DIR, out_dir=out)
        assert (out / "reconciliation.json").is_file()
        assert (out / "reconciliation-report.md").is_file()
        assert (out / "manifest.json").is_file()
        data = json.loads((out / "reconciliation.json").read_text(
            encoding="utf-8"))
        assert data["canonical"]["n_cases"] == 150
        assert data["canonical"]["decision_counts"]["confirmed"] == 113
        assert data["canonical"]["decision_counts"]["reject"] == 20
        assert data["canonical"]["decision_counts"]["needs_followup"] == 17
        assert data["canonical"]["non_confirmed"] == 37


# ── fail-closed 断言（synthetic） ─────────────────────────────────────

class TestFailClosed:
    """canonical 非法 → 零派生产物更新。"""

    def test_duplicate_case_id_fails(self, tmp_path: Path):
        rows = [_base_row("c-001"), _base_row("c-001")]
        canon = _make_canonical(tmp_path, rows)
        errs = rc.validate_canonical(rc.load_canonical(canon)[0])
        assert any("duplicate" in e for e in errs)

    def test_invalid_decision_fails(self, tmp_path: Path):
        row = _base_row("c-001", decision="maybe")
        rows = [row]
        canon = _make_canonical(tmp_path, rows)
        errs = rc.validate_canonical(rc.load_canonical(canon)[0])
        assert any("invalid decision" in e for e in errs)

    def test_json_corruption_fails(self, tmp_path: Path):
        p = tmp_path / "automated-review.jsonl"
        p.write_text("{not json}\n", encoding="utf-8")
        with pytest.raises(rc.ReconcileError, match="JSON"):
            rc.load_canonical(p)

    def test_sha_drift_fails_closed(self, tmp_path: Path):
        """manifest 记录 SHA 与文件实际 SHA 不一致 → fail-closed。"""
        rows = [_base_row(f"c-{i:03d}") for i in range(1, 151)]
        canon = _make_canonical(tmp_path, rows)
        out = tmp_path / "reconciliation"
        # 构造一个 review dir：canonical + 伪造 manifest
        review_dir = tmp_path / "review"
        review_dir.mkdir()
        canon_target = review_dir / "automated-review.jsonl"
        canon_target.write_text(canon.read_text(encoding="utf-8"),
                                encoding="utf-8")
        (review_dir / "manifest.json").write_text(
            json.dumps({"review_sha256": "0" * 64}, ensure_ascii=False),
            encoding="utf-8")
        with pytest.raises(rc.ReconcileError, match="SHA"):
            rc.reconcile(review_dir=review_dir, out_dir=out)
        assert not (out / "reconciliation.json").exists()

    def test_issues_extra_or_missing_detected(self, tmp_path: Path):
        rows = [
            _base_row("c-001", decision="confirmed"),
            _base_row("c-002", decision="reject"),
            _base_row("c-003", decision="needs_followup"),
        ]
        stats = rc.recount(rows)
        issues = tmp_path / "automated-review-issues.jsonl"
        # 只含 reject，缺 needs_followup
        issues.write_text(
            _line({**rows[1], "case_id": "c-002"}) + "\n", encoding="utf-8")
        errs = rc.check_issues_file(issues, stats)
        assert errs

    def test_report_wrong_decision_column_detected(self, tmp_path: Path):
        """报告把 confirmed case 列为 needs_followup → 检出。"""
        rows = [
            _base_row("c-001", decision="confirmed"),
            _base_row("c-002", decision="reject"),
        ]
        stats = rc.recount(rows)
        md = tmp_path / "report.md"
        md.write_text(
            "| case_id | decision | 问题类别 | 理由 |\n"
            "|---|---|---|---|\n"
            "| c-001 | needs_followup | other | wrong |\n",
            encoding="utf-8")
        errs = rc._check_report_table(md, stats)
        assert errs


# ── 确定性重建断言 ────────────────────────────────────────────────────

class TestRebuild:
    """机械重建：只修正统计/清单/派生 SHA，不改 150 条 decision。"""

    def test_rebuild_keeps_decisions(self, tmp_path: Path):
        rows = [
            _base_row("c-001", decision="confirmed"),
            _base_row("c-002", decision="reject"),
            _base_row("c-003", decision="needs_followup"),
        ]
        canon = _make_canonical(tmp_path, rows)
        rebuilt = rc.rebuild_issues(rc.load_canonical(canon)[0])
        assert {r["case_id"] for r in rebuilt} == {"c-002", "c-003"}
        assert all(r["review_decision"] in ("reject", "needs_followup")
                   for r in rebuilt)
        # decision 不变
        assert all(r["review_decision"] == orig["review_decision"]
                   for r, orig in zip(rebuilt, [rows[1], rows[2]]))

    def test_rebuild_summary_matches_recount(self, tmp_path: Path):
        rows = [_base_row(f"c-{i:03d}") for i in range(1, 5)]
        rows[1]["review_decision"] = "reject"
        rows[2]["review_decision"] = "needs_followup"
        stats = rc.recount(rows)
        summary = rc.rebuild_summary(rows, stats)
        assert summary["n_cases"] == 4
        assert summary["decision_counts"] == {
            "confirmed": 2, "reject": 1, "needs_followup": 1}
        assert summary["non_confirmed_count"] == 2
        assert summary["overlay_eligible"] is False

    def test_rebuild_is_deterministic(self, tmp_path: Path):
        rows = [_base_row(f"c-{i:03d}") for i in range(1, 4)]
        stats = rc.recount(rows)
        s1 = rc.rebuild_summary(rows, stats)
        s2 = rc.rebuild_summary(rows, stats)
        assert json.dumps(s1, sort_keys=True) == json.dumps(s2, sort_keys=True)
        g1 = rc.rebuild_gate_report(rows, stats)
        g2 = rc.rebuild_gate_report(rows, stats)
        assert g1 == g2
        r1 = rc.rebuild_review_report(rows, stats)
        r2 = rc.rebuild_review_report(rows, stats)
        assert r1 == r2

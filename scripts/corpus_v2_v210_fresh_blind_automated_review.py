"""Run a fresh, full, Pro-only blind automated review for v2.0.10.

The review engine is shared with the frozen v2.0.9 implementation.  This
adapter installs a v2.0.10 runtime profile only for the duration of a call and
restores every v2.0.9 global afterwards.  It never reads v2.0.9 review or
triage contents: those paths are used only for byte-level input-SHA checks
recorded by the v2.0.10 candidate manifest.
"""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import corpus_v2_v209_fresh_blind_automated_review as base  # noqa: E402


V208 = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.8-owner-authorized-semantic-quality-remediation"
V209 = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.9-owner-authorized-final-dependency-closed-retirement"
CANDIDATE = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.10-owner-authorized-coherence-remediation"
OUT = CANDIDATE / "automated-review"
CHUNKS_PATH = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST_PATH = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT_PATH = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"
TRANS_POLICY_PATH = V208 / "translation-equivalence-policy.md"
TRANS_LEDGER_PATH = V208 / "translation-equivalence-policy-ledger.jsonl"

MODEL = base.MODEL
TEMPERATURE = base.TEMPERATURE
MAX_TOKENS = base.MAX_TOKENS
MAX_RETRIES = base.MAX_RETRIES
THINKING_DISABLED = base.THINKING_DISABLED
ReviewError = base.ReviewError
_DEFAULT_CLIENT = base._DEFAULT_CLIENT


@dataclass(frozen=True)
class ReviewProfile:
    candidate_actor: str
    candidate_gate: str
    expected_case_count: int
    expected_evidence_count: int
    expected_answerable: int
    expected_refusal_count: int
    expected_candidate_retired_cases: int
    expected_candidate_retired_evidence: int
    actor: str
    overlay_status: str
    gate_ok: str
    gate_blocked: str
    rule_version: str
    task_name: str
    review_label: str
    created_by: str


PROFILE = ReviewProfile(
    candidate_actor="OWNER_AUTHORIZED_V2_0_10_COHERENCE_REMEDIATION",
    candidate_gate="COHERENCE_REMEDIATION_CANDIDATE_OK",
    expected_case_count=136,
    expected_evidence_count=148,
    expected_answerable=105,
    expected_refusal_count=31,
    expected_candidate_retired_cases=1,
    expected_candidate_retired_evidence=1,
    actor="OWNER_AUTHORIZED_V2_0_10_FRESH_BLIND_AUTOMATED_REVIEW",
    overlay_status="LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_10",
    gate_ok="AUTOMATED_REVIEW_136_136_CONFIRMED",
    gate_blocked="AUTOMATED_REVIEW_GATE_BLOCKED",
    rule_version="v2.0.10-fresh-blind-automated-review-1",
    task_name="v2.0.10-fresh-full-blind-automated-review",
    review_label="v2.0.10",
    created_by="corpus_v2_v210_fresh_blind_automated_review.py",
)
GATE_OK = PROFILE.gate_ok
GATE_BLOCKED = PROFILE.gate_blocked

_RUNTIME_KEYS = (
    "CANDIDATE", "OUT", "EXPECTED_CASE_COUNT", "EXPECTED_EVIDENCE_COUNT",
    "EXPECTED_REFUSAL_COUNT", "EXPECTED_ANSWERABLE",
    "EXPECTED_CANDIDATE_RETIRED_CASES", "EXPECTED_CANDIDATE_RETIRED_EVIDENCE",
    "ACTOR", "OVERLAY_STATUS", "GATE_OK", "GATE_BLOCKED", "RULE_VERSION",
    "TASK_NAME", "REVIEW_LABEL", "CREATED_BY", "CANDIDATE_ACTOR",
    "CANDIDATE_GATE", "INPUT_READ_PATHS", "INPUT_SHA_MAP", "INPUT_CHECK_MAP",
    "RETIRED_IDS", "SKILL_NOTE",
)


def _candidate_input_sha_map() -> dict[str, Path]:
    """Map every v2.0.10 manifest input digest to its immutable source path."""
    triage = V209 / "automated-review/coherence-reject-triage"
    return {
        "v209-manifest.json": V209 / "manifest.json",
        "v209-draft-after.jsonl": V209 / "draft-after.jsonl",
        "v209-evidence-after.jsonl": V209 / "evidence-after.jsonl",
        "v209-review-manifest.json": V209 / "automated-review/manifest.json",
        "v209-review-issues.jsonl":
            V209 / "automated-review/automated-review-issues.jsonl",
        "v209-triage-manifest.json": triage / "manifest.json",
        "v209-triage-reject-root-cause-triage.jsonl":
            triage / "reject-root-cause-triage.jsonl",
        "v209-mixed-033-duplicate-evidence-check.json":
            triage / "mixed-033-duplicate-evidence-check.json",
        "chunks.jsonl": CHUNKS_PATH,
        "chunk-manifest.json": CHUNK_MANIFEST_PATH,
        "current-v2-draft.jsonl": CURRENT_DRAFT_PATH,
        "translation-equivalence-policy.md": TRANS_POLICY_PATH,
        "translation-equivalence-policy-ledger.jsonl": TRANS_LEDGER_PATH,
    }


def _base_runtime_snapshot() -> dict:
    return {name: getattr(base, name) for name in _RUNTIME_KEYS}


@contextmanager
def _v210_runtime():
    """Install the profile in the shared engine and restore it transactionally."""
    before = _base_runtime_snapshot()
    allowed = {
        CANDIDATE / "draft-after.jsonl",
        CANDIDATE / "evidence-after.jsonl",
        CANDIDATE / "manifest.json",
        CHUNKS_PATH,
        CHUNK_MANIFEST_PATH,
        TRANS_POLICY_PATH,
        TRANS_LEDGER_PATH,
    }
    overrides = {
        "CANDIDATE": CANDIDATE,
        "OUT": OUT,
        "EXPECTED_CASE_COUNT": PROFILE.expected_case_count,
        "EXPECTED_EVIDENCE_COUNT": PROFILE.expected_evidence_count,
        "EXPECTED_REFUSAL_COUNT": PROFILE.expected_refusal_count,
        "EXPECTED_ANSWERABLE": PROFILE.expected_answerable,
        "EXPECTED_CANDIDATE_RETIRED_CASES":
            PROFILE.expected_candidate_retired_cases,
        "EXPECTED_CANDIDATE_RETIRED_EVIDENCE":
            PROFILE.expected_candidate_retired_evidence,
        "ACTOR": PROFILE.actor,
        "OVERLAY_STATUS": PROFILE.overlay_status,
        "GATE_OK": PROFILE.gate_ok,
        "GATE_BLOCKED": PROFILE.gate_blocked,
        "RULE_VERSION": PROFILE.rule_version,
        "TASK_NAME": PROFILE.task_name,
        "REVIEW_LABEL": PROFILE.review_label,
        "CREATED_BY": PROFILE.created_by,
        "CANDIDATE_ACTOR": PROFILE.candidate_actor,
        "CANDIDATE_GATE": PROFILE.candidate_gate,
        "INPUT_READ_PATHS": allowed,
        "INPUT_SHA_MAP": _candidate_input_sha_map(),
        "RETIRED_IDS": set(base.RETIRED_IDS) | {"multi-019"},
        "SKILL_NOTE": (
            "data-analytics:analyze-data-quality workflow was applied to the "
            "candidate's deterministic five-dimension validation."
        ),
    }
    try:
        for name, value in overrides.items():
            setattr(base, name, value)
        base.INPUT_CHECK_MAP = base._input_check_map(CANDIDATE)
        yield
    finally:
        for name, value in before.items():
            setattr(base, name, value)


def preflight(*, candidate_dir: Path = CANDIDATE,
              chunks_path: Path = CHUNKS_PATH,
              chunk_manifest_path: Path = CHUNK_MANIFEST_PATH,
              current_draft_path: Path = CURRENT_DRAFT_PATH,
              trans_policy_path: Path = TRANS_POLICY_PATH,
              trans_ledger_path: Path = TRANS_LEDGER_PATH) -> dict:
    with _v210_runtime():
        return base.preflight(candidate_dir, chunks_path, chunk_manifest_path,
                              current_draft_path, trans_policy_path,
                              trans_ledger_path)


def run(*, out_dir: Path = OUT, candidate_dir: Path = CANDIDATE,
        chunks_path: Path = CHUNKS_PATH,
        chunk_manifest_path: Path = CHUNK_MANIFEST_PATH,
        current_draft_path: Path = CURRENT_DRAFT_PATH,
        trans_policy_path: Path = TRANS_POLICY_PATH,
        trans_ledger_path: Path = TRANS_LEDGER_PATH,
        client=_DEFAULT_CLIENT) -> dict:
    """Perform one fresh full review; never reuse a pre-existing output folder."""
    if out_dir.exists():
        raise ReviewError(f"review output directory already exists: {out_dir}")
    with _v210_runtime():
        return base.run(
            out_dir=out_dir,
            candidate_dir=candidate_dir,
            chunks_path=chunks_path,
            chunk_manifest_path=chunk_manifest_path,
            current_draft_path=current_draft_path,
            trans_policy_path=trans_policy_path,
            trans_ledger_path=trans_ledger_path,
            client=client,
        )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--probe-json" in args:
        with _v210_runtime():
            try:
                result = base.probe(_DEFAULT_CLIENT)
            except Exception as exc:
                print(json.dumps({"ok": False, "model": None,
                                  "expected_model": MODEL, "error": str(exc)},
                                 ensure_ascii=False, indent=1))
                return 2
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0

    parser = argparse.ArgumentParser(
        description="v2.0.10 fresh full blind automated review")
    parser.add_argument("command", nargs="?", default="build", choices=("build",))
    parser.add_argument("--out-dir", default=str(OUT))
    parser.add_argument("--candidate-dir", default=str(CANDIDATE))
    parser.add_argument("--chunks", default=str(CHUNKS_PATH))
    parser.add_argument("--chunk-manifest", default=str(CHUNK_MANIFEST_PATH))
    parser.add_argument("--current-draft", default=str(CURRENT_DRAFT_PATH))
    parser.add_argument("--trans-policy", default=str(TRANS_POLICY_PATH))
    parser.add_argument("--trans-ledger", default=str(TRANS_LEDGER_PATH))
    ns = parser.parse_args(args)
    try:
        result = run(
            out_dir=Path(ns.out_dir),
            candidate_dir=Path(ns.candidate_dir),
            chunks_path=Path(ns.chunks),
            chunk_manifest_path=Path(ns.chunk_manifest),
            current_draft_path=Path(ns.current_draft),
            trans_policy_path=Path(ns.trans_policy),
            trans_ledger_path=Path(ns.trans_ledger),
            client=_DEFAULT_CLIENT,
        )
    except ReviewError as exc:
        print(f"v2.0.10 blind review failed closed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"gate": result["gate"], "counts": result["counts"],
                      "out_dir": str(result["out_dir"])}, ensure_ascii=False,
                     indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

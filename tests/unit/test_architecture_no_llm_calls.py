"""Static guards backing acceptance criteria #5 ("pipeline runs with zero LLM
calls") and #7 ("no Opus calls in logs"): make both true by construction
rather than by hoping nobody adds a call or a model string later.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent.parent / "src" / "opportunity_engine"
ALLOWED_LLM_VENDOR_FILE = SRC_ROOT / "providers" / "llm_provider.py"
VENDOR_IMPORT_PATTERN = re.compile(r"^\s*(import|from)\s+(anthropic|openai)\b", re.MULTILINE)
# Matches an actual Opus *model identifier* shape (claude-opus-5, claude_opus_4_8, ...),
# not the bare English word -- CLAUDE.md and llm_provider.py's docstrings need to be able
# to explain the ban in prose ("Opus is banned outright") without tripping this guard.
# The real risk this catches is a hardcoded model-ID string, which the runtime
# ALLOWED_MODELS allowlist in llm_provider.py also independently rejects.
OPUS_MODEL_ID_PATTERN = re.compile(r"claude[-_]opus", re.IGNORECASE)


def _all_source_files() -> list[Path]:
    return sorted(SRC_ROOT.rglob("*.py"))


def test_no_llm_vendor_sdk_imported_outside_llm_provider() -> None:
    offenders = []
    for path in _all_source_files():
        if path == ALLOWED_LLM_VENDOR_FILE:
            continue
        if VENDOR_IMPORT_PATTERN.search(path.read_text()):
            offenders.append(str(path))
    assert offenders == [], (
        "LLM vendor SDKs may only be imported from providers/llm_provider.py, "
        f"found in: {offenders}"
    )


def test_no_opus_model_id_appears_anywhere_in_source() -> None:
    """Opus is banned on this project outright, in any phase (see CLAUDE.md).
    No literal `claude-opus-*` model-ID string may appear anywhere in `src/`."""
    offenders = [
        str(path) for path in _all_source_files() if OPUS_MODEL_ID_PATTERN.search(path.read_text())
    ]
    assert offenders == [], (
        f"an Opus model-ID string must never appear in source, found in: {offenders}"
    )

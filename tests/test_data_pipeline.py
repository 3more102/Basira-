import json
import pytest
from scripts.audit_corpus import audit
from scripts.prepare_corpus import prepare

def test_audit_dedup_and_split(tmp_path):
    src = tmp_path / "corpus.jsonl"
    entries = [
        {"text": "مرحبا بالعالم", "source": "fixture", "license": "test-only"},
        {"text": "مرحبا بالعالم", "source": "fixture", "license": "test-only"},
        {"text": "Hello world", "source": "fixture", "license": "test-only"},
    ]
    src.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in entries), encoding="utf-8")
    report = audit(src)
    assert report["accepted"] == 2 and report["duplicates"] == 1
    result = prepare(src, tmp_path / "out")
    assert result["train"] + result["validation"] == 2
    assert result["duplicates"] == 1

def test_missing_provenance_rejected(tmp_path):
    src = tmp_path / "bad.jsonl"
    src.write_text(json.dumps({"text": "hello"}) + "\n", encoding="utf-8")
    assert audit(src)["invalid"] == 1
    with pytest.raises(ValueError):
        prepare(src, tmp_path / "out")

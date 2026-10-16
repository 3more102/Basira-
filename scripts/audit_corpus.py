"""Audit JSONL text corpus before tokenizer training. Does not prove licensing."""
import argparse
import hashlib
import json
from pathlib import Path

def audit(path):
    seen = set()
    counts = {"lines": 0, "accepted": 0, "duplicates": 0, "invalid": 0, "characters": 0}
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            counts["lines"] += 1
            try:
                item = json.loads(line)
                text = item["text"]
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("missing text")
                if not isinstance(item.get("source"), str) or not item["source"].strip():
                    raise ValueError("missing source")
                if not isinstance(item.get("license"), str) or not item["license"].strip():
                    raise ValueError("missing license")
                digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
                if digest in seen:
                    counts["duplicates"] += 1
                    continue
                seen.add(digest)
                counts["accepted"] += 1
                counts["characters"] += len(text)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                counts["invalid"] += 1
    return counts

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    result = audit(args.path)
    print(json.dumps(result, indent=2))
    if result["invalid"] or not result["accepted"]:
        raise SystemExit("Corpus audit failed; correct invalid records")

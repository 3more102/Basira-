"""Prepare deduplicated text files from provenance-tagged JSONL. Split by document."""
import argparse
import hashlib
import json
from pathlib import Path

def prepare(source, output_dir, validation_percent=1):
    if not 0 < validation_percent < 100:
        raise ValueError("validation_percent must be between 0 and 100")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    seen = set()
    counts = {"train": 0, "validation": 0, "duplicates": 0}
    with Path(source).open(encoding="utf-8") as inp, (out/"train.txt").open("w", encoding="utf-8") as train, (out/"validation.txt").open("w", encoding="utf-8") as val:
        for number, line in enumerate(inp, 1):
            item = json.loads(line)
            if not all(isinstance(item.get(k), str) and item[k].strip() for k in ("text", "source", "license")):
                raise ValueError(f"Invalid record on line {number}")
            content = item["text"].strip().replace("\n", " ")
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if digest in seen:
                counts["duplicates"] += 1
                continue
            seen.add(digest)
            bucket = "validation" if int(digest[:8], 16) % 100 < validation_percent else "train"
            (val if bucket == "validation" else train).write(content + "\n")
            counts[bucket] += 1
    return counts

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--validation-percent", type=int, default=1)
    args = p.parse_args()
    print(json.dumps(prepare(args.input, args.output, args.validation_percent), indent=2))

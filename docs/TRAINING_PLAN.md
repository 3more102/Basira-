# Basira-1B training readiness and acceptance gates

## Gate 0 — Architecture
- 1,004,259,328 analytically counted parameters; compare against actual allocated tensors on a memory-sufficient GPU or CPU host.
- Tests must validate causal loss, gradient flow, and weight tying.
- No pretrained weights currently exist.

## Gate 1 — Data
- Collect Arabic and English data with source and license metadata.
- Run `python scripts/audit_corpus.py data/raw.jsonl`.
- Run `python scripts/prepare_corpus.py --input data/raw.jsonl --output data/processed`.
- Review source licenses manually: a filled license string is **not** proof of authorization.
- Filter PII, secrets, copyrighted material without authorization, and benchmark leakage.
- Maintain document-level held-out splits and publish dataset provenance statistics.
- Train the BPE tokenizer on **training data only**, then check exact vocabulary size.

## Gate 2 — Smoke tests
- Execute unit tests on CPU; train a small model with a matching tokenizer vocabulary.
- Verify save/resume, finite loss, optimizer behavior, and deterministic evaluation.
- Check actual memory use, throughput, and tokens/sec on a single cloud GPU.

## Gate 3 — Distributed training
- Implement and validate FSDP2 or ZeRO sharding, gradient accumulation, BF16, learning-rate schedule, checkpoint resumption, and monitoring.
- Record GPU model, count, peak memory, measured throughput, training tokens, data mix, and total GPU-hours.
- Set training duration based on measured throughput and budget; never infer completion from step count alone.

## Gate 4 — Evaluation and release
- Report held-out Arabic and English perplexity separately, contamination checks, multilingual benchmark results, safety and memorization audits.
- Record model card, dataset provenance, weights hashes, licensing review, and reproducibility.
- **Release trained weights only after all gates pass.**

## Current status (2026-10-16)
Architecture, baseline trainer, tokenizer utility, data preparation/audit and tests have source implementations. Cloud pretraining, actual tensor-allocation verification, CI run status, dataset ingestion, and trained checkpoint remain unverified/not performed.

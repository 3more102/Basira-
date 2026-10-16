"""Baseline causal language modeling trainer. Smoke test first; full run requires GPU engineering."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import torch
from torch.utils.data import Dataset
from transformers import AutoTokenizer, Trainer, TrainingArguments, default_data_collator
from basira import make_config, make_model

class Blocks(Dataset):
    def __init__(self, path, tokenizer, block_size):
        text = Path(path).read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError("Training corpus is empty")
        ids = tokenizer(text, add_special_tokens=False)["input_ids"]
        ids.append(tokenizer.eos_token_id)
        self.blocks = [ids[i:i+block_size] for i in range(0, len(ids)-block_size+1, block_size)]
        if not self.blocks:
            raise ValueError("Not enough tokens for one block; add data or lower --block-size")
    def __len__(self):
        return len(self.blocks)
    def __getitem__(self, idx):
        ids = torch.tensor(self.blocks[idx], dtype=torch.long)
        return {"input_ids": ids, "attention_mask": torch.ones_like(ids), "labels": ids.clone()}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tokenizer", required=True)
    p.add_argument("--data", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--tiny", action="store_true")
    p.add_argument("--steps", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=1)
    p.add_argument("--grad-accum", type=int, default=1)
    p.add_argument("--block-size", type=int, default=128)
    p.add_argument("--lr", type=float, default=3e-4)
    args = p.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer)
    config = make_config(tiny=args.tiny)
    if len(tokenizer) != config.vocab_size:
        raise ValueError(f"Tokenizer vocab {len(tokenizer)} != model vocab {config.vocab_size}")
    if args.block_size > config.max_position_embeddings:
        raise ValueError("block-size exceeds model context window")
    model = make_model(tiny=args.tiny)
    ds = Blocks(args.data, tokenizer, args.block_size)
    training = TrainingArguments(
        output_dir=args.output, max_steps=args.steps,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr, logging_steps=1, save_steps=max(1,args.steps),
        save_safetensors=True, report_to="none",
        bf16=torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
        dataloader_num_workers=0)
    trainer = Trainer(model=model, args=training, train_dataset=ds,
                      data_collator=default_data_collator)
    trainer.train()
    trainer.save_model(args.output)
    tokenizer.save_pretrained(args.output)

if __name__ == "__main__":
    main()

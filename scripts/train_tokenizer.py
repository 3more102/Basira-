"""Train a byte-level BPE tokenizer from original corpus; no pretrained tokenizer."""
import argparse
from pathlib import Path
from tokenizers import Tokenizer, models, trainers, pre_tokenizers, decoders, processors
from transformers import PreTrainedTokenizerFast

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--vocab-size", type=int, default=50000)
    args = p.parse_args()
    if not Path(args.input).is_file():
        raise FileNotFoundError(args.input)
    tok = Tokenizer(models.BPE(unk_token="<unk>"))
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    specials = ["<pad>", "<unk>", "<s>", "</s>"]
    tok.train([args.input], trainers.BpeTrainer(vocab_size=args.vocab_size,
                                               min_frequency=2, special_tokens=specials,
                                               initial_alphabet=pre_tokenizers.ByteLevel.alphabet()))
    tok.post_processor = processors.TemplateProcessing(
        single="<s> $A </s>", pair="<s> $A </s> $B:1 </s>:1",
        special_tokens=[("<s>", tok.token_to_id("<s>")), ("</s>", tok.token_to_id("</s>"))])
    hf = PreTrainedTokenizerFast(tokenizer_object=tok, bos_token="<s>", eos_token="</s>",
                                 unk_token="<unk>", pad_token="<pad>")
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    hf.save_pretrained(out)
    print(f"Saved tokenizer with {len(hf)} tokens to {out}")
    if len(hf) != args.vocab_size:
        raise RuntimeError("Corpus did not yield requested vocabulary; do not train model with mismatched vocab.")
if __name__ == "__main__":
    main()

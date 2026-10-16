from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from basira import make_config, theoretical_parameters

config = make_config()
count = theoretical_parameters(config)
print(f"Basira-1B theoretical trainable parameters: {count:,} ({count/1e9:.6f}B)")
assert count == 1_004_259_328
print("To independently verify tensor allocation, instantiate make_model() on a memory-sufficient host and sum p.numel().")

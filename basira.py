"""Basira-1B original random-initialization model configuration."""
from transformers import LlamaConfig, LlamaForCausalLM

def make_config(tiny=False):
    if tiny:
        return LlamaConfig(vocab_size=256, hidden_size=128, intermediate_size=352,
                           num_hidden_layers=2, num_attention_heads=4,
                           num_key_value_heads=2, max_position_embeddings=128,
                           tie_word_embeddings=True)
    return LlamaConfig(vocab_size=50000, hidden_size=2048, intermediate_size=5632,
                       num_hidden_layers=20, num_attention_heads=16,
                       num_key_value_heads=4, max_position_embeddings=4096,
                       tie_word_embeddings=True, attention_bias=False,
                       mlp_bias=False)

def make_model(tiny=False):
    return LlamaForCausalLM(make_config(tiny=tiny))

def theoretical_parameters(config):
    h, d, n = config.hidden_size, config.intermediate_size, config.num_hidden_layers
    kv = h * config.num_key_value_heads // config.num_attention_heads
    # embedding + attention (Q,K,V,O) + gated MLP + 2 RMSNorms/layer + final RMSNorm
    return config.vocab_size*h + n*(2*h*h + 2*h*kv + 3*h*d + 2*h) + h

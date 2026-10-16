from basira import make_config, make_model, theoretical_parameters
import torch

def test_exact_1b_parameter_formula():
    cfg = make_config()
    assert theoretical_parameters(cfg) == 1_004_259_328
    assert cfg.num_hidden_layers == 20
    assert cfg.tie_word_embeddings

def test_tiny_forward_backward_and_parameter_formula():
    model = make_model(tiny=True)
    assert sum(p.numel() for p in model.parameters()) == theoretical_parameters(make_config(tiny=True))
    ids = torch.randint(0, 256, (2, 12))
    out = model(input_ids=ids, labels=ids)
    assert torch.isfinite(out.loss)
    out.loss.backward()
    assert model.model.embed_tokens.weight.grad is not None

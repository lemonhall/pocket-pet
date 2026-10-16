"""REQ-0001-007 / REQ-0001-008 shape gates: the student must stay in the
architecture the existing Q4 engine and SIMD kernels expect.

If these fail, "zero kernel changes" is off the table, so they are cheap but hard
gates - not nice-to-haves.
"""
from pocket_pet import tokenizer as T
from pocket_pet.model import CatLM, Config


def test_vocab_is_closed_and_small():
    v = T.VOCAB
    assert len(v) == len(set(v)), "duplicate token"
    assert len(v) <= 64, f"vocab {len(v)} exceeds the 64 the engine allows"
    for name in ("hunger", "litter_box", "seek_food", "hide", "night", "elder", "none"):
        assert name in T.STOI, f"{name} missing from the vocabulary"


def test_vocab_covers_every_state_line():
    """Every field and every legal value must be encodable with no <unk>."""
    from pocket_pet.state import NUMERIC, STAGES, TIMES, WHERE, GOALS, BUCKETS
    for name in list(NUMERIC) + list(WHERE) + ["stage", "last", "time"]:
        assert name in T.STOI
    for d in range(max(NUMERIC.values())):
        assert str(d) in T.STOI
    for w in list(BUCKETS) + [str(c) for c in range(1, 13)] + list(STAGES) + list(TIMES) + list(GOALS):
        assert w in T.STOI, f"{w} not in vocab"


def test_param_count_is_about_14m():
    m = CatLM(Config())
    n = m.n_params()
    assert 12_000_000 <= n <= 16_000_000, f"{n:,} params is not the 14M shape"


def test_forward_shape_and_goal_logits():
    import torch
    m = CatLM(Config())
    ids = T.encode("hunger 8 energy 1 bored 3", bos=True)[: Config().seq_len]
    logits = m.next_token_logits(ids)
    assert logits.shape[0] == Config().vocab_size
    goals = torch.tensor([T.STOI[g] for g in T.GOALS])
    assert goals.max() < logits.shape[0]


def test_roundtrip_encode_decode():
    line = "hunger 6 energy 3 stage adult time night"
    assert T.decode(T.encode(line, bos=False)) == line

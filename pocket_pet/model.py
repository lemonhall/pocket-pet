"""A 14M-parameter llama2.c-style model: RMSNorm, RoPE, SwiGLU, 8 layers.

Same shape as the one pocket-tank ships, so the exported weights can be handed to
the existing Q4 engine (M5). It is a next-token LM, not a classifier: the goal is
simply the token that follows the state line.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class Config:
    vocab_size: int = 60
    dim: int = 384
    n_layers: int = 8
    n_heads: int = 8
    seq_len: int = 64
    dropout: float = 0.0


class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float = 1e-5):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps) * self.weight


def rope(x: torch.Tensor) -> torch.Tensor:
    """Rotary positions, applied to (B, H, T, D)."""
    b, h, t, d = x.shape
    half = d // 2
    pos = torch.arange(t, device=x.device, dtype=torch.float32)
    freqs = torch.exp(-math.log(10000.0) * torch.arange(half, device=x.device) / half)
    ang = pos[:, None] * freqs[None, :]
    cos, sin = ang.cos()[None, None], ang.sin()[None, None]
    x1, x2 = x[..., :half], x[..., half:]
    return torch.cat([x1 * cos - x2 * sin, x1 * sin + x2 * cos], dim=-1)


class Attention(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        self.n_heads = cfg.n_heads
        self.head_dim = cfg.dim // cfg.n_heads
        self.wq = nn.Linear(cfg.dim, cfg.dim, bias=False)
        self.wk = nn.Linear(cfg.dim, cfg.dim, bias=False)
        self.wv = nn.Linear(cfg.dim, cfg.dim, bias=False)
        self.wo = nn.Linear(cfg.dim, cfg.dim, bias=False)

    def forward(self, x, mask):
        b, t, _ = x.shape
        q = self.wq(x).view(b, t, self.n_heads, self.head_dim).transpose(1, 2)
        k = self.wk(x).view(b, t, self.n_heads, self.head_dim).transpose(1, 2)
        v = self.wv(x).view(b, t, self.n_heads, self.head_dim).transpose(1, 2)
        q, k = rope(q), rope(k)
        att = (q @ k.transpose(-2, -1)) / math.sqrt(self.head_dim)
        att = att.masked_fill(mask == 0, float("-inf"))
        out = (att.softmax(-1) @ v).transpose(1, 2).reshape(b, t, -1)
        return self.wo(out)


class Block(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        # llama's 8/3 * dim, rounded to 8: 1024 at dim 384. Using 4*dim made the
        # model 18.9M, which is not the architecture the Q4 engine expects
        # (test_param_count_is_about_14m caught it).
        hidden = int(8 / 3 * cfg.dim / 8) * 8
        self.attn_norm = RMSNorm(cfg.dim)
        self.attn = Attention(cfg)
        self.ffn_norm = RMSNorm(cfg.dim)
        self.w1 = nn.Linear(cfg.dim, hidden, bias=False)
        self.w3 = nn.Linear(cfg.dim, hidden, bias=False)
        self.w2 = nn.Linear(hidden, cfg.dim, bias=False)

    def forward(self, x, mask):
        x = x + self.attn(self.attn_norm(x), mask)
        h = self.ffn_norm(x)
        return x + self.w2(F.silu(self.w1(h)) * self.w3(h))


class CatLM(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.tok = nn.Embedding(cfg.vocab_size, cfg.dim)
        self.blocks = nn.ModuleList(Block(cfg) for _ in range(cfg.n_layers))
        self.norm = RMSNorm(cfg.dim)
        self.head = nn.Linear(cfg.dim, cfg.vocab_size, bias=False)

    def forward(self, idx: torch.Tensor) -> torch.Tensor:
        b, t = idx.shape
        mask = torch.tril(torch.ones(t, t, device=idx.device)).view(1, 1, t, t)
        x = self.tok(idx)
        for blk in self.blocks:
            x = blk(x, mask)
        return self.head(self.norm(x))

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters())

    @torch.no_grad()
    def next_token_logits(self, ids: list[int]) -> torch.Tensor:
        """Logits for the token after `ids` (used by eval and by the sim)."""
        x = torch.tensor([ids[-self.cfg.seq_len:]], dtype=torch.long, device=next(self.parameters()).device)
        return self.forward(x)[0, -1]

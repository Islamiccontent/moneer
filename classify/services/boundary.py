"""مصنّف حدود التقطيع: انحدار لوجستي بأوزان JSON يحكم عند كل فجوة أيُقطع أم لا، بلا اعتماديات."""

import json
import math
import zlib
from functools import lru_cache
from pathlib import Path

BITS = 20
MASK = (1 << BITS) - 1
THRESHOLD = 0.4

PUNCT = set(".،,:؛;!؟?»﴾)]…")
OPENERS = set('«﴿(["“')
CLOSERS = set('»﴾)]"”')

DIAC = dict.fromkeys(range(0x064B, 0x0653), None)
DIAC[0x0670] = None
DIAC[0x0640] = None
_STRIP = "".join(PUNCT) + "".join(OPENERS)


def _h(s: str) -> int:
    """crc32 لا hash(): الأخير يُبذَّر عشوائياً كل تشغيل فتضيع الأوزان."""
    return zlib.crc32(s.encode("utf-8")) & MASK


def _bare(w: str) -> str:
    return w.translate(DIAC).strip(_STRIP)


def _bucket(n: int) -> str:
    return str(n) if n < 6 else ("6-10" if n <= 10 else ("11-20" if n <= 20 else "20+"))


def _feats(words, i, last_cut, depth, tag):
    p, n = words[i - 1], words[i]
    pb, nb = _bare(p), _bare(n)
    pc, nc = p[-1], n[0]
    f = [
        f"pc={pc}",
        f"nc={nc}",
        f"pc_nc={pc}|{nc}",
        f"pw={pb}",
        f"nw={nb}",
        f"pw_pc={pb}|{pc}",
        f"plen={_bucket(len(pb))}",
        f"since={_bucket(i - last_cut)}",
        f"left={_bucket(len(words) - i)}",
        f"depth={min(depth, 2)}",
        f"tag={tag}",
        f"plen_all={_bucket(len(words))}",
        f"abbrev={int(len(pb) <= 1 and pc == '.')}",
        f"ellipsis={int(p.endswith('..') or pc == '…')}",
        f"digit={int(pb[:1].isdigit())}",
    ]
    if i >= 2:
        f.append(f"pp={_bare(words[i - 2])}")
    if i + 1 < len(words):
        f.append(f"nn={_bare(words[i + 1])}")
    return f


def _candidates(words):
    """الفجواتُ التي يُسأل عندها: بعد علامةِ ترقيم، أو قبل افتتاح اقتباس."""
    out, depth = [], 0
    for i in range(1, len(words)):
        prev, nxt = words[i - 1], words[i]
        depth = max(0, depth + sum(c in OPENERS for c in prev) - sum(c in CLOSERS for c in prev))
        if prev[-1] in PUNCT or nxt[0] in OPENERS:
            out.append((i, depth))
    return out


@lru_cache(maxsize=1)
def _weights() -> dict[int, float]:
    path = Path(__file__).resolve().parent.parent / "data" / "boundary_model.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): v for k, v in data["w"].items()}


def available() -> bool:
    return bool(_weights())


def split(text: str, tag: str = "p") -> list[str] | None:
    """يقطّع الفقرة بالنموذج، أو يعيد None إن غاب ملف الأوزان فيتولاها المقطّع الآلي."""
    w = _weights()
    if not w:
        return None
    words = text.split()
    if len(words) < 2:
        return [text.strip()] if text.strip() else None
    last, picks = 0, []
    for i, depth in _candidates(words):
        z = sum(w.get(_h(x), 0.0) for x in _feats(words, i, last, depth, tag))
        if 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z)))) >= THRESHOLD:
            picks.append(i)
            last = i
    out, prev = [], 0
    for c in picks + [len(words)]:
        piece = " ".join(words[prev:c]).strip()
        if piece:
            out.append(piece)
        prev = c
    return out or ([text.strip()] if text.strip() else None)

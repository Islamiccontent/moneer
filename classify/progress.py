"""مخزن حالة تقدم المعالجة الجارية تقرأه الواجهة من /api/segment/progress/."""

import threading
import time

_LOCK = threading.Lock()
_STATE = {"stage": "", "pct": 0, "at": 0.0}


def report(stage: str, pct: int) -> None:
    """يسجل المرحلة الجارية ونسبتها (تُحدّ إلى 0–100)."""
    with _LOCK:
        _STATE.update(stage=str(stage), pct=max(0, min(100, int(pct))), at=time.time())


def snapshot() -> dict:
    """أحدث حالة كما تُعرض للواجهة."""
    with _LOCK:
        return {"stage": _STATE["stage"], "pct": _STATE["pct"]}

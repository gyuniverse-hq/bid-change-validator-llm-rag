# -*- coding: utf-8 -*-
"""HWP v5 (OLE 바이너리) 파서.

직접 바이너리 파싱하지 않는다:
1차 — pyhwp의 hwp5txt (subprocess, `python -m hwp5.hwp5txt`)
2차 — LibreOffice headless (`soffice --headless --convert-to txt`)

두 경로 모두 표 구조를 보존하지 못하므로 parse_status는 최대 "partial"이며
표 추출 실패 사실을 parse_notes에 반드시 기록한다.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .base import make_result

_SOFFICE_CANDIDATES = [
    "soffice",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]


def _run_hwp5txt(path):
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "out.txt")
        env = dict(os.environ, PYTHONUTF8="1")
        proc = subprocess.run(
            [sys.executable, "-m", "hwp5.hwp5txt", "--output", out, str(path)],
            capture_output=True, timeout=300, env=env,
        )
        if proc.returncode != 0 or not os.path.exists(out):
            raise RuntimeError(
                f"hwp5txt 실패 (rc={proc.returncode}): "
                f"{proc.stderr.decode('utf-8', 'replace')[:300]}"
            )
        return Path(out).read_text(encoding="utf-8", errors="replace")


def _run_soffice(path):
    exe = None
    for cand in _SOFFICE_CANDIDATES:
        if shutil.which(cand) or os.path.exists(cand):
            exe = cand
            break
    if exe is None:
        raise RuntimeError("LibreOffice(soffice) 미설치")
    with tempfile.TemporaryDirectory() as td:
        proc = subprocess.run(
            [exe, "--headless", "--convert-to", "txt:Text (encoded):UTF8",
             "--outdir", td, str(path)],
            capture_output=True, timeout=600,
        )
        txts = list(Path(td).glob("*.txt"))
        if proc.returncode != 0 or not txts:
            raise RuntimeError(
                f"soffice 변환 실패 (rc={proc.returncode}): "
                f"{proc.stderr.decode('utf-8', 'replace')[:300]}"
            )
        return txts[0].read_text(encoding="utf-8", errors="replace")


def parse_hwp(path):
    errors = []
    for name, fn in (("hwp5txt", _run_hwp5txt), ("soffice", _run_soffice)):
        try:
            text = fn(path)
            if text.strip():
                return make_result(
                    path, full_text=text, tables=[],
                    parse_status="partial",
                    parse_notes=f"{name} 텍스트 추출 성공 — 단, HWP 바이너리 경로에서는 "
                                f"표 구조가 보존되지 않음(배점표 등은 수동 확인 필요)",
                    fmt="hwp",
                )
            errors.append(f"{name}: 빈 출력")
        except Exception as e:
            errors.append(f"{name}: {e}")
    return make_result(path, parse_status="failed",
                       parse_notes="; ".join(errors), fmt="hwp")

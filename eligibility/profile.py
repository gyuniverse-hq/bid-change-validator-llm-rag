# -*- coding: utf-8 -*-
"""회사 프로필 로드. data/company_profile.json."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "data" / "company_profile.json"


def load_profile(path=None):
    p = Path(path) if path else PROFILE_PATH
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))

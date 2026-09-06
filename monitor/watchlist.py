# -*- coding: utf-8 -*-
"""감시 목록 — 사용자가 지켜보기로 한 공고 저장.

다른 상태 파일(company_profile.json, demo/profiles/*.json)과 같은 패턴으로
data/watchlist.json에 단순 JSON 배열로 저장한다.
"""
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCHLIST_PATH = ROOT / "data" / "watchlist.json"


def _load():
    if not WATCHLIST_PATH.exists():
        return []
    return json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))


def _save(items):
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                              encoding="utf-8")


def list_watched():
    return _load()


def add_bid(bid_no, label=None):
    items = _load()
    if any(i["bid_no"] == bid_no for i in items):
        return items  # 이미 감시 중 — 중복 추가 안 함
    items.append({
        "bid_no": bid_no,
        "label": label or bid_no,
        "added_at": datetime.now().isoformat(timespec="seconds"),
    })
    _save(items)
    return items


def remove_bid(bid_no):
    items = [i for i in _load() if i["bid_no"] != bid_no]
    _save(items)
    return items

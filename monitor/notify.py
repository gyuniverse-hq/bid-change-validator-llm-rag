# -*- coding: utf-8 -*-
"""변경 알림 기록 — `watch`가 감지한 변경사항을 쌓아둔다.

CLI(`python main.py watch`)가 실행될 때마다 append하고, 이후 웹 서버가
이 파일을 읽어 알림 배지로 보여줄 수 있다 (server/api.py에 아직 미연결 —
다음 단계로 남겨둠).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTIFICATIONS_PATH = ROOT / "data" / "notifications.json"

_MAX_KEEP = 200  # 무한정 쌓이지 않도록 최근 N건만 보존


def append_notifications(entries):
    if not entries:
        return
    items = list_notifications()
    items = entries + items  # 최신이 앞에 오도록
    items = items[:_MAX_KEEP]
    NOTIFICATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOTIFICATIONS_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                                  encoding="utf-8")


def list_notifications():
    if not NOTIFICATIONS_PATH.exists():
        return []
    return json.loads(NOTIFICATIONS_PATH.read_text(encoding="utf-8"))


def mark_read(notification_id):
    items = list_notifications()
    changed = False
    for it in items:
        if it.get("id") == notification_id and not it.get("read"):
            it["read"] = True
            changed = True
    if changed:
        NOTIFICATIONS_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    return items

# -*- coding: utf-8 -*-
"""조항 정렬(alignment) — v1 조항 ↔ v2 조항을 **임베딩 유사도**로 매칭.

조항 번호로 매칭하지 않는다: 정정 시 조항이 하나 추가되면 번호가 전부 밀려서
번호 기반 diff는 무의미해진다.
"""
from llm.embeddings import similarity_matrix

# 동일 조항으로 간주할 최소 유사도
_ALIGN_THRESHOLD = 0.60
# 유사도가 이 값 이상이면 "내용까지 동일"로 간주 (변경 없음)
_IDENTICAL_THRESHOLD = 0.995


def align_chunks(old_chunks, new_chunks):
    """반환:
    {
      "pairs": [{"old_id", "new_id", "sim", "changed": bool}],
      "removed_old_ids": [...],   # v2에 대응 없음 (조항 삭제)
      "added_new_ids": [...],     # v1에 대응 없음 (조항 신설)
      "method": "openai"|"ngram",
    }
    """
    if not old_chunks or not new_chunks:
        return {
            "pairs": [],
            "removed_old_ids": [c["chunk_id"] for c in old_chunks],
            "added_new_ids": [c["chunk_id"] for c in new_chunks],
            "method": "none",
        }
    matrix, method = similarity_matrix(
        [c["text"] for c in old_chunks], [c["text"] for c in new_chunks])

    # 탐욕적 최적 매칭: 유사도 내림차순으로 1:1 배정
    cands = []
    for i, row in enumerate(matrix):
        for j, sim in enumerate(row):
            if sim >= _ALIGN_THRESHOLD:
                cands.append((sim, i, j))
    cands.sort(reverse=True)

    used_old, used_new = set(), set()
    pairs = []
    old_texts = {c["chunk_id"]: c["text"] for c in old_chunks}
    new_texts = {c["chunk_id"]: c["text"] for c in new_chunks}
    for sim, i, j in cands:
        oid = old_chunks[i]["chunk_id"]
        nid = new_chunks[j]["chunk_id"]
        if oid in used_old or nid in used_new:
            continue
        used_old.add(oid)
        used_new.add(nid)
        # 텍스트 완전 동일이면 유사도와 무관하게 변경 없음
        identical = old_texts[oid].strip() == new_texts[nid].strip() \
            or sim >= _IDENTICAL_THRESHOLD
        pairs.append({"old_id": oid, "new_id": nid, "sim": round(sim, 4),
                      "changed": not identical})

    removed = [c["chunk_id"] for c in old_chunks if c["chunk_id"] not in used_old]
    added = [c["chunk_id"] for c in new_chunks if c["chunk_id"] not in used_new]
    return {"pairs": pairs, "removed_old_ids": removed,
            "added_new_ids": added, "method": method}

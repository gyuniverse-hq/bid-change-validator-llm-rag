# -*- coding: utf-8 -*-
"""임베딩 유사도 유틸.

- 1차: OpenAI 임베딩 (text-embedding-3-small)
- 폴백: 문자 2-gram 해싱 벡터 (API 키 없음/호출 실패 시에도 파이프라인이 돌게 함)

용도: (1) RFP 조항 ↔ 표준 조항 매칭 (detect 경로 A)
      (2) v1 조항 ↔ v2 조항 정렬 (monitor — 조항 번호 매칭 금지)
"""
import hashlib
import math
import os

from dotenv import load_dotenv

load_dotenv()

EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
_NGRAM_DIM = 4096


def _ngram_vector(text, n=2):
    vec = [0.0] * _NGRAM_DIM
    t = "".join(text.split())
    for i in range(max(0, len(t) - n + 1)):
        gram = t[i:i + n]
        idx = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16) % _NGRAM_DIM
        vec[idx] += 1.0
    return vec


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def embed_texts(texts, allow_fallback=True):
    """(벡터 목록, 사용 방법) 반환. 방법: 'openai' | 'ngram'."""
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            # 입력이 길면 앞부분만 (임베딩 매칭 용도로 충분)
            trimmed = [t[:4000] if t else " " for t in texts]
            resp = client.embeddings.create(model=EMBED_MODEL, input=trimmed)
            return [d.embedding for d in resp.data], "openai"
        except Exception:
            if not allow_fallback:
                raise
    if not allow_fallback:
        raise RuntimeError("OPENAI_API_KEY 미설정")
    return [_ngram_vector(t) for t in texts], "ngram"


def similarity_matrix(texts_a, texts_b):
    """texts_a x texts_b 코사인 유사도 행렬. (matrix, method) 반환."""
    vecs, method = embed_texts(list(texts_a) + list(texts_b))
    va = vecs[:len(texts_a)]
    vb = vecs[len(texts_a):]
    matrix = [[cosine(a, b) for b in vb] for a in va]
    return matrix, method

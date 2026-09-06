# -*- coding: utf-8 -*-
"""LLM provider 추상화.

역할 분리 (절대 원칙 — 근거는 검색이, 판정은 코드가, LLM은 서술만):
- role="sol"  (OPENAI_MODEL_HIGH, GPT-5.6 Sol)  — 골든셋 생성 전용. 개발 단계 1회성.
                런타임 파이프라인에서 호출 금지.
- role="luna" (OPENAI_MODEL_DEFAULT, GPT-5.6 Luna) — 런타임 서술·슬롯추출 전용.

LLM에게 판정·숫자 변환을 맡기지 않는다. LLM의 역할은
(1) 코드가 확정한 결과를 문장으로 풀어쓰기, (2) 산문 -> 정형 필드 변환뿐이다.
"""
import json
import os

from dotenv import load_dotenv

load_dotenv()

_ROLE_ENV = {
    "luna": ("OPENAI_MODEL_DEFAULT", "gpt-5.6-luna"),
    "sol": ("OPENAI_MODEL_HIGH", "gpt-5.6-sol"),
}


class LLMClient:
    """OpenAI 호환 provider. 다른 provider로 교체 시 이 클래스만 구현을 바꾼다."""

    def __init__(self, role="luna"):
        if role not in _ROLE_ENV:
            raise ValueError(f"role은 {list(_ROLE_ENV)} 중 하나여야 함: {role}")
        self.role = role
        env_key, default = _ROLE_ENV[role]
        self.model = os.getenv(env_key, default)
        self.api_key = os.getenv("OPENAI_API_KEY")
        self._client = None

    @property
    def available(self):
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
        return self._client

    def chat(self, system, user, json_schema=None, temperature=None):
        # temperature 기본 None: GPT-5.6 계열은 기본값(1) 외 temperature를 지원하지 않음
        """일반 대화 호출. json_schema를 주면 structured output을 강제한다
        (스키마 이탈을 디코딩 단계에서 차단)."""
        if not self.available:
            raise RuntimeError("OPENAI_API_KEY 미설정 — LLM 호출 불가")
        client = self._get_client()
        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": json_schema.get("name", "result"),
                    "strict": True,
                    "schema": json_schema["schema"],
                },
            }
        resp = client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content
        if json_schema is not None:
            return json.loads(content)
        return content


def get_client(role="luna"):
    return LLMClient(role=role)

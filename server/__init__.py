"""로컬 데모 서버 — 브라우저 페이지가 실제 파이프라인(파서·탐지·Luna 호출)을 호출하는 브리지.

Claude Artifact는 CSP 때문에 임의의 localhost로 fetch를 보낼 수 없다.
그래서 이 서버는 브라우저에서 직접 여는 `server/static/index.html`과 짝을 이루며,
Artifact가 아니라 사용자 PC에서 `python main.py serve`로 띄우는 진짜 로컬 서버다.
"""

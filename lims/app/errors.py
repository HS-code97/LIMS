"""업무 오류 (main.py 예외 처리기가 HTTP 상태로 바꿈). 모델·서비스 어디서나 쓰도록 의존성 없이 둡니다."""
from __future__ import annotations


class Conflict(Exception):
    """번호 충돌 (409)."""

    def __init__(self, message: str, items: list[str]):
        super().__init__(message)
        self.items = items


class Invalid(ValueError):
    """입력 오류 (422)."""

    def __init__(self, message: str, items: list[str] | None = None):
        super().__init__(message)
        self.items = items or []

"""시편체계 안내(`시편번호 체계.md` v3.1을 그림으로 설명하는 화면)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..auth import require_user
from ..models import User
from ..services.marking import STAGES, coil_code_candidates
from ..web import render

router = APIRouter()

# 화면의 코일코드 예시(3.5절)는 실제 제안 함수로 계산해 규칙과 어긋나지 않게 합니다.
DEMO_COIL = "CQV3141T"


@router.get("/guide/numbering")
def numbering_guide(request: Request, user: User = Depends(require_user)):
    return render(request, "numbering_guide.html", nav="guide", STAGES=STAGES,
                  demo_coil=DEMO_COIL, coil_candidates=coil_code_candidates(DEMO_COIL))

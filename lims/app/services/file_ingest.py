"""파일 수집·자동 매칭 (7장 P5).

파일명 규칙(권장): {약식번호}_{태그}_{자유}.{확장자}
  26P4-C0102_W03_front.jpg      → C0102 시편, 회차 3
  26P4-S0102_SEM_x5000_bse.tif  → S0102 시편, SEM
"""
from __future__ import annotations

import glob
import hashlib
import re
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import FILES_DIR
from ..models import Attachment, Specimen, TestResult, TestRun
from .thumbnails import make_thumbnails

SHORT_ID = re.compile(r"(?P<proj>\d{2}[A-Z][0-9A-Z])-(?P<stage>[PCS])(?P<serial>\d{4})")
CYCLE = re.compile(r"_(?:W|C)(?P<n>\d{1,3})(?=[_.])")
SAFE = re.compile(r"[^0-9A-Za-z가-힣._()\-]+")


@dataclass
class ParsedName:
    short_id: str | None
    cycle: int | None
    tags: list[str] = field(default_factory=list)


def parse_filename(name: str) -> ParsedName:
    up = Path(name).name.upper()
    m = SHORT_ID.search(up)
    c = CYCLE.search(up)
    stem = Path(up).stem
    tags = [t for t in stem.split("_")[1:] if t]
    return ParsedName(m.group(0) if m else None, int(c.group("n")) if c else None, tags)


def kind_of(name: str, tags: list[str]) -> str:
    ext = Path(name).suffix.lower()
    if "SEM" in tags or ext in (".tif", ".tiff") and any(t.startswith("X") and t[1:].isdigit() for t in tags):
        return "SEM"
    if ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff"):
        return "PHOTO"
    if ext in (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xlsx", ".xls"):
        return "DOC"
    return "RAW"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class IngestResult:
    name: str
    status: str                  # matched / unmatched / duplicate
    attachment_id: int | None = None
    short_id: str | None = None
    cycle: int | None = None
    message: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _store(tmp: Path, sha: str, original: str, short_id: str | None) -> tuple[Path, Path | None]:
    folder = FILES_DIR / f"{date.today():%Y}" / (short_id or "_unsorted")
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{sha[:12]}_{SAFE.sub('_', Path(original).name)}"
    shutil.move(str(tmp), dest)
    return dest, make_thumbnails(dest)


def rel(p: Path | None) -> str | None:
    return p.relative_to(FILES_DIR).as_posix() if p else None


def ingest(db: Session, tmp: Path, original_name: str, **kw) -> IngestResult:
    """임시 파일 1개를 해시 검사 → 매칭 → 저장·썸네일 → attachments 기록.
    도중에 실패하면(예: 업로드와 폴더 감시가 같은 파일을 동시에 넣어 해시 UNIQUE 위반) 임시 파일과
    이미 옮긴 원본·썸네일을 지워, DB 행 없는 고아 파일이 남지 않게 합니다."""
    stored: list[Path] = []
    try:
        return _ingest(db, tmp, original_name, stored, **kw)
    except BaseException:
        tmp.unlink(missing_ok=True)
        for p in stored:
            p.unlink(missing_ok=True)
        raise


def _ingest(db: Session, tmp: Path, original_name: str, stored: list[Path], *, user_id: int | None,
            test_run: TestRun | None = None, source: str = "upload",
            default_spec: Specimen | None = None, auto_test_run: bool = False) -> IngestResult:
    """default_spec: 시편 상세 화면에서 올린 경우, 파일명에 약식번호가 없으면 이 시편에 연결."""
    sha = sha256_of(tmp)
    dup = db.scalar(select(Attachment).where(Attachment.sha256 == sha))
    if dup is not None and dup.is_deleted:
        # 실수로 지운 파일을 다시 올리면 되살립니다 (원본은 논리 삭제라 그대로 있음, D-20)
        tmp.unlink(missing_ok=True)
        dup.is_deleted = False
        where = dup.specimen.short_id if dup.specimen else None
        return IngestResult(original_name, "matched" if where else "unmatched", dup.id, where,
                            message=f"삭제했던 파일을 되살렸습니다 ({where or '미분류함'})")
    if dup is not None:
        tmp.unlink(missing_ok=True)
        where = dup.specimen.short_id if dup.specimen else "미분류함"
        return IngestResult(original_name, "duplicate", dup.id, dup.specimen.short_id if dup.specimen else None,
                            message=f"같은 파일이 이미 있습니다 ({where}, {dup.original_name})")

    parsed = parse_filename(original_name)
    spec = None
    if parsed.short_id:
        spec = db.scalar(select(Specimen).where(Specimen.short_id == parsed.short_id,
                                                Specimen.is_deleted.is_(False)))
    elif default_spec is not None:
        spec = default_spec
    if spec is not None and test_run is None and auto_test_run and parsed.cycle is not None:
        # 폴더 감시 등 시험런 화면 밖 경로: 진행 중 시험런 하나에만 탑승해 있으면 그 회차 셀에 연결
        from ..models import RunSpecimen
        running = db.scalars(select(TestRun).join(RunSpecimen).where(
            RunSpecimen.specimen_id == spec.id, RunSpecimen.unloaded_at.is_(None), TestRun.status == "RUNNING")).all()
        if len(running) == 1:
            test_run = running[0]
    result = None
    msg = ""
    if spec and test_run is not None and parsed.cycle is not None:
        boarded = any(b.specimen_id == spec.id for b in test_run.boardings)
        if boarded:
            result = db.scalar(select(TestResult).where(TestResult.test_run_id == test_run.id,
                                                        TestResult.specimen_id == spec.id,
                                                        TestResult.cycle_no == parsed.cycle))
            if result is None:
                result = TestResult(test_run_id=test_run.id, specimen_id=spec.id, cycle_no=parsed.cycle,
                                    template_id=test_run.template_id, metrics={}, inspector_id=user_id,
                                    eval_date=date.today())
                db.add(result)
                db.flush()
            if (test_run.cycles or 0) <= parsed.cycle:
                test_run.cycles = parsed.cycle + 1
        else:
            msg = f"{spec.short_id}은 {test_run.test_run_no}에 탑승하지 않아 시편에만 연결했습니다."

    dest, thumb = _store(tmp, sha, original_name, spec.short_id if spec else None)
    stored += [dest, *dest.parent.glob(f"{glob.escape(dest.stem)}.w*.webp")]
    att = Attachment(specimen_id=spec.id if spec else None, result_id=result.id if result else None,
                     process_run_id=spec.process_run_id if spec else None,
                     kind=kind_of(original_name, parsed.tags), path=rel(dest), thumb_path=rel(thumb),
                     original_name=Path(original_name).name, sha256=sha, size_bytes=dest.stat().st_size,
                     source=source, uploaded_by=user_id)
    db.add(att)
    db.flush()
    if spec is None:
        why = "파일명에서 약식번호를 찾지 못했습니다" if not parsed.short_id else f"{parsed.short_id} 시편이 없습니다"
        return IngestResult(original_name, "unmatched", att.id, None, parsed.cycle, f"미분류함으로 이동 — {why}")
    return IngestResult(original_name, "matched", att.id, spec.short_id, parsed.cycle if result else None, msg)


def link(db: Session, att: Attachment, spec: Specimen, result: TestResult | None = None) -> None:
    """미분류 파일을 시편(·결과)에 연결. 파일은 시편 폴더로 옮깁니다."""
    src = FILES_DIR / att.path
    folder = FILES_DIR / f"{date.today():%Y}" / spec.short_id
    folder.mkdir(parents=True, exist_ok=True)
    if src.exists() and src.parent != folder:
        dest = folder / src.name
        shutil.move(str(src), dest)
        att.path = rel(dest)
        if att.thumb_path:
            for w in ("w400", "w1600"):
                t = src.with_name(f"{src.stem}.{w}.webp")
                if t.exists():
                    shutil.move(str(t), folder / t.name)
            att.thumb_path = rel(folder / f"{dest.stem}.w400.webp")
    att.specimen_id = spec.id
    att.process_run_id = spec.process_run_id
    if result is not None:
        att.result_id = result.id

"""과거 엑셀 데이터 일괄 가져오기 (2단계). 양식은 app/services/excel_import.py 머리말 참조.

사용:  python -m scripts.import_excel 파일.xlsx --user hhs            (미리보기: 검증만, 저장 안 함)
       python -m scripts.import_excel 파일.xlsx --user hhs --commit   (저장)
       python -m scripts.import_excel --template 양식.xlsx            (빈 양식 만들기)
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, current_user_id  # noqa: E402
from app.models import User  # noqa: E402
from app.services.excel_import import run_import, template_workbook  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--template")
    a = ap.parse_args()
    if a.template:
        Path(a.template).write_bytes(template_workbook())
        print(a.template)
        return
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.emp_no == a.user))
        current_user_id.set(uid)
        rep = run_import(db, Path(a.file).read_bytes(), uid, dry_run=not a.commit)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    sys.exit(1 if rep["errors"] else 0)


if __name__ == "__main__":
    main()

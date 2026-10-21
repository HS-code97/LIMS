# 개발 서버 실행 (Windows): .\run_dev.ps1  → http://localhost:8610
# 처음 한 번: py -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt
#            cd lims; ..\.venv\Scripts\python.exe -m scripts.demo   (기준 시나리오 데모 데이터)
Set-Location $PSScriptRoot
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir lims --port 8610

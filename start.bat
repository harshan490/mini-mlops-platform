@echo off
setlocal
cd /d "%~dp0"
echo === Mini MLOps Platform ===
if not exist backend\venv\Scripts\python.exe (
  echo Creating Python venv...
  py -3.11 -m venv backend\venv || python -m venv backend\venv
)
backend\venv\Scripts\python.exe -c "import fastapi, sqlmodel, psutil, xgboost, apscheduler" 2>nul || backend\venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if not exist frontend\node_modules (
  pushd frontend && call npm install && popd
)
pushd backend && venv\Scripts\python.exe -m app.seed && popd
start "Mini MLOps API" cmd /k "cd /d %~dp0backend && venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-dir app --port 8000"
start "Mini MLOps UI" cmd /k "cd /d %~dp0frontend && npm run dev"
timeout /t 6 >nul
start "" http://localhost:5173

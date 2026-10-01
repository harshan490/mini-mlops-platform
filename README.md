# Mini MLOps Platform

Upload data, train models live, register, deploy, predict, and monitor drift, all from one glass-style HUD.

## Run
Double-click `start.bat` (installs anything missing, seeds demo data, starts both servers, opens http://localhost:5173).

Manual:
```
cd backend && venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
cd frontend && npm run dev
```
API docs: http://localhost:8000/docs. Reset the demo (stop the server first): `cd backend && venv\Scripts\python.exe -m app.seed --reset`.

## Architecture
```
React 18 + Vite (frontend/)  --/api, /ws, /serve-->  FastAPI (backend/app)
  R3F cosmic background, GSAP, Recharts, React Flow     |- trainer   (real per-epoch training, WS progress)
                                                         |- registry  (versioned artifacts, stages, lineage)
                                                         |- serving   (in-process replicas, autoscaler)
                                                         |- drift     (PSI vs training distribution)
                                                         |- alerts    (error rate, P95, drift, recovery)
                                                         |- pipeline  (YAML DAG, parallel branches, cron)
                                                         SQLite (mlops.db) + storage/{datasets,models,runs}
```
Team pages: `/users/harshan` and `/users/abishek` (sidebar "Team" avatars). The acting member is picked from the avatar menu; every upload, run, registration and deployment is credited to them.

## 5-minute demo script
1. **Datasets**: drop a CSV on the upload box; it is profiled and quality-scored.
2. **Experiments**: pick XGBoost + `travel_recommend`, Start Training; watch loss/accuracy stream live (GPU).
3. Click two runs in the table to compare their metrics; use **Auto Tune** for a 6-trial search.
4. **Register as Model**, then in **Model Registry** set the version to Production.
5. **Deploy to Production** → you land on Deployments.
6. **Try it**: edit the JSON, Predict → prediction, probabilities, latency.
7. **Simulate traffic** (and **Simulate drift**).
8. **Monitoring**: requests and latency charts move; drift > 0.25 fires an alert (toast + bell).
9. **Pipelines**: Run Pipeline → the DAG executes validate → preprocess → features → XGBoost ‖ MLP → evaluate → register → deploy.

## Honest notes
- LSTM / BERT / YOLOv8 rows are seeded history (PyTorch is not installed); everything trained with RF / XGBoost / Logistic Regression / MLP is real.
- Seeded prediction logs and 48 h of host metrics fill the charts on first launch; live values come from psutil / NVML.
- Training adds a small per-epoch pace (Settings → training.pace_ms, default 120 ms) so progress is visible.

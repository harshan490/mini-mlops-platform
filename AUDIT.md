# Mini MLOps Platform — Phase 0 Audit

Audit date: 2026-09-30. Scope: everything in `MLOPS CCP/` except `node_modules`,
`venv`, `__pycache__`, `.next` and the Office/PowerPoint documents.

## 1. What existed before the rebuild

| Layer | Found | Notes |
|---|---|---|
| Frontend | **Next.js 16 (App Router) + React 19 + Tailwind 4**, shadcn, Chart.js, Recharts, GSAP, framer-motion | 7 pages (`/`, `/datasets`, `/experiments`, `/models`, `/training`, `/deployment`, `/monitoring`), ~3,100 lines. Almost all numbers came from a hard-coded mock store (`src/lib/dataStore.ts`). Own nested git repo (`frontend/.git`, one "Create Next App" commit plus uncommitted work). |
| Backend | **FastAPI + SQLAlchemy** (not SQLModel), Alembic, JWT auth (python-jose + passlib) | 8 routers. Real: dataset CSV/XLSX upload with row/column count, a Random Forest fit in `/api/training/run`. Mocked: predictions (`random.uniform`), monitoring (constants), MLflow URIs (fake `s3://` strings). `dashboard.py` had a crash bug (`is not null`). No WebSockets, no background jobs, no model artifacts on disk. |
| Database | `backend/mlops.db` (SQLite, 5 tables: users, datasets, experiments, models, deployments) | Config defaulted to PostgreSQL, session to SQLite. |
| ML code | RF classifier/regressor on numeric columns (`training.py`), algorithm catalogue (`models.py`) | Reused as the starting point for `services/trainer.py`. |
| Infra | `docker-compose.yml` (Postgres, MLflow, MinIO, Prometheus, Grafana), `docker/prometheus.yml` scraping `:8000/metrics` | Kept. The new backend serves `/metrics` so the Prometheus job works. |
| Python env | `backend/venv`, Python 3.11.0 | Had fastapi, sqlalchemy, pandas, scikit-learn 1.9, xgboost 3.2, mlflow, cryptography, pyarrow. Added: sqlmodel, psutil, nvidia-ml-py, apscheduler, pytest. **torch is not installed**, so LSTM/BERT/YOLO rows are seeded history, never retrained. |
| Hardware | NVIDIA GeForce RTX 3050 6 GB Laptop GPU | Read by `pynvml` for real GPU stats. |

## 2. Stack: what exists vs. what the target needs

| Target | Existing | Decision |
|---|---|---|
| Vite + React 18 + TS | Next.js 16 + React 19 | **Rebuild in `/frontend`.** The target stack, the Vite proxy requirement and React Router v6 all name Vite explicitly; the old pages were mock-data screens that match none of the 8 mockups. The Next app is preserved untouched in `_legacy/frontend-next/`. |
| Tailwind 3 + tokens | Tailwind 4 (CSS-first) | New `tailwind.config.ts` + `src/styles/tokens.css`. |
| Zustand, TanStack Query | none | Add. |
| GSAP 3 + @gsap/react | gsap present, unused | Add `@gsap/react`, ScrollTrigger. |
| three + R3F + drei + postprocessing | none | Add (fiber 8 / drei 9 / postprocessing 2 — the React 18 line). |
| Recharts | present | Keep (v2 API). |
| React Flow (@xyflow/react) | none | Add. |
| FastAPI | present | Keep. |
| SQLModel + SQLite | SQLAlchemy + SQLite/Postgres | Rewrite models in SQLModel. |
| WebSockets | none | `/ws/system`, `/ws/runs/{id}`, `/ws/pipelines/{run_id}`. |
| Background jobs | none | `ThreadPoolExecutor` job manager with cooperative cancel. |
| psutil / pynvml | none | Real CPU / RAM / GPU sampling every 10 s. |
| Fernet key storage | none | API keys encrypted; key in `backend/.env`. |

## 3. Per-page gap table

| Page | Component | Exists? | Matches mockup? | Backend wired? | Action |
|---|---|---|---|---|---|
| Shell | Sidebar, top bar, clock, bell, avatar | Partly (Next layout) | No | No | Rebuild |
| Shell | Cosmic WebGL background | `NeuralCanvas3D` (different scene) | No | — | Rebuild (R3F) |
| Dashboard | Hero, 3D stat cards, orbit ring | No | — | — | Build |
| Dashboard | Global search / Ctrl+K palette | No | — | No | Build + `/api/search` |
| Dashboard | Active pipeline (live) | Mock card | No | No | Build + WS |
| Dashboard | Model performance chart | Mock chart | No | No | Build |
| Dashboard | Recent experiments | Mock list | Partly | Partly | Rebuild |
| Dashboard | System health gauges + sparklines | No | — | No | Build + psutil |
| Datasets | Stats, table, filters, bulk delete, ⋯ menu | Basic table | No | List only | Rebuild |
| Datasets | Detail panel, versions, tags, preview | No | — | No | Build |
| Datasets | Upload (CSV / ZIP / Parquet) + profiling | CSV/XLSX upload, rows/cols only | No | Partly | Rebuild + quality score |
| Datasets | Growth chart, types donut, recent uploads | No | — | No | Build |
| Experiments | Live training run + charts | No | — | No | Build (real training, WS) |
| Experiments | Hyperparameters, Start, Auto Tune, Stop | Form on `/training` | No | Blocking RF only | Rebuild |
| Experiments | Run details, table, compare, recent runs, metrics | Basic list | No | List only | Rebuild |
| Models | Registry table, register modal, stages | Basic list | No | List only | Rebuild |
| Models | Tabs (overview/metrics/artifacts/lineage/settings) | No | — | No | Build |
| Deployments | Real serving, replicas, autoscaling | Mock predict | No | Fake | Rebuild (in-process serving) |
| Deployments | Try-it, simulate, logs, rollback | Mock form | No | Fake | Build |
| Pipelines | DAG / list / YAML views, run, schedule | No | — | No | Build |
| Monitoring | KPIs, charts, drift (PSI), alerts | Mock panels | No | Constants | Rebuild |
| Settings | All 8 cards incl. API keys, integrations | No | — | No | Build |
| **Users (new)** | **Harshan and Abishek profile pages** | No | — (not in mockups) | No | **Build** — same visual language; every entity gets an owner |

## 4. Reusable code kept

- `training.py` fit logic (numeric-feature RF) → generalised in `services/trainer.py`.
- Algorithm catalogue from `models.py` → `trainer.ALGORITHMS`.
- JWT approach from `core/security.py` (python-jose HS256). Password hashing switches
  to `hashlib.pbkdf2_hmac` because passlib 1.7.4 is incompatible with the installed bcrypt 5.
- `docker-compose.yml` and `docker/prometheus.yml`, unchanged.

## 5. Where the old code went

Nothing was deleted. Superseded code was moved:

| From | To |
|---|---|
| `frontend/` (Next.js app, its nested `.git`, `node_modules`, `.next`) | `_legacy/frontend-next/` |
| `backend/main.py`, `backend/app/{api,core,db,models}`, `alembic/`, `alembic.ini`, `mlops.db` | `_legacy/backend-v1/` |

The snapshot commit `3dec4a3d3` holds the backend's previously uncommitted work.
During the frontend move, Windows fell back to copy-then-delete; every file was
verified afterwards (47 inner-git files, 25 source files, 1,054 `.next` files,
41,820 `node_modules` files all present at the destination).

## 6. Additions beyond the mockups

1. **Two user pages** — `/users/harshan` and `/users/abishek`. Each is a profile with
   stats, a 30-day activity chart, contribution mix, the member's own experiments,
   models, deployments and an activity feed. The acting user is chosen from the
   avatar menu; every create/update action is attributed to that user.
2. `/metrics` (Prometheus text format) so the existing Prometheus scrape job works.

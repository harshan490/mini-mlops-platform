"""Pipeline DAG execution. Every step runs real code; parallel branches run concurrently."""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any, Optional

import numpy as np
import pandas as pd
import yaml
from sqlmodel import select

from app.config import PIPELINES_DIR
from app.db import session_scope
from app.models import Dataset, DatasetVersion, Deployment, Pipeline, PipelineLog, PipelineRun, Run
from app.services import registry, storage
from app.services.activity import log_activity, raise_alert
from app.services.deploy import deploy_version
from app.services.features import load_frame
from app.services.hub import hub
from app.services.trainer import ALGORITHMS, normalise_params, trainer
from app.utils import iso, to_jsonable, utcnow

NODE_TYPES = ["validate", "preprocess", "features", "train", "evaluate", "register", "deploy"]
ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")


class PipelineSpecError(ValueError):
    pass


def parse_spec(text: str) -> dict[str, Any]:
    try:
        spec = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PipelineSpecError(f"Invalid YAML: {exc}") from exc
    if not isinstance(spec, dict):
        raise PipelineSpecError("Pipeline YAML must be a mapping")
    for key in ("name", "dataset"):
        if not isinstance(spec.get(key), str) or not spec[key].strip():
            raise PipelineSpecError(f"'{key}' is required")
    version = str(spec.get("version", "v1.0.0"))
    if not re.fullmatch(r"v\d+\.\d+\.\d+", version):
        raise PipelineSpecError("version must look like v1.2.3")
    spec["version"] = version
    nodes = spec.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise PipelineSpecError("'nodes' must be a non-empty list")
    ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise PipelineSpecError("each node must be a mapping")
        nid = node.get("id")
        if not isinstance(nid, str) or not ID_RE.match(nid):
            raise PipelineSpecError(f"invalid node id: {nid!r} (lowercase letters, digits, _ or -)")
        if nid in ids:
            raise PipelineSpecError(f"duplicate node id: {nid}")
        ids.add(nid)
        if node.get("type") not in NODE_TYPES:
            raise PipelineSpecError(f"node {nid}: type must be one of {NODE_TYPES}")
        node.setdefault("name", nid.replace("_", " ").title())
        node.setdefault("version", version)
        deps = node.setdefault("depends_on", [])
        if not isinstance(deps, list):
            raise PipelineSpecError(f"node {nid}: depends_on must be a list")
        params = node.setdefault("params", {})
        if not isinstance(params, dict):
            raise PipelineSpecError(f"node {nid}: params must be a mapping")
        if node["type"] == "train":
            algo = params.get("algorithm")
            if algo not in ALGORITHMS:
                raise PipelineSpecError(f"node {nid}: params.algorithm must be one of {list(ALGORITHMS)}")
            try:
                normalise_params(algo, params)
            except ValueError as exc:
                raise PipelineSpecError(f"node {nid}: {exc}") from exc
        if node["type"] == "register" and not str(params.get("model_name", "")).strip():
            raise PipelineSpecError(f"node {nid}: params.model_name is required")
    for node in nodes:
        for dep in node["depends_on"]:
            if dep not in ids:
                raise PipelineSpecError(f"node {node['id']} depends on unknown node {dep}")
    # cycle check (Kahn)
    indeg = {n["id"]: len(n["depends_on"]) for n in nodes}
    children: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for n in nodes:
        for dep in n["depends_on"]:
            children[dep].append(n["id"])
    queue = [nid for nid, d in indeg.items() if d == 0]
    seen = 0
    while queue:
        cur = queue.pop()
        seen += 1
        for child in children[cur]:
            indeg[child] -= 1
            if indeg[child] == 0:
                queue.append(child)
    if seen != len(nodes):
        raise PipelineSpecError("pipeline graph has a cycle")
    return spec


def dump_spec(spec: dict[str, Any]) -> str:
    return yaml.safe_dump(spec, sort_keys=False, allow_unicode=True)


class NodeStopped(Exception):
    pass


class PipelineRunner:
    def __init__(self) -> None:
        self._cancel: dict[int, threading.Event] = {}
        self._node_cancel: dict[tuple[int, str], threading.Event] = {}
        self._node_runs: dict[tuple[int, str], int] = {}
        self._state_lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pipeline")
        self.scheduler = None

    # ----------------------------------------------------------------- public
    def start(self, pipeline_id: int, triggered_by: str, actor_id: Optional[int], version: Optional[str] = None) -> PipelineRun:
        with session_scope() as s:
            pipe = s.get(Pipeline, pipeline_id)
            if pipe is None:
                raise LookupError("Pipeline not found")
            yaml_text = pipe.yaml
            if version and version != pipe.version:
                from app.models import PipelineVersion

                pv = s.exec(select(PipelineVersion).where(PipelineVersion.pipeline_id == pipeline_id,
                                                          PipelineVersion.version == version)).first()
                if pv is None:
                    raise LookupError(f"Version {version} not found")
                yaml_text = pv.yaml
            spec = parse_spec(yaml_text)
            running = s.exec(select(PipelineRun).where(PipelineRun.pipeline_id == pipeline_id,
                                                       PipelineRun.status.in_(["Queued", "Running"]))).first()
            if running:
                raise ValueError(f"Run #{running.number} of this pipeline is still active")
            last = s.exec(select(PipelineRun.number).order_by(PipelineRun.number.desc())).first() or 0
            nodes = {n["id"]: {"status": "pending", "name": n["name"], "type": n["type"], "version": n["version"],
                               "started_at": None, "finished_at": None, "duration_s": None, "progress": 0,
                               "message": "", "artifacts": [], "run_id": None} for n in spec["nodes"]}
            run = PipelineRun(pipeline_id=pipeline_id, number=last + 1, version=spec["version"], yaml_snapshot=yaml_text,
                              triggered_by=triggered_by, status="Queued", nodes=nodes, owner_id=actor_id,
                              started_at=utcnow())
            s.add(run)
            s.commit()
            s.refresh(run)
            pipe_name = pipe.name
        self._cancel[run.id] = threading.Event()
        log_activity(actor_id, "pipeline", "run", f"Started {pipe_name} run #{run.number} ({triggered_by})", f"/pipelines?run={run.id}")
        self.pool.submit(self._safe_execute, run.id)
        return run

    def stop(self, run_id: int) -> bool:
        ev = self._cancel.get(run_id)
        if ev is None:
            return False
        ev.set()
        with self._state_lock:
            keys = [k for k in self._node_runs if k[0] == run_id]
        for key in keys:
            trainer.stop(self._node_runs[key])
        return True

    def stop_node(self, run_id: int, node_id: str) -> bool:
        key = (run_id, node_id)
        ev = self._node_cancel.get(key)
        if ev is None:
            return False
        ev.set()
        if key in self._node_runs:
            trainer.stop(self._node_runs[key])
        return True

    def recover_interrupted(self) -> None:
        with session_scope() as s:
            for run in s.exec(select(PipelineRun).where(PipelineRun.status.in_(["Queued", "Running"]))).all():
                run.status = "Failed"
                run.finished_at = utcnow()
                nodes = dict(run.nodes)
                for nid, st in nodes.items():
                    if st.get("status") in ("pending", "running"):
                        nodes[nid] = {**st, "status": "failed", "message": "Interrupted by server restart"}
                run.nodes = nodes
                s.add(run)
            s.commit()

    # ---------------------------------------------------------------- helpers
    def _log(self, run_id: int, node: str, message: str, level: str = "INFO") -> None:
        ts = utcnow()
        with session_scope() as s:
            s.add(PipelineLog(run_id=run_id, ts=ts, level=level, node=node, message=message))
            s.commit()
        hub.publish(f"pipeline:{run_id}", {"type": "log", "ts": iso(ts), "level": level, "node": node, "message": message})

    def _update_node(self, pipeline_run_id: int, node_id: str, /, **fields: Any) -> None:
        """Merge ``fields`` into a node's state (fields may include the node's training ``run_id``)."""
        with self._state_lock:
            with session_scope() as s:
                run = s.get(PipelineRun, pipeline_run_id)
                nodes = dict(run.nodes)
                nodes[node_id] = {**nodes[node_id], **to_jsonable(fields)}
                run.nodes = nodes
                s.add(run)
                s.commit()
                state = nodes[node_id]
        hub.publish(f"pipeline:{pipeline_run_id}", {"type": "node", "node": node_id, **state})

    def _safe_execute(self, run_id: int) -> None:
        try:
            self._execute(run_id)
        except Exception as exc:  # noqa: BLE001
            with session_scope() as s:
                run = s.get(PipelineRun, run_id)
                run.status = "Failed"
                run.finished_at = utcnow()
                s.add(run)
                s.commit()
            self._log(run_id, "pipeline", f"Pipeline crashed: {exc}", "ERROR")
            hub.publish(f"pipeline:{run_id}", {"type": "run", "status": "Failed"})

    # --------------------------------------------------------------- executor
    def _execute(self, run_id: int) -> None:
        cancel = self._cancel.setdefault(run_id, threading.Event())
        with session_scope() as s:
            run = s.get(PipelineRun, run_id)
            pipe = s.get(Pipeline, run.pipeline_id)
            spec = parse_spec(run.yaml_snapshot)
            run.status = "Running"
            run.started_at = utcnow()
            s.add(run)
            s.commit()
            ds = s.exec(select(Dataset).where(Dataset.name == spec["dataset"])).first()
            if ds is None:
                raise ValueError(f"Dataset '{spec['dataset']}' not found")
            dv = s.exec(select(DatasetVersion).where(DatasetVersion.dataset_id == ds.id,
                                                     DatasetVersion.version == ds.current_version)).first()
            ctx: dict[str, Any] = {
                "pipeline": pipe.name, "number": run.number, "owner_id": run.owner_id, "dataset_id": ds.id,
                "dataset_name": ds.name, "dataset_version": ds.current_version,
                "target": spec.get("target") or ds.target_column,
                "source_path": storage.resolve(dv.file_path) if dv and dv.file_path else None,
                "run_dir": PIPELINES_DIR / f"run-{run_id}", "train_runs": {},
            }
        ctx["run_dir"].mkdir(parents=True, exist_ok=True)
        hub.publish(f"pipeline:{run_id}", {"type": "run", "status": "Running"})
        self._log(run_id, "pipeline", f"Run #{ctx['number']} of {ctx['pipeline']} {spec['version']} started on {ctx['dataset_name']} v{ctx['dataset_version']}")
        t_run = time.perf_counter()

        nodes = {n["id"]: n for n in spec["nodes"]}
        status: dict[str, str] = {nid: "pending" for nid in nodes}
        remaining = list(nodes)
        futures: dict[Future, str] = {}
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix=f"prun-{run_id}") as pool:
            while remaining or futures:
                launched = False
                for nid in list(remaining):
                    deps = nodes[nid]["depends_on"]
                    if any(status[d] in ("pending", "running") for d in deps):
                        continue
                    remaining.remove(nid)
                    dep_status = [status[d] for d in deps]
                    ready = all(st == "success" for st in dep_status) or (
                        nodes[nid]["type"] == "evaluate" and any(st == "success" for st in dep_status))
                    if cancel.is_set():
                        status[nid] = "stopped"
                        self._update_node(run_id, nid, status="stopped", message="Pipeline stopped")
                        continue
                    if not ready:
                        status[nid] = "skipped"
                        self._update_node(run_id, nid, status="skipped", message="Upstream step did not succeed")
                        self._log(run_id, nodes[nid]["name"], "Skipped: upstream step did not succeed", "WARN")
                        continue
                    status[nid] = "running"
                    self._node_cancel[(run_id, nid)] = threading.Event()
                    self._update_node(run_id, nid, status="running", started_at=iso(utcnow()), progress=0)
                    futures[pool.submit(self._run_node, run_id, nodes[nid], ctx, status)] = nid
                    launched = True
                if not futures:
                    if remaining and not launched:
                        raise RuntimeError("Pipeline scheduler stalled")
                    continue
                done, _ = wait(list(futures), return_when=FIRST_COMPLETED)
                for fut in done:
                    nid = futures.pop(fut)
                    node = nodes[nid]
                    try:
                        result = fut.result()
                        status[nid] = "success"
                        self._update_node(run_id, nid, status="success", finished_at=iso(utcnow()), progress=100, **result)
                    except NodeStopped:
                        status[nid] = "stopped"
                        self._update_node(run_id, nid, status="stopped", finished_at=iso(utcnow()), message="Stopped by user")
                        self._log(run_id, node["name"], "Stopped by user", "WARN")
                    except Exception as exc:  # noqa: BLE001
                        status[nid] = "failed"
                        self._update_node(run_id, nid, status="failed", finished_at=iso(utcnow()), message=str(exc)[:300])
                        self._log(run_id, node["name"], f"Failed: {exc}", "ERROR")

        sinks = [nid for nid in nodes if not any(nid in n["depends_on"] for n in nodes.values())]
        if cancel.is_set():
            final = "Stopped"
        elif all(status[nid] == "success" for nid in sinks):
            final = "Success"
        else:
            final = "Failed"
        duration = round(time.perf_counter() - t_run, 2)
        with session_scope() as s:
            run = s.get(PipelineRun, run_id)
            run.status = final
            run.finished_at = utcnow()
            run.duration_s = duration
            s.add(run)
            s.commit()
        self._log(run_id, "pipeline", f"Run finished: {final} in {duration:.1f}s", "INFO" if final == "Success" else "WARN")
        hub.publish(f"pipeline:{run_id}", {"type": "run", "status": final, "duration_s": duration})
        if final == "Failed":
            raise_alert("critical", "pipeline_failed", "experiment", f"{ctx['pipeline']} run #{ctx['number']} failed",
                        "One or more pipeline steps failed")
        elif final == "Success":
            raise_alert("success", "pipeline_success", "experiment", f"{ctx['pipeline']} run #{ctx['number']} succeeded",
                        f"Finished in {duration:.0f}s")
        log_activity(ctx["owner_id"], "pipeline", final.lower(), f"{ctx['pipeline']} run #{ctx['number']}: {final}",
                     f"/pipelines?run={run_id}")
        self._cancel.pop(run_id, None)

    # ------------------------------------------------------------------ nodes
    def _check(self, run_id: int, node_id: str) -> None:
        if self._cancel[run_id].is_set() or self._node_cancel[(run_id, node_id)].is_set():
            raise NodeStopped()

    def _run_node(self, run_id: int, node: dict[str, Any], ctx: dict[str, Any], status: dict[str, str]) -> dict[str, Any]:
        t0 = time.perf_counter()
        name, ntype, params = node["name"], node["type"], node["params"]
        self._log(run_id, name, f"Starting {ntype} step")
        handler = getattr(self, f"_node_{ntype}")
        result = handler(run_id, node, ctx, params) or {}
        self._check(run_id, node["id"])
        duration = round(time.perf_counter() - t0, 2)
        self._log(run_id, name, f"Completed in {duration:.2f}s")
        return {"duration_s": duration, **result}

    def _write_json(self, ctx: dict[str, Any], filename: str, payload: dict[str, Any]) -> str:
        path = ctx["run_dir"] / filename
        path.write_text(json.dumps(to_jsonable(payload), indent=2), encoding="utf-8")
        return storage.rel(path)

    def _node_validate(self, run_id: int, node: dict, ctx: dict, params: dict) -> dict[str, Any]:
        path = ctx["source_path"]
        if path is None or not path.exists():
            raise ValueError(f"Dataset {ctx['dataset_name']} has no data file")
        df = load_frame(path)
        self._check(run_id, node["id"])
        rows, cols = df.shape
        missing = float(df.isna().mean().mean() * 100) if rows else 0.0
        dups = float(df.duplicated().mean() * 100) if rows else 0.0
        target = ctx["target"]
        self._log(run_id, node["name"], f"Loaded {rows:,} rows x {cols} columns from {path.name}")
        self._log(run_id, node["name"], f"Missing {missing:.2f}%, duplicates {dups:.2f}%")
        if not target or target not in df.columns:
            raise ValueError(f"Target column '{target}' not present")
        if rows < int(params.get("min_rows", 50)):
            raise ValueError(f"Only {rows} rows (min {params.get('min_rows', 50)})")
        if missing > float(params.get("max_missing_pct", 20)):
            raise ValueError(f"Missing values {missing:.1f}% exceed {params.get('max_missing_pct', 20)}%")
        balance = df[target].value_counts(normalize=True).head(10).round(4).to_dict()
        report = {"rows": rows, "columns": cols, "missing_pct": missing, "duplicate_pct": dups, "target": target,
                  "class_balance": balance}
        art = self._write_json(ctx, "validation_report.json", report)
        return {"message": f"{rows:,} rows validated", "artifacts": [storage.display(art)]}

    def _node_preprocess(self, run_id: int, node: dict, ctx: dict, params: dict) -> dict[str, Any]:
        df = load_frame(ctx["source_path"])
        before = len(df)
        if params.get("drop_duplicates", True):
            df = df.drop_duplicates()
        target = ctx["target"]
        df = df.dropna(subset=[target])
        numeric = [c for c in df.select_dtypes(include="number").columns if c != target]
        for col in numeric:
            df[col] = df[col].fillna(df[col].median())
            if params.get("clip_outliers", True):
                q1, q3 = df[col].quantile(0.25), df[col].quantile(0.75)
                iqr = q3 - q1
                if iqr > 0:
                    df[col] = df[col].clip(q1 - 3 * iqr, q3 + 3 * iqr)
        for col in df.columns:
            if col != target and df[col].dtype == object and df[col].isna().any():
                df[col] = df[col].fillna(df[col].mode().iloc[0])
        self._check(run_id, node["id"])
        out = ctx["run_dir"] / "preprocessed.parquet"
        df.to_parquet(out, index=False)
        ctx["preprocessed_path"] = out
        self._log(run_id, node["name"], f"{before - len(df)} rows dropped, {len(numeric)} numeric columns imputed")
        return {"message": f"{len(df):,} clean rows", "artifacts": [storage.display(storage.rel(out))]}

    def _node_features(self, run_id: int, node: dict, ctx: dict, params: dict) -> dict[str, Any]:
        src = ctx.get("preprocessed_path") or ctx["source_path"]
        df = pd.read_parquet(src) if str(src).endswith(".parquet") else load_frame(src)
        target = ctx["target"]
        dropped = []
        for col in list(df.columns):
            if col == target:
                continue
            if df[col].nunique(dropna=False) <= 1:
                dropped.append(col)
            elif df[col].dtype == object and df[col].nunique() > 30:
                dropped.append(col)
        df = df.drop(columns=dropped)
        added = []
        if params.get("ratio_features", False):
            numeric = [c for c in df.select_dtypes(include="number").columns if c != target][:4]
            for i in range(len(numeric) - 1):
                a, b = numeric[i], numeric[i + 1]
                name = f"{a}_per_{b}"
                df[name] = df[a] / df[b].replace(0, np.nan)
                df[name] = df[name].fillna(0.0)
                added.append(name)
        self._check(run_id, node["id"])
        out = ctx["run_dir"] / "features.parquet"
        df.to_parquet(out, index=False)
        ctx["features_path"] = out
        self._write_json(ctx, "feature_report.json", {"dropped": dropped, "added": added, "columns": list(df.columns)})
        self._log(run_id, node["name"], f"{df.shape[1] - 1} features ready (dropped {len(dropped)}, added {len(added)})")
        return {"message": f"{df.shape[1] - 1} features", "artifacts": [storage.display(storage.rel(out))]}

    def _node_train(self, run_id: int, node: dict, ctx: dict, params: dict) -> dict[str, Any]:
        algo = params["algorithm"]
        p = normalise_params(algo, params)
        feat = ctx.get("features_path") or ctx.get("preprocessed_path")
        if feat is not None:
            p["data_path"] = storage.rel(feat)
        with session_scope() as s:
            from app.services.trainer import next_run_code

            info = ALGORITHMS[algo]
            r = Run(code=next_run_code(s), name=f"{ctx['pipeline']} · {node['name']}", algorithm=algo,
                    algorithm_label=info["label"], framework=info["framework"], kind="pipeline",
                    dataset_id=ctx["dataset_id"], dataset_version=ctx["dataset_version"], target=ctx["target"],
                    params=p, total_epochs=p["epochs"], owner_id=ctx["owner_id"])
            s.add(r)
            s.commit()
            s.refresh(r)
            train_run_id, code = r.id, r.code
        key = (run_id, node["id"])
        with self._state_lock:
            self._node_runs[key] = train_run_id
        self._update_node(run_id, node["id"], run_id=train_run_id, message=f"Training {code}")
        self._log(run_id, node["name"], f"Created run {code} ({info['label']}, {p['epochs']} epochs)")
        if self._node_cancel[key].is_set() or self._cancel[run_id].is_set():
            trainer.stop(train_run_id)

        def on_epoch(_r: Run, epoch: int, m: dict[str, Any]) -> None:
            total = p["epochs"]
            if epoch == 1 or epoch % max(1, total // 5) == 0 or epoch == total:
                self._log(run_id, node["name"], f"Epoch {epoch}/{total} - loss: {m['train_loss']:.4f} - val_acc: {m['val_acc']:.4f}")
                self._update_node(run_id, node["id"], progress=round(epoch / total * 100, 1))

        result = trainer.execute(train_run_id, on_epoch=on_epoch)
        with self._state_lock:
            self._node_runs.pop(key, None)
        with session_scope() as s:
            r = s.get(Run, train_run_id)
            acc = (r.metrics or {}).get("accuracy")
            err = r.error
            art = r.artifact_path
        if result == "Stopped":
            raise NodeStopped()
        if result != "Completed":
            raise ValueError(f"{code} {result.lower()}: {err}")
        ctx["train_runs"][node["id"]] = train_run_id
        return {"message": f"{code} accuracy {acc:.3f}", "artifacts": [storage.display(art)], "run_id": train_run_id,
                "accuracy": acc}

    def _node_evaluate(self, run_id: int, node: dict, ctx: dict, params: dict) -> dict[str, Any]:
        candidates = [ctx["train_runs"][d] for d in node["depends_on"] if d in ctx["train_runs"]]
        if not candidates:
            raise ValueError("No trained model to evaluate")
        best_id, best_acc = None, -1.0
        with session_scope() as s:
            for rid in candidates:
                r = s.get(Run, rid)
                acc = float((r.metrics or {}).get("accuracy") or 0.0)
                self._log(run_id, node["name"], f"{r.code} ({r.algorithm_label}): accuracy {acc:.4f}")
                if acc > best_acc:
                    best_id, best_acc, best_code = rid, acc, r.code
        min_acc = float(params.get("min_accuracy", 0.0))
        if best_acc < min_acc:
            raise ValueError(f"Best accuracy {best_acc:.3f} is below the {min_acc:.2f} gate")
        ctx["best_run_id"] = best_id
        self._log(run_id, node["name"], f"Selected {best_code} (accuracy {best_acc:.4f})")
        report = self._write_json(ctx, "evaluation.json", {"best_run": best_code, "accuracy": best_acc, "candidates": candidates})
        return {"message": f"Best: {best_code} ({best_acc:.3f})", "artifacts": [storage.display(report)], "run_id": best_id}

    def _node_register(self, run_id: int, node: dict, ctx: dict, params: dict) -> dict[str, Any]:
        if "best_run_id" not in ctx:
            raise ValueError("Nothing to register (no evaluate step result)")
        with session_scope() as s:
            mv = registry.register_run(s, ctx["best_run_id"], str(params["model_name"]),
                                       description=f"Registered by {ctx['pipeline']} run #{ctx['number']}",
                                       owner_id=ctx["owner_id"])
            ctx["model_id"], ctx["version_id"] = mv.model_id, mv.id
            version = mv.version
            art = mv.artifact_path
        self._log(run_id, node["name"], f"Registered {params['model_name']} {version}")
        return {"message": f"{params['model_name']} {version}", "artifacts": [storage.display(art)]}

    def _node_deploy(self, run_id: int, node: dict, ctx: dict, params: dict) -> dict[str, Any]:
        if "version_id" not in ctx:
            raise ValueError("Nothing to deploy (no register step result)")
        env = str(params.get("environment", "Staging"))
        with session_scope() as s:
            dep = deploy_version(s, ctx["model_id"], ctx["version_id"], env, ctx["owner_id"])
            dep_id, slug = dep.id, dep.slug
        self._log(run_id, node["name"], f"Rolling out to {env} as /serve/{slug}/predict")
        deadline = time.time() + 60
        while time.time() < deadline:
            self._check(run_id, node["id"])
            with session_scope() as s:
                d = s.get(Deployment, dep_id)
                state, err = d.status, d.last_error
            if state == "Running":
                break
            if state == "Failed":
                raise ValueError(f"Deployment failed: {err}")
            time.sleep(0.3)
        else:
            raise TimeoutError("Deployment did not become ready within 60s")
        return {"message": f"Live at /serve/{slug}/predict", "artifacts": [f"/serve/{slug}/predict"]}

    # --------------------------------------------------------------- schedule
    def start_scheduler(self) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler

        self.scheduler = BackgroundScheduler(daemon=True)
        self.scheduler.start()
        with session_scope() as s:
            for pipe in s.exec(select(Pipeline).where(Pipeline.schedule != None)).all():  # noqa: E711
                try:
                    self.apply_schedule(pipe.id, pipe.schedule)
                except Exception:  # noqa: BLE001
                    pass

    def apply_schedule(self, pipeline_id: int, cron: Optional[str]) -> Optional[str]:
        """Install (or remove) the cron job. Returns the next run time (ISO) if scheduled."""
        from apscheduler.triggers.cron import CronTrigger

        job_id = f"pipeline-{pipeline_id}"
        if self.scheduler is None:
            return None
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
        if not cron:
            return None
        trigger = CronTrigger.from_crontab(cron)
        job = self.scheduler.add_job(self._scheduled_run, trigger, args=[pipeline_id], id=job_id, replace_existing=True)
        nrt = getattr(job, "next_run_time", None)
        return nrt.isoformat() if nrt else None

    def next_run_time(self, pipeline_id: int) -> Optional[str]:
        if self.scheduler is None:
            return None
        job = self.scheduler.get_job(f"pipeline-{pipeline_id}")
        nrt = getattr(job, "next_run_time", None) if job else None
        return nrt.isoformat() if nrt else None

    def _scheduled_run(self, pipeline_id: int) -> None:
        with session_scope() as s:
            pipe = s.get(Pipeline, pipeline_id)
            if pipe is None or not pipe.active:
                return
            owner = pipe.owner_id
        try:
            self.start(pipeline_id, "schedule", owner)
        except Exception:  # noqa: BLE001 - e.g. previous run still active
            pass


def validate_cron(cron: str) -> None:
    from apscheduler.triggers.cron import CronTrigger

    try:
        CronTrigger.from_crontab(cron)
    except ValueError as exc:
        raise ValueError(f"Invalid cron expression: {exc}") from exc


pipeline_runner = PipelineRunner()

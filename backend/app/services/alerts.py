"""Alert rules engine: error rate, P95 latency, drift, and recovery events."""
from __future__ import annotations

import threading

from sqlmodel import select

from app.db import session_scope
from app.models import Alert, Deployment
from app.services.activity import raise_alert
from app.services.drift import THRESHOLD, deployment_drift
from app.services.serving import deployment_window_stats

ERROR_RATE_PCT = 2.0
P95_MS = 600.0
MIN_REQUESTS = 20
RULE_KINDS = ("error_rate", "latency", "drift")
TITLES = {
    "error_rate": ("critical", "High error rate detected"),
    "latency": ("warning", "Latency threshold breached"),
    "drift": ("warning", "Model drift spike"),
}


class AlertEngine:
    def __init__(self) -> None:
        self._stop = threading.Event()

    def evaluate(self) -> None:
        with session_scope() as s:
            deps = s.exec(select(Deployment).where(Deployment.status == "Running")).all()
            active = {(a.deployment_id, a.kind): a for a in s.exec(
                select(Alert).where(Alert.resolved == False, Alert.kind.in_(RULE_KINDS))).all()}  # noqa: E712
            for dep in deps:
                stats = deployment_window_stats(s, dep.id, minutes=15)
                breaches: dict[str, str] = {}
                if stats["requests"] >= MIN_REQUESTS:
                    if stats["error_rate"] > ERROR_RATE_PCT:
                        breaches["error_rate"] = f"{dep.name} error rate {stats['error_rate']:.1f}% > {ERROR_RATE_PCT:.0f}% (last 15 min)"
                    if stats["p95_ms"] > P95_MS:
                        breaches["latency"] = f"{dep.name} P95 latency {stats['p95_ms']:.0f} ms > {P95_MS:.0f} ms"
                drift = deployment_drift(s, dep.id, n=300)
                if drift.get("available"):
                    score = max(drift["data_drift"], drift["prediction_drift"])
                    if score > THRESHOLD:
                        top = drift["features"][0]["name"] if drift["features"] else "prediction"
                        breaches["drift"] = f"{dep.name} drift score {score:.2f} > {THRESHOLD} (top feature: {top})"
                for kind in RULE_KINDS:
                    key = (dep.id, kind)
                    if kind in breaches and key not in active:
                        severity, title = TITLES[kind]
                        raise_alert(severity, kind, "monitoring", title, breaches[kind], deployment_id=dep.id, resolved=False)
                    elif kind not in breaches and key in active:
                        alert = active[key]
                        # Only resolve when there is fresh evidence (traffic or drift sample) that it cleared.
                        if kind == "drift" and not drift.get("available"):
                            continue
                        if kind != "drift" and stats["requests"] < MIN_REQUESTS:
                            continue
                        alert.resolved = True
                        s.add(alert)
                        s.commit()
                        raise_alert("success", "recovery", "monitoring", "Model recovered",
                                    f"{dep.name}: {TITLES[kind][1].lower()} cleared", deployment_id=dep.id)

    def start(self) -> None:
        def loop() -> None:
            while not self._stop.wait(20):
                try:
                    self.evaluate()
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=loop, name="alert-engine", daemon=True).start()


alert_engine = AlertEngine()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.endpoints import auth, datasets, models, training, experiments, deployments, monitoring, dashboard

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"/api/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(datasets.router, prefix="/api/datasets", tags=["datasets"])
app.include_router(models.router, prefix="/api/models", tags=["models"])
app.include_router(training.router, prefix="/api/training", tags=["training"])
app.include_router(experiments.router, prefix="/api/experiments", tags=["experiments"])
app.include_router(deployments.router, prefix="/api/deployments", tags=["deployments"])
app.include_router(monitoring.router, prefix="/api/monitoring", tags=["monitoring"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])




@app.get("/")
def read_root():
    return {"message": "Welcome to Mini MLOps Platform API"}

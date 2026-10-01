import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Mini MLOps Platform"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "supersecretkey_change_in_production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8 # 8 days
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://mlops_user:mlops_password@localhost:5432/mlops_db")

settings = Settings()

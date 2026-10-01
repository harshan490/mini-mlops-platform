import os
import pandas as pd
from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.api import deps
from app.models.dataset import Dataset
from app.models.user import User
from pydantic import BaseModel
from datetime import datetime

router = APIRouter()

class DatasetResponse(BaseModel):
    id: int
    name: str
    version: str
    upload_date: datetime
    num_rows: int
    num_columns: int
    file_path: str

    class Config:
        from_attributes = True

UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../datasets"))

@router.post("/upload", response_model=DatasetResponse)
async def upload_dataset(
    *,
    db: Session = Depends(deps.get_db),
    file: UploadFile = File(...),
    current_user: User = Depends(deps.get_current_user_optional)
) -> Any:
    filename = os.path.basename(file.filename)
    clean_filename = filename.lower()
    
    if not clean_filename.endswith(('.csv', '.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only CSV or XLSX files are supported")
    
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    content = await file.read()
    with open(file_path, "wb") as buffer:
        buffer.write(content)
    
    try:
        if clean_filename.endswith('.csv'):
            try:
                df = pd.read_csv(file_path)
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, encoding='latin1')
        else:
            df = pd.read_excel(file_path)
        
        num_rows, num_columns = df.shape
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")
    
    dataset = Dataset(
        name=filename,
        version="v1.0",
        num_rows=num_rows,
        num_columns=num_columns,
        file_path=file_path,
        user_id=current_user.id
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    
    return dataset


@router.get("/", response_model=List[DatasetResponse])
def get_datasets(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_user_optional)
) -> Any:
    datasets = db.query(Dataset).offset(skip).limit(limit).all()
    return datasets


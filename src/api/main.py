import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from src.api.routes.ndvi import router as ndvi_router
from src.db.database import engine, Base

Base.metadata.create_all(bind=engine)

app = FastAPI(title="COG-NDVI Engine API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ndvi_router)

WEB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web"))

@app.get("/")
def read_root():
    index_path = os.path.join(WEB_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "COG-NDVI Engine API Operational"}

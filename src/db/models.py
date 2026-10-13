from sqlalchemy import Column, Integer, String, Float, JSON
from datetime import datetime
from src.db.database import Base

class SavedROI(Base):
    __tablename__ = "saved_rois"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    index_type = Column(String, default="ndvi")
    dataset = Column(String, default="synthetic")
    geometry = Column(JSON)
    area_ha = Column(Float)
    total_pixels = Column(Integer)
    mean_val = Column(Float)
    min_val = Column(Float)
    max_val = Column(Float)
    std_val = Column(Float, default=0.0)
    classes = Column(JSON, nullable=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%d/%m/%Y %H:%M"))

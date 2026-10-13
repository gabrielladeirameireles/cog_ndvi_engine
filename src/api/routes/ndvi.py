from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any, Optional

from src.db.database import get_db
from src.db.models import SavedROI
from src.services.ndvi import (
    generate_xyz_tile,
    query_point_value,
    query_roi_stats,
    export_roi_geotiff,
    generate_pdf_report
)

router = APIRouter(prefix="/ndvi", tags=["NDVI Engine"])

class ROIStatsRequest(BaseModel):
    geometry: Dict[str, Any]
    red_key: str = "red_band.tif"
    nir_key: str = "nir_band.tif"

class PDFExportRequest(BaseModel):
    name: str
    index_type: str = "ndvi"
    stats: Dict[str, Any]

class SaveROIRequest(BaseModel):
    name: str
    index_type: str = "ndvi"
    dataset: str = "synthetic"
    geometry: Dict[str, Any]
    area_ha: float
    total_pixels: int = 0
    mean_val: float
    min_val: float
    max_val: float
    std_val: float = 0.0
    classes: Optional[Dict[str, Any]] = None

@router.get("/status")
def get_status():
    return {"module": "NDVI Service", "status": "active"}

@router.get("/tiles/{z}/{x}/{y}.png")
def get_tile(
    z: int, x: int, y: int,
    red_key: str = "red_band.tif",
    nir_key: str = "nir_band.tif",
    colormap: str = "classic",
    index_type: str = "ndvi"
):
    tile_bytes = generate_xyz_tile(z, x, y, red_key, nir_key, colormap, index_type)
    return Response(content=tile_bytes, media_type="image/png")

@router.get("/point")
def get_point(
    lat: float = Query(...),
    lon: float = Query(...),
    red_key: str = "red_band.tif",
    nir_key: str = "nir_band.tif"
):
    return query_point_value(lat, lon, red_key, nir_key)

@router.post("/roi-stats")
def get_roi_stats(req: ROIStatsRequest):
    return query_roi_stats(req.geometry, req.red_key, req.nir_key)

@router.post("/export-pdf")
def export_pdf(req: PDFExportRequest):
    pdf_bytes = generate_pdf_report(req.name, req.index_type, req.stats)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=relatorio_{req.name}.pdf"}
    )

@router.post("/export-geotiff")
def export_geotiff(req: ROIStatsRequest):
    tiff_bytes = export_roi_geotiff(req.geometry, req.red_key, req.nir_key)
    return Response(
        content=tiff_bytes,
        media_type="image/tiff",
        headers={"Content-Disposition": "attachment; filename=recorte_roi.tif"}
    )

@router.post("/roi/save")
def save_roi(req: SaveROIRequest, db: Session = Depends(get_db)):
    roi_entry = SavedROI(
        name=req.name,
        index_type=req.index_type,
        dataset=req.dataset,
        geometry=req.geometry,
        area_ha=req.area_ha,
        total_pixels=req.total_pixels,
        mean_val=req.mean_val,
        min_val=req.min_val,
        max_val=req.max_val,
        std_val=req.std_val,
        classes=req.classes
    )
    db.add(roi_entry)
    db.commit()
    db.refresh(roi_entry)
    return {"status": "success", "id": roi_entry.id, "name": roi_entry.name}

@router.get("/roi/history")
def list_rois(db: Session = Depends(get_db)):
    rois = db.query(SavedROI).order_by(SavedROI.id.desc()).all()
    return rois

@router.delete("/roi/{roi_id}")
def delete_roi(roi_id: int, db: Session = Depends(get_db)):
    item = db.query(SavedROI).filter(SavedROI.id == roi_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="ROI não encontrada")
    db.delete(item)
    db.commit()
    return {"status": "deleted", "id": roi_id}

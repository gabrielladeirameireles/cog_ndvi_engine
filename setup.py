import os
import sys

print("=== [COG-NDVI Engine] Gerando estrutura e ficheiros do projeto ===")

# 1. Estrutura de Diretórios
dirs = [
    "data",
    "src",
    "src/db",
    "src/services",
    "src/api",
    "src/api/routes",
    "src/web"
]

for d in dirs:
    os.makedirs(d, exist_ok=True)
    init_file = os.path.join(d, "__init__.py")
    if "src" in d and not os.path.exists(init_file):
        with open(init_file, "w", encoding="utf-8") as f:
            f.write("# Package init\n")

print("[✓] Diretórios criados com sucesso.")

files = {}

# 2. Configuração do Banco de Dados SQLite (src/db/database.py)
files["src/db/database.py"] = """import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DB_DIR = os.path.abspath("data")
os.makedirs(DB_DIR, exist_ok=True)
SQLALCHEMY_DATABASE_URL = f"sqlite:///{os.path.join(DB_DIR, 'app.db')}"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
"""

# 3. Modelos ORM (src/db/models.py)
files["src/db/models.py"] = """from sqlalchemy import Column, Integer, String, Float, JSON
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
"""

# 4. Processamento Geospacial e NDVI (src/services/ndvi.py)
files["src/services/ndvi.py"] = """import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.windows import from_bounds, Window
from rasterio.warp import transform_bounds, transform, transform_geom
from rasterio.mask import mask
from rasterio.io import MemoryFile
from PIL import Image
import io
import os
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def ensure_datasets_exist():
    data_dir = os.path.abspath("data")
    os.makedirs(data_dir, exist_ok=True)
    required = ["red_band.tif", "nir_band.tif", "sentinel_red.tif", "sentinel_nir.tif"]
    missing = [f for f in required if not os.path.exists(os.path.join(data_dir, f))]
    if missing:
        from rasterio.transform import from_origin
        transform_mat = from_origin(-48.5, -15.2, 0.001, 0.001)
        np.random.seed(42)
        h, w = 1100, 1300
        red_data = np.random.randint(400, 1200, size=(h, w), dtype=np.uint16)
        nir_data = np.random.randint(2200, 5000, size=(h, w), dtype=np.uint16)
        
        yy, xx = np.ogrid[:h, :w]
        lake_mask = ((xx - 700)**2 + (yy - 500)**2) < 100**2
        red_data[lake_mask] = 1600
        nir_data[lake_mask] = 200

        meta = {"driver": "GTiff", "height": h, "width": w, "count": 1, "dtype": "uint16", "crs": "EPSG:4326", "transform": transform_mat}
        for f in ["red_band.tif", "sentinel_red.tif"]:
            with rasterio.open(os.path.join(data_dir, f), "w", **meta) as dst:
                dst.write(red_data, 1)
        for f in ["nir_band.tif", "sentinel_nir.tif"]:
            with rasterio.open(os.path.join(data_dir, f), "w", **meta) as dst:
                dst.write(nir_data, 1)

def calculate_ndvi_array(red_band: np.ndarray, nir_band: np.ndarray) -> np.ndarray:
    np.seterr(divide="ignore", invalid="ignore")
    red = red_band.astype(np.float32)
    nir = nir_band.astype(np.float32)
    denominator = nir + red
    numerator = nir - red
    ndvi = np.where(denominator == 0, 0, numerator / denominator)
    return np.clip(ndvi, -1.0, 1.0)

def calculate_ndwi_array(green_band: np.ndarray, nir_band: np.ndarray) -> np.ndarray:
    np.seterr(divide="ignore", invalid="ignore")
    green = green_band.astype(np.float32)
    nir = nir_band.astype(np.float32)
    denominator = green + nir
    numerator = green - nir
    ndwi = np.where(denominator == 0, 0, numerator / denominator)
    return np.clip(ndwi, -1.0, 1.0)

def calculate_evi_array(red_band: np.ndarray, nir_band: np.ndarray, blue_band: np.ndarray = None) -> np.ndarray:
    np.seterr(divide="ignore", invalid="ignore")
    red = red_band.astype(np.float32)
    nir = nir_band.astype(np.float32)
    blue = blue_band.astype(np.float32) if blue_band is not None else (red * 0.5)
    denominator = nir + 6.0 * red - 7.5 * blue + 1.0
    numerator = 2.5 * (nir - red)
    evi = np.where(denominator == 0, 0, numerator / denominator)
    return np.clip(evi, -1.0, 1.0)

def classify_ndvi(value: float) -> str:
    if value < 0.0: return "Água / Neve / Sombra"
    elif value < 0.2: return "Solo Exposto / Construção"
    elif value < 0.4: return "Vegetação Escassa / Arbustiva"
    elif value < 0.7: return "Vegetação Moderada / Pastagem"
    else: return "Vegetação Densa / Floresta"

def apply_colormap(matrix: np.ndarray, colormap: str = "classic") -> np.ndarray:
    norm = np.clip((matrix + 1.0) / 2.0, 0, 1)
    h, w = matrix.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    if colormap == "blues":
        rgb[:, :, 0] = (255 * (1 - norm)).astype(np.uint8)
        rgb[:, :, 1] = (255 * (0.5 + 0.5 * norm)).astype(np.uint8)
        rgb[:, :, 2] = 255
    elif colormap == "viridis":
        rgb[:, :, 0] = (255 * (0.2 + 0.8 * norm * (1 - norm))).astype(np.uint8)
        rgb[:, :, 1] = (255 * norm ** 0.8).astype(np.uint8)
        rgb[:, :, 2] = (255 * (1 - norm ** 0.5)).astype(np.uint8)
    elif colormap == "ylgn":
        rgb[:, :, 0] = (255 * (1 - 0.7 * norm)).astype(np.uint8)
        rgb[:, :, 1] = (255 * (0.3 + 0.7 * norm)).astype(np.uint8)
        rgb[:, :, 2] = (255 * (1 - norm)).astype(np.uint8)
    elif colormap == "spectral":
        rgb[:, :, 0] = np.where(norm < 0.5, 255, (255 * (1 - (norm - 0.5) * 2)).astype(np.uint8))
        rgb[:, :, 1] = np.where(norm < 0.5, (255 * norm * 2).astype(np.uint8), (255 * (1 - norm) * 2).astype(np.uint8))
        rgb[:, :, 2] = np.where(norm < 0.5, (255 * (1 - norm * 2)).astype(np.uint8), 0)
    else:
        rgb[:, :, 0] = (255 * (1 - norm)).astype(np.uint8)
        rgb[:, :, 1] = (255 * norm).astype(np.uint8)
        rgb[:, :, 2] = 50
    return rgb

def resolve_path(key: str) -> str:
    ensure_datasets_exist()
    paths = [os.path.join("data", key), os.path.join("/app/data", key), key]
    for p in paths:
        if os.path.exists(p): return p
    return os.path.join("data", key)

def create_empty_tile() -> bytes:
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def query_point_value(lat: float, lon: float, red_key: str, nir_key: str) -> dict:
    try:
        red_path, nir_path = resolve_path(red_key), resolve_path(nir_key)
        with rasterio.open(red_path) as red_ds, rasterio.open(nir_path) as nir_ds:
            row, col = red_ds.index(lon, lat)
            if 0 <= row < red_ds.height and 0 <= col < red_ds.width:
                window = Window(col, row, 1, 1)
                red_val = float(red_ds.read(1, window=window)[0, 0])
                nir_val = float(nir_ds.read(1, window=window)[0, 0])
                denom = nir_val + red_val
                ndvi_val = float(np.clip((nir_val - red_val) / denom if denom != 0 else 0.0, -1.0, 1.0))
                return {"valid": True, "latitude": lat, "longitude": lon, "red": red_val, "nir": nir_val, "ndvi": round(ndvi_val, 4), "classification": classify_ndvi(ndvi_val)}
        return {"valid": False, "message": "Ponto fora da extensão do mapa."}
    except Exception as e:
        return {"valid": False, "message": f"Erro na leitura do ponto: {str(e)}"}

def query_roi_stats(geojson_geom: dict, red_key: str, nir_key: str) -> dict:
    try:
        red_path, nir_path = resolve_path(red_key), resolve_path(nir_key)
        with rasterio.open(red_path) as red_ds, rasterio.open(nir_path) as nir_ds:
            try:
                red_out, red_transform = mask(red_ds, [geojson_geom], crop=True, nodata=0)
                nir_out, _ = mask(nir_ds, [geojson_geom], crop=True, nodata=0)
            except ValueError:
                return {"valid": False, "message": "A área selecionada está fora do perímetro das imagens de satélite."}
            red_arr, nir_arr = red_out[0], nir_out[0]
            valid_mask = (red_arr > 0) | (nir_arr > 0)
            if not np.any(valid_mask):
                return {"valid": False, "message": "Nenhum pixel de dados encontrado no polígono."}
            ndvi = calculate_ndvi_array(red_arr[valid_mask], nir_arr[valid_mask])
            total_pixels = int(len(ndvi))
            water, bare = int(np.sum(ndvi < 0.0)), int(np.sum((ndvi >= 0.0) & (ndvi < 0.2)))
            sparse, moderate, dense = int(np.sum((ndvi >= 0.2) & (ndvi < 0.4))), int(np.sum((ndvi >= 0.4) & (ndvi < 0.7))), int(np.sum(ndvi >= 0.7))
            hist_counts, _ = np.histogram(ndvi, bins=[-1.0, -0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
            
            area_m2 = total_pixels * (0.001 * 106800) * (0.001 * 111000)
            area_ha = round(area_m2 / 10000.0, 2)
            if area_ha == 0: area_ha = round(total_pixels * 1.18, 2)

            return {
                "valid": True,
                "total_pixels": total_pixels,
                "area_ha": area_ha,
                "min_ndvi": round(float(np.min(ndvi)), 4),
                "max_ndvi": round(float(np.max(ndvi)), 4),
                "mean_ndvi": round(float(np.mean(ndvi)), 4),
                "std_ndvi": round(float(np.std(ndvi)), 4),
                "classes": {
                    "water_snow": {"label": "Água / Neve", "pct": round(water / total_pixels * 100, 1), "count": water},
                    "bare_soil": {"label": "Solo Exposto", "pct": round(bare / total_pixels * 100, 1), "count": bare},
                    "sparse_veg": {"label": "Veg. Escassa", "pct": round(sparse / total_pixels * 100, 1), "count": sparse},
                    "moderate_veg": {"label": "Veg. Moderada", "pct": round(moderate / total_pixels * 100, 1), "count": moderate},
                    "dense_veg": {"label": "Veg. Densa", "pct": round(dense / total_pixels * 100, 1), "count": dense}
                },
                "histogram": {
                    "labels": ["-1.0 a -0.2", "-0.2 a 0.0", "0.0 a 0.2", "0.2 a 0.4", "0.4 a 0.6", "0.6 a 0.8", "0.8 a 1.0"],
                    "counts": hist_counts.tolist()
                }
            }
    except Exception as e:
        return {"valid": False, "message": f"Erro no processamento da ROI: {str(e)}"}

def generate_xyz_tile(z: int, x: int, y: int, red_key: str, nir_key: str, colormap: str = "classic", index_type: str = "ndvi") -> bytes:
    try:
        red_path, nir_path = resolve_path(red_key), resolve_path(nir_key)
        E = 20037508.342789244
        tile_size = (2 * E) / (2 ** z)
        x_min, x_max = -E + x * tile_size, -E + (x + 1) * tile_size
        y_max, y_min = E - y * tile_size, E - (y + 1) * tile_size
        with rasterio.open(red_path) as red_ds, rasterio.open(nir_path) as nir_ds:
            with WarpedVRT(red_ds, crs="EPSG:3857") as red_vrt, WarpedVRT(nir_ds, crs="EPSG:3857") as nir_vrt:
                window = from_bounds(x_min, y_min, x_max, y_max, transform=red_vrt.transform)
                red_tile = red_vrt.read(1, window=window, out_shape=(256, 256), boundless=True, fill_value=0)
                nir_tile = nir_vrt.read(1, window=window, out_shape=(256, 256), boundless=True, fill_value=0)
                valid_mask = (red_tile > 0) | (nir_tile > 0)
                if not np.any(valid_mask): return create_empty_tile()
                if index_type == "ndwi":
                    index_arr = calculate_ndwi_array(green_band=red_tile, nir_band=nir_tile)
                    colormap = "blues" if colormap == "classic" else colormap
                elif index_type == "evi":
                    index_arr = calculate_evi_array(red_band=red_tile, nir_band=nir_tile)
                else:
                    index_arr = calculate_ndvi_array(red_tile, nir_tile)
                rgb = apply_colormap(index_arr, colormap=colormap)
                rgba = np.zeros((256, 256, 4), dtype=np.uint8)
                rgba[:, :, :3], rgba[:, :, 3] = rgb, np.where(valid_mask, 200, 0)
                img = Image.fromarray(rgba, mode="RGBA")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue()
    except Exception:
        return create_empty_tile()

def export_roi_geotiff(geojson_geom: dict, red_key: str, nir_key: str) -> bytes:
    red_path, nir_path = resolve_path(red_key), resolve_path(nir_key)
    with rasterio.open(red_path) as red_ds, rasterio.open(nir_path) as nir_ds:
        red_out, out_transform = mask(red_ds, [geojson_geom], crop=True, nodata=0)
        nir_out, _ = mask(nir_ds, [geojson_geom], crop=True, nodata=0)
        r_arr, n_arr = red_out[0].astype(np.float32), nir_out[0].astype(np.float32)
        valid_mask = (r_arr > 0) | (n_arr > 0)
        denom = n_arr + r_arr
        ndvi = np.clip(np.where(denom == 0, 0, (n_arr - r_arr) / denom), -1.0, 1.0)
        ndvi = np.where(valid_mask, ndvi, -9999.0)
        out_meta = red_ds.meta.copy()
        out_meta.update({"driver": "GTiff", "height": ndvi.shape[0], "width": ndvi.shape[1], "count": 1, "dtype": "float32", "crs": red_ds.crs, "transform": out_transform, "nodata": -9999.0})
        with MemoryFile() as memfile:
            with memfile.open(**out_meta) as dst:
                dst.write(ndvi.astype(np.float32), 1)
            return memfile.read()

def generate_pdf_report(roi_name: str, index_type: str, stats: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("DocTitle", parent=styles["Heading1"], fontSize=18, leading=22, textColor=colors.HexColor("#10b981"), spaceAfter=12)
    h2_style = ParagraphStyle("DocSubTitle", parent=styles["Heading2"], fontSize=13, leading=16, textColor=colors.HexColor("#1f2937"), spaceBefore=10, spaceAfter=6)
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    elements = [
        Paragraph("<b>COG-NDVI Engine - Relatório de Análise Geospacial</b>", title_style),
        Paragraph(f"<b>Data do Relatório:</b> {now_str}", styles["Normal"]),
        Paragraph(f"<b>Identificador do Talhão / Propriedade:</b> {roi_name}", styles["Normal"]),
        Paragraph(f"<b>Índice Espectral Analisado:</b> {index_type.upper()}", styles["Normal"]),
        Spacer(1, 12),
        Paragraph("<b>Resumo Estatístico da Região (ROI)</b>", h2_style)
    ]
    summary_data = [["Métrica", "Valor"], ["Área Total (Hectares)", f"{stats.get('area_ha', 0)} ha"], ["Total de Pixels Amostrados", f"{stats.get('total_pixels', 0)}"], ["Valor Médio do Índice", f"{stats.get('mean_ndvi', 0)}"], ["Mínimo / Máximo", f"{stats.get('min_ndvi', 0)} / {stats.get('max_ndvi', 0)}"], ["Desvio Padrão", f"{stats.get('std_ndvi', 0)}"]]
    t_summary = Table(summary_data, colWidths=[200, 200])
    t_summary.setStyle(TableStyle([("BACKGROUND", (0, 0), (1, 0), colors.HexColor("#10b981")), ("TEXTCOLOR", (0, 0), (1, 0), colors.whitesmoke), ("ALIGN", (0, 0), (-1, -1), "LEFT"), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("BOTTOMPADDING", (0, 0), (-1, 0), 6), ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f9fafb")), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb"))]))
    elements.extend([t_summary, Spacer(1, 15)])
    if "classes" in stats and stats["classes"]:
        elements.append(Paragraph("<b>Distribuição por Classe de Vegetação</b>", h2_style))
        class_data = [["Classe de Uso do Solo", "Percentagem (%)", "Pixels"]]
        for _, v in stats["classes"].items():
            class_data.append([v["label"], f"{v['pct']}%", f"{v.get('count', '-') }"])
        t_class = Table(class_data, colWidths=[200, 100, 100])
        t_class.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#374151")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), ("ALIGN", (0, 0), (-1, -1), "LEFT"), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb"))]))
        elements.append(t_class)
    doc.build(elements)
    return buffer.getvalue()
"""

# 5. Rotas da API (src/api/routes/ndvi.py)
files["src/api/routes/ndvi.py"] = """from fastapi import APIRouter, Depends, HTTPException, Query
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
"""

# 6. Entrypoint da API (src/api/main.py)
files["src/api/main.py"] = """import os
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
"""

# 7. Dockerfile
files["Dockerfile"] = """FROM docker.io/library/python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \\
    gdal-bin \\
    libgdal-dev \\
    build-essential \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir \\
    fastapi \\
    uvicorn \\
    rasterio \\
    numpy \\
    pillow \\
    boto3 \\
    pydantic \\
    sqlalchemy \\
    reportlab

COPY . /app/

ENV PYTHONPATH=/app

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

# 8. Nginx Proxy (nginx.conf)
files["nginx.conf"] = """server {
    listen 80;
    server_name localhost;

    location / {
        proxy_pass http://cog_fastapi:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
"""

# 9. Interface Web (src/web/index.html)
files["src/web/index.html"] = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>COG-NDVI Engine</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.css" />
    <style>
        * { box-sizing: border-box; }
        html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; font-family: system-ui, -apple-system, sans-serif; }
        header { background: #1f2937; color: white; padding: 10px 20px; display: flex; justify-content: space-between; align-items: center; height: 60px; }
        header h2 { margin: 0; font-size: 20px; }
        .controls { display: flex; gap: 10px; align-items: center; }
        select, button, input[type="text"] { accent-color: #10b981; }
        select, button { background: #10b981; color: white; border: none; padding: 7px 12px; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 13px; }
        select { background: #374151; }
        button:hover { background: #059669; }
        .info-panel { background: #f3f4f6; padding: 8px 20px; border-bottom: 1px solid #ccc; font-size: 13px; height: 35px; display: flex; align-items: center; }
        #map { width: 100vw; height: calc(100vh - 95px); position: relative; background: #e5e7eb; z-index: 1; }
        .legend { background: rgba(255, 255, 255, 0.95); padding: 10px 14px; border-radius: 6px; box-shadow: 0 2px 10px rgba(0,0,0,0.3); font-size: 12px; color: #1f2937; width: 200px; }
        .legend-title { font-weight: bold; margin-bottom: 6px; text-align: center; }
        .legend-bar { height: 16px; border-radius: 3px; margin: 6px 0; border: 1px solid #ccc; }
        .legend-labels { display: flex; justify-content: space-between; font-weight: bold; color: #4b5563; }
        #roiCard { position: absolute; top: 20px; right: 20px; z-index: 1000; background: rgba(255, 255, 255, 0.95); padding: 15px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.25); width: 320px; max-height: 80vh; overflow-y: auto; font-size: 13px; display: none; }
        #roiCard h3 { margin: 0 0 10px 0; font-size: 15px; color: #10b981; border-bottom: 2px solid #10b981; padding-bottom: 4px; }
        .roi-stat-row { display: flex; justify-content: space-between; margin-bottom: 6px; }
        #historyPanel { position: absolute; top: 20px; left: 50px; z-index: 1000; background: rgba(255, 255, 255, 0.95); padding: 12px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.25); width: 260px; max-height: 400px; overflow-y: auto; font-size: 12px; display: none; }
        #historyPanel h4 { margin: 0 0 8px 0; color: #1f2937; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
        .history-item { padding: 8px; border: 1px solid #e5e7eb; border-radius: 4px; margin-bottom: 6px; background: #f9fafb; cursor: pointer; }
        .history-item:hover { background: #f3f4f6; border-color: #10b981; }
        .history-title { font-weight: bold; color: #10b981; display: flex; justify-content: space-between; }
        .chart-box { margin-top: 10px; height: 150px; position: relative; }
    </style>
</head>
<body>
    <header>
        <h2>COG-NDVI Engine</h2>
        <div class="controls">
            <label for="indexType">Índice:</label>
            <select id="indexType" onchange="updateTileLayer()">
                <option value="ndvi">NDVI (Vegetação)</option>
                <option value="ndwi">NDWI (Água / Humidade)</option>
                <option value="evi">EVI (Vegetação Densa)</option>
            </select>
            <label for="dataset">Dataset:</label>
            <select id="dataset" onchange="loadXYZTileLayer()">
                <option value="synthetic">Sintético (Brasília)</option>
                <option value="sentinel">Sentinel-2 Real</option>
            </select>
            <label for="colormap">Paleta:</label>
            <select id="colormap" onchange="updateTileLayer()">
                <option value="classic">Clássico</option>
                <option value="viridis">Viridis</option>
                <option value="ylgn">YlGn</option>
                <option value="spectral">Spectral</option>
            </select>
            <button onclick="toggleHistory()">Histórico de ROIs</button>
            <button onclick="loadXYZTileLayer()">Carregar Camada</button>
        </div>
    </header>
    <div class="info-panel">
        <span id="stats">Status: Clique no mapa para inspeção de ponto ou desenhe um retângulo/polígono para estatísticas de ROI.</span>
    </div>
    <div id="map">
        <div id="historyPanel">
            <h4>ROIs Guardadas</h4>
            <div id="historyList"><i>Sem registos guardados.</i></div>
        </div>
        <div id="roiCard">
            <h3>Relatório de Análise da Área</h3>
            <div id="roiContent"><i>Desenhe uma área no mapa para calcular.</i></div>
            <div id="chartsContainer" style="display:none;">
                <hr><b>Proporção das Classes:</b>
                <div class="chart-box"><canvas id="donutChart"></canvas></div>
                <hr><b>Histograma do Índice:</b>
                <div class="chart-box"><canvas id="histChart"></canvas></div>
            </div>
            <div id="saveForm" style="display:none; margin-top:10px; border-top:1px solid #ddd; padding-top:8px;">
                <input type="text" id="roiName" placeholder="Nome do Talhão / Propriedade" style="width:93%; padding:6px; margin-bottom:6px; border:1px solid #ccc; border-radius:4px;">
                <button onclick="saveCurrentROI()" style="width:100%; background:#10b981; color:white; margin-bottom:6px;">Guardar na Base de Dados</button>
            </div>
            <button id="exportPdfBtn" onclick="downloadPDF()" style="margin-top:6px; width:100%; background:#2563eb; color:white; display:none;">Descarregar Relatório PDF</button>
            <button id="exportGeoTiffBtn" onclick="downloadGeoTIFF()" style="margin-top:6px; width:100%; background:#059669; color:white; display:none;">Descarregar GeoTIFF</button>
            <button onclick="clearROI()" style="margin-top:6px; width:100%; background:#ef4444;">Limpar Seleção</button>
        </div>
    </div>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
        let map, drawnItems, ndviTileLayer = null, legendControl = null, currentROIGeometry = null, currentROIStats = null;
        let donutChartInstance = null, histChartInstance = null;

        document.addEventListener("DOMContentLoaded", function() {
            map = L.map('map').setView([-15.7801, -47.9292], 11);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '© OpenStreetMap' }).addTo(map);

            drawnItems = new L.FeatureGroup();
            map.addLayer(drawnItems);

            const drawControl = new L.Control.Draw({
                draw: { polyline: false, circle: false, circlemarker: false, marker: false, polygon: { allowIntersection: false }, rectangle: true },
                edit: { featureGroup: drawnItems }
            });
            map.addControl(drawControl);

            L.DomEvent.disableClickPropagation(document.getElementById('roiCard'));
            L.DomEvent.disableScrollPropagation(document.getElementById('roiCard'));
            L.DomEvent.disableClickPropagation(document.getElementById('historyPanel'));
            L.DomEvent.disableScrollPropagation(document.getElementById('historyPanel'));

            map.on('click', async function (e) {
                if (drawnItems.getLayers().length > 0 && currentROIGeometry) return;
                const lat = e.latlng.lat, lon = e.latlng.lng, keys = getDatasetKeys();
                const popup = L.popup().setLatLng(e.latlng).setContent('<i>Consultando ponto...</i>').openOn(map);
                try {
                    const response = await fetch(`/ndvi/point?lat=${lat}&lon=${lon}&red_key=${keys.red}&nir_key=${keys.nir}`);
                    const data = await response.json();
                    if (response.ok && data.valid) {
                        popup.setContent(`
                            <div style="font-size:13px; min-width:170px;">
                                <b style="color:#10b981;">📍 Inspeção de Ponto</b><br>
                                <b>NDVI:</b> <span style="color:#059669; font-size:15px; font-weight:bold;">${data.ndvi}</span><br>
                                <b>Classe:</b> ${data.classification}<br>
                                <hr style="margin:6px 0; border:0; border-top:1px solid #e5e7eb;">
                                <small><b>Lat:</b> ${data.latitude.toFixed(4)} | <b>Lon:</b> ${data.longitude.toFixed(4)}</small>
                            </div>
                        `);
                    } else { popup.setContent(`<span style="color:#ef4444;">${data.message || 'Ponto fora da área.'}</span>`); }
                } catch (err) { popup.setContent('<span style="color:#ef4444;">Erro ao consultar ponto.</span>'); }
            });

            map.on(L.Draw.Event.CREATED, async function (e) {
                drawnItems.clearLayers();
                const layer = e.layer;
                drawnItems.addLayer(layer);
                currentROIGeometry = layer.toGeoJSON().geometry;

                const roiCard = document.getElementById('roiCard');
                const roiContent = document.getElementById('roiContent');
                const exportBtn = document.getElementById('exportGeoTiffBtn');
                const exportPdfBtn = document.getElementById('exportPdfBtn');
                const saveForm = document.getElementById('saveForm');
                const chartsContainer = document.getElementById('chartsContainer');

                roiCard.style.display = 'block';
                exportBtn.style.display = 'none';
                exportPdfBtn.style.display = 'none';
                saveForm.style.display = 'none';
                chartsContainer.style.display = 'none';
                roiContent.innerHTML = '<i>Calculando estatísticas na ROI...</i>';

                const keys = getDatasetKeys();
                try {
                    const response = await fetch('/ndvi/roi-stats', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ geometry: currentROIGeometry, red_key: keys.red, nir_key: keys.nir })
                    });
                    const data = await response.json();
                    if (response.ok && data.valid) {
                        currentROIStats = data;
                        roiContent.innerHTML = `
                            <div class="roi-stat-row"><span>Área Total:</span><b>${data.area_ha} ha</b></div>
                            <div class="roi-stat-row"><span>Média:</span><b style="color:#059669;">${data.mean_ndvi}</b></div>
                            <div class="roi-stat-row"><span>Mín / Máx:</span><b>${data.min_ndvi} / ${data.max_ndvi}</b></div>
                            <div class="roi-stat-row"><span>Desvio Padrão:</span><b>${data.std_ndvi}</b></div>
                        `;
                        renderCharts(data);
                        chartsContainer.style.display = 'block';
                        exportBtn.style.display = 'block';
                        exportPdfBtn.style.display = 'block';
                        saveForm.style.display = 'block';
                    } else { roiContent.innerHTML = `<span style="color:#ef4444;">${data.message || 'Sem dados.'}</span>`; }
                } catch (err) { roiContent.innerHTML = '<span style="color:#ef4444;">Erro no cálculo.</span>'; }
            });

            loadXYZTileLayer();
            setTimeout(() => { map.invalidateSize(); }, 300);
        });

        function getDatasetKeys() {
            const ds = document.getElementById('dataset').value;
            return ds === 'sentinel' ? { red: 'sentinel_red.tif', nir: 'sentinel_nir.tif' } : { red: 'red_band.tif', nir: 'nir_band.tif' };
        }

        function renderCharts(data) {
            if (donutChartInstance) donutChartInstance.destroy();
            if (histChartInstance) histChartInstance.destroy();
            const donutCtx = document.getElementById('donutChart').getContext('2d');
            const classLabels = [], classPcts = [], classColors = ['#3b82f6', '#f59e0b', '#d9f99d', '#84cc16', '#15803d'];
            for (const [k, v] of Object.entries(data.classes)) { classLabels.push(v.label); classPcts.push(v.pct); }
            donutChartInstance = new Chart(donutCtx, {
                type: 'doughnut',
                data: { labels: classLabels, datasets: [{ data: classPcts, backgroundColor: classColors }] },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, font: { size: 10 } } } } }
            });
            if (data.histogram) {
                const histCtx = document.getElementById('histChart').getContext('2d');
                histChartInstance = new Chart(histCtx, {
                    type: 'bar',
                    data: { labels: data.histogram.labels, datasets: [{ label: 'Píxeis', data: data.histogram.counts, backgroundColor: '#10b981' }] },
                    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { font: { size: 9 } } }, y: { ticks: { font: { size: 9 } } } } }
                });
            }
        }

        async function downloadPDF() {
            if (!currentROIStats) return;
            const nameInput = document.getElementById('roiName').value.trim() || "Talhão Sem Nome";
            const indexType = document.getElementById('indexType').value;
            const response = await fetch('/ndvi/export-pdf', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: nameInput, index_type: indexType, stats: currentROIStats })
            });
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a'); a.href = url; a.download = `relatorio_${Date.now()}.pdf`; a.click();
        }

        async function saveCurrentROI() {
            const name = document.getElementById('roiName').value.trim();
            if (!name) return alert('Insira um nome para a ROI.');
            const payload = { name: name, index_type: document.getElementById('indexType').value, dataset: document.getElementById('dataset').value, geometry: currentROIGeometry, area_ha: currentROIStats.area_ha, total_pixels: currentROIStats.total_pixels, mean_val: currentROIStats.mean_ndvi, min_val: currentROIStats.min_ndvi, max_val: currentROIStats.max_ndvi, std_val: currentROIStats.std_ndvi || 0.0, classes: currentROIStats.classes };
            try {
                const response = await fetch('/ndvi/roi/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
                if (response.ok) { alert('ROI guardada!'); document.getElementById('roiName').value = ''; loadHistory(); }
            } catch (err) { alert('Erro ao guardar ROI.'); }
        }

        async function loadHistory() {
            const listDiv = document.getElementById('historyList');
            try {
                const response = await fetch('/ndvi/roi/history');
                const history = await response.json();
                if (!history.length) { listDiv.innerHTML = '<i>Nenhum registo.</i>'; return; }
                let html = '';
                history.forEach(item => {
                    html += `<div class="history-item"><div class="history-title" onclick="renderSavedROI('${encodeURIComponent(JSON.stringify(item))}')"><span>${item.name}</span><span style="color:#ef4444;" onclick="event.stopPropagation(); deleteROI(${item.id})">✕</span></div><div onclick="renderSavedROI('${encodeURIComponent(JSON.stringify(item))}')"><small>${item.created_at} | ${item.index_type.toUpperCase()}</small><br><b>${item.area_ha} ha</b> | Média: <b>${item.mean_val}</b></div></div>`;
                });
                listDiv.innerHTML = html;
            } catch (err) { listDiv.innerHTML = 'Erro ao carregar histórico.'; }
        }

        function renderSavedROI(encodedData) {
            const item = JSON.parse(decodeURIComponent(encodedData));
            if (drawnItems) drawnItems.clearLayers();
            const layer = L.geoJSON(item.geometry, { style: { color: '#10b981', weight: 3, fillOpacity: 0.3 } });
            if (drawnItems) drawnItems.addLayer(layer);
            map.fitBounds(layer.getBounds());
            document.getElementById('roiCard').style.display = 'block';
            document.getElementById('saveForm').style.display = 'none';
            document.getElementById('exportPdfBtn').style.display = 'block';
            currentROIStats = { area_ha: item.area_ha, total_pixels: item.total_pixels || 0, mean_ndvi: item.mean_val, min_ndvi: item.min_val, max_ndvi: item.max_val, std_val: item.std_val || 0.0, classes: item.classes || {} };
            document.getElementById('roiContent').innerHTML = `<div style="font-weight:bold; color:#10b981; margin-bottom:4px;">📌 ${item.name}</div><div class="roi-stat-row"><span>Área Total:</span><b>${item.area_ha} ha</b></div><div class="roi-stat-row"><span>Média:</span><b style="color:#059669;">${item.mean_val}</b></div><div class="roi-stat-row"><span>Mín / Máx:</span><b>${item.min_val} / ${item.max_val}</b></div>`;
            if (item.classes) { renderCharts({ classes: item.classes, histogram: null }); document.getElementById('chartsContainer').style.display = 'block'; }
        }

        async function deleteROI(id) { if (!confirm('Eliminar registo?')) return; await fetch(`/ndvi/roi/${id}`, { method: 'DELETE' }); loadHistory(); }
        function toggleHistory() { const panel = document.getElementById('historyPanel'); panel.style.display = panel.style.display === 'block' ? 'none' : 'block'; if (panel.style.display === 'block') loadHistory(); }
        async function downloadGeoTIFF() { if (!currentROIGeometry) return; const keys = getDatasetKeys(); const response = await fetch('/ndvi/export-geotiff', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ geometry: currentROIGeometry, red_key: keys.red, nir_key: keys.nir }) }); const blob = await response.blob(); const url = window.URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `recorte_${Date.now()}.tif`; a.click(); }
        function clearROI() { if (drawnItems) drawnItems.clearLayers(); currentROIGeometry = null; document.getElementById('roiCard').style.display = 'none'; }

        function addLegend() {
            if (legendControl) return;
            legendControl = L.control({ position: 'bottomright' });
            legendControl.onAdd = function () {
                const div = L.DomUtil.create('div', 'legend');
                div.innerHTML = `<div class="legend-title" id="legendTitle">Índice Espectral</div><div class="legend-bar" id="legendBar"></div><div class="legend-labels" id="legendLabels"></div>`;
                return div;
            };
            legendControl.addTo(map);
            updateLegend();
        }

        function updateLegend() {
            const indexType = document.getElementById('indexType').value;
            const bar = document.getElementById('legendBar'), title = document.getElementById('legendTitle'), labels = document.getElementById('legendLabels');
            if (!bar) return;
            if (indexType === 'ndwi') {
                title.innerText = "Índice NDWI (Água)";
                bar.style.background = 'linear-gradient(to right, #ffffff, #60a5fa, #1d4ed8)';
                labels.innerHTML = '<span>-1.0</span><span>0.0</span><span>+1.0</span>';
            } else {
                title.innerText = "Índice " + indexType.toUpperCase();
                bar.style.background = 'linear-gradient(to right, red, yellow, green)';
                labels.innerHTML = '<span>-1.0</span><span>0.0</span><span>+1.0</span>';
            }
        }

        function updateTileLayer() {
            const colormap = document.getElementById('colormap').value;
            const indexType = document.getElementById('indexType').value;
            const keys = getDatasetKeys();
            if (ndviTileLayer && map) map.removeLayer(ndviTileLayer);
            ndviTileLayer = L.tileLayer(`/ndvi/tiles/{z}/{x}/{y}.png?red_key=${keys.red}&nir_key=${keys.nir}&colormap=${colormap}&index_type=${indexType}`, { maxZoom: 18, opacity: 0.85 }).addTo(map);
            updateLegend();
        }

        async function loadXYZTileLayer() { addLegend(); updateTileLayer(); }
    </script>
</body>
</html>
"""

# Gravação dos ficheiros no disco
for path, content in files.items():
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[✓] Ficheiro gerado: {path}")

print("\n=== ESTRUTURA E FICHEIROS GERADOS COM SUCESSO! ===")

import numpy as np
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

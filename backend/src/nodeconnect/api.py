import json
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .cleaning import build_quality_summary, clean_observations
from .config import PROCESSED_DATA_DIR, RAW_DATA_DIR, REPORTS_DIR

app = FastAPI(title="NodeConnect API", version="0.1.0")

# Mount report assets if directory exists
if (REPORTS_DIR / "assets").exists():
    app.mount("/reports/assets", StaticFiles(directory=str(REPORTS_DIR / "assets")), name="report_assets")


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"project": "NodeConnect", "status": "running"}


@app.post("/api/v1/scans")
def create_scan(scan_id: str, name: str | None = None) -> dict[str, str | None]:
    if not scan_id.strip():
        raise HTTPException(status_code=400, detail="scan_id is required")
    return {"scan_id": scan_id, "name": name or scan_id}


@app.post("/api/v1/scans/{scan_id}/import")
async def import_scan(scan_id: str, file: UploadFile = File(...)) -> dict[str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="A CSV file is required")
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    raw_dir = RAW_DATA_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    target_path = raw_dir / f"{scan_id}.csv"

    contents = await file.read()
    target_path.write_bytes(contents)

    return {"scan_id": scan_id, "stored_at": str(target_path), "status": "imported"}


@app.get("/api/v1/scans/{scan_id}/quality")
def quality_report(scan_id: str) -> dict[str, object]:
    path = PROCESSED_DATA_DIR / f"{scan_id}.csv"
    if not path.exists():
        fallback = RAW_DATA_DIR / f"{scan_id}.csv"
        if not fallback.exists():
            raise HTTPException(status_code=404, detail="Scan dataset not found")
        path = fallback

    df = pd.read_csv(path)
    cleaned = clean_observations(df)
    summary = build_quality_summary(cleaned)
    return {"scan_id": scan_id, **summary}


@app.get("/api/v1/scans/{scan_id}/report", response_class=FileResponse)
def get_scan_report(scan_id: str) -> FileResponse:
    report_file = REPORTS_DIR / "wifi_survey_report.html"
    if not report_file.exists():
        raise HTTPException(status_code=404, detail="Report HTML template not found")
    return FileResponse(str(report_file), media_type="text/html")


@app.get("/api/v1/scans/{scan_id}/report/data")
def get_scan_report_data(scan_id: str) -> dict[str, object]:
    json_path = PROCESSED_DATA_DIR / f"{scan_id}_report_data.json"
    if not json_path.exists():
        # Fallback to general scan_1_report_data.json
        json_path = PROCESSED_DATA_DIR / "scan_1_report_data.json"
        if not json_path.exists():
            raise HTTPException(status_code=404, detail="Report dataset not found")
    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/v1/scans/{scan_id}/report/pdf", response_class=FileResponse)
def get_scan_report_pdf(scan_id: str) -> FileResponse:
    pdf_file = REPORTS_DIR / "wifi_survey_report.pdf"
    if not pdf_file.exists():
        raise HTTPException(status_code=404, detail="Report PDF not found")
    return FileResponse(
        str(pdf_file),
        media_type="application/pdf",
        filename=f"wifi_survey_report_{scan_id}.pdf"
    )


@app.get("/api/v1/scans/{scan_id}/report/csv", response_class=FileResponse)
def get_scan_report_csv(scan_id: str, view: str = "complete") -> FileResponse:
    if view == "coordinates" or view == "heatmap":
        csv_file = REPORTS_DIR / "scan_1_spatial_heatmap_coordinates.csv"
        filename = f"scan_{scan_id}_spatial_heatmap_coordinates.csv"
    elif view == "aps":
        csv_file = REPORTS_DIR / "scan_1_access_points.csv"
        filename = f"scan_{scan_id}_access_points.csv"
    else:
        csv_file = REPORTS_DIR / "scan_1_complete_survey_export.csv"
        filename = f"scan_{scan_id}_complete_survey_export.csv"

    if not csv_file.exists():
        raise HTTPException(status_code=404, detail=f"Report CSV ({view}) not found")
    return FileResponse(
        str(csv_file),
        media_type="text/csv",
        filename=filename
    )


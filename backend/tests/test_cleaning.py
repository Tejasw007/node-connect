import pandas as pd

from nodeconnect.cleaning import build_quality_summary, clean_observations
from nodeconnect.ocr import _summarize_ocr_data


def test_missing_rssi_flagged():
    df = pd.DataFrame({"rssi_dbm": [None, -60, -75]})
    result = clean_observations(df)

    assert result["missing_rssi"].tolist() == [True, False, False]
    assert result["review_status"].tolist() == ["needs_review", "accepted", "accepted"]


def test_out_of_range_rssi_flagged():
    df = pd.DataFrame({"rssi_dbm": [-121, -60, 5]})
    result = clean_observations(df)

    assert result["rssi_outside_guardrail"].tolist() == [True, False, True]
    assert result["quality_status"].tolist() == [
        "needs_review_rssi_range",
        "candidate_valid",
        "needs_review_rssi_range",
    ]


def test_quality_summary_counts_valid_rows():
    df = pd.DataFrame({"rssi_dbm": ["-60", "-70", "invalid", None]})
    summary = build_quality_summary(df)

    assert summary["rows"] == 4
    assert summary["missing_rssi"] == 1
    assert summary["invalid_rssi"] == 1
    assert summary["needs_review"] >= 2
    assert summary["median_rssi_dbm"] == -65.0


def test_ocr_summary_groups_words_and_reports_confidence():
    data = {
        "text": ["", "NodeConnect", "", "RSSI", "-60"],
        "conf": ["-1", "90", "-1", "95", "40"],
        "level": [1, 5, 4, 5, 5],
        "block_num": [0, 1, 1, 1, 1],
        "par_num": [0, 1, 1, 1, 1],
        "line_num": [0, 1, 1, 2, 2],
    }

    text, words, mean_confidence, confident_words = _summarize_ocr_data(data)

    assert text == "NodeConnect\nRSSI -60"
    assert words == 3
    assert mean_confidence == 75.0
    assert confident_words == 2


def test_survey_report_data_and_html_integrity():
    import json
    from nodeconnect.config import PROCESSED_DATA_DIR, REPORTS_DIR

    json_file = PROCESSED_DATA_DIR / "scan_1_report_data.json"
    assert json_file.exists(), "scan_1_report_data.json must exist"

    with json_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["report_metadata"]["scan_id"] == "Scan 1"
    assert data["executive_kpis"]["samples_collected"] == 404
    assert data["executive_kpis"]["unique_access_points"] == 275
    assert data["coverage_breakdown"]["excellent"]["percentage"] == 9
    assert data["coverage_breakdown"]["dead"]["percentage"] == 13

    html_file = REPORTS_DIR / "wifi_survey_report.html"
    assert html_file.exists(), "wifi_survey_report.html must exist"
    html_text = html_file.read_text(encoding="utf-8")
    assert "Jain_Student" in html_text
    assert "Download PDF" in html_text
    assert "CSV Export" in html_text
    assert "@media print" in html_text
    assert "heatmapCanvas" in html_text
    assert "measurement_points" in html_text


def test_survey_pdf_and_csv_exports():
    from nodeconnect.config import REPORTS_DIR

    pdf_file = REPORTS_DIR / "wifi_survey_report.pdf"
    assert pdf_file.exists(), "wifi_survey_report.pdf must be generated"
    assert pdf_file.stat().st_size > 100000, "PDF should be fully rendered"

    coord_csv = REPORTS_DIR / "scan_1_spatial_heatmap_coordinates.csv"
    assert coord_csv.exists(), "Heatmap coordinates CSV must exist"
    lines = coord_csv.read_text(encoding="utf-8-sig").splitlines()
    assert len(lines) > 200, "Should contain >200 coordinate observation points"
    assert "x_coord_meters" in lines[0]
    assert "signal_strength_dbm" in lines[0]

    master_csv = REPORTS_DIR / "scan_1_complete_survey_export.csv"
    assert master_csv.exists(), "Master CSV export must exist"
    content = master_csv.read_text(encoding="utf-8-sig")
    assert "Jain_Student" in content
    assert "HEATMAP COORDINATES & SIGNAL STRENGTH" in content


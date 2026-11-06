from __future__ import annotations

import argparse
import csv
import os
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps
from pytesseract import Output

from .config import PROCESSED_DATA_DIR, RAW_DATA_DIR

_OCR_CONFIG = "--psm 12"
_CONFIDENT_WORD_THRESHOLD = 60.0


def _configure_tesseract() -> None:
    configured_command = os.environ.get("TESSERACT_CMD")
    if configured_command:
        resolved_command = shutil.which(configured_command) or configured_command
        if not Path(resolved_command).is_file():
            raise FileNotFoundError(
                "TESSERACT_CMD does not point to a Tesseract executable."
            )
        pytesseract.pytesseract.tesseract_cmd = resolved_command
        return

    command = shutil.which("tesseract")
    if command:
        pytesseract.pytesseract.tesseract_cmd = command
        return

    local_app_data = os.environ.get("LOCALAPPDATA")
    candidates = [
        Path(local_app_data) / "Programs" / "Tesseract-OCR" / "tesseract.exe"
        if local_app_data
        else None,
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Tesseract-OCR"
        / "tesseract.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Tesseract-OCR"
        / "tesseract.exe",
    ]
    executable = next((path for path in candidates if path and path.is_file()), None)
    if executable is None:
        raise FileNotFoundError(
            "Tesseract was not found. Install Tesseract OCR or set TESSERACT_CMD."
        )
    pytesseract.pytesseract.tesseract_cmd = str(executable)


def _summarize_ocr_data(
    data: Mapping[str, Sequence[object]],
) -> tuple[str, int, float, int]:
    required_fields = (
        "text",
        "conf",
        "level",
        "block_num",
        "par_num",
        "line_num",
    )
    rows = zip(*(data[field] for field in required_fields), strict=True)
    text_by_line: dict[tuple[int, int, int], list[str]] = {}
    confidences: list[float] = []
    detected_words = 0

    for raw_text, raw_confidence, raw_level, raw_block, raw_paragraph, raw_line in rows:
        word = str(raw_text).strip()
        if int(raw_level) != 5 or not word:
            continue

        detected_words += 1
        confidence = float(raw_confidence)
        if confidence >= 0:
            confidences.append(confidence)

        line_key = (int(raw_block), int(raw_paragraph), int(raw_line))
        text_by_line.setdefault(line_key, []).append(word)

    text = "\n".join(" ".join(words) for words in text_by_line.values())
    mean_confidence = (
        round(sum(confidences) / len(confidences), 1) if confidences else 0.0
    )
    confident_words = sum(
        confidence >= _CONFIDENT_WORD_THRESHOLD for confidence in confidences
    )
    return text, detected_words, mean_confidence, confident_words


def extract_image_text(path: Path) -> dict[str, object]:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        width, height = image.size
        data = pytesseract.image_to_data(
            image,
            lang="eng",
            config=_OCR_CONFIG,
            output_type=Output.DICT,
            timeout=120,
        )

    text, detected_words, mean_confidence, confident_words = _summarize_ocr_data(data)
    return {
        "source_image": path.name,
        "review_status": "unreviewed",
        "image_width_px": width,
        "image_height_px": height,
        "detected_words": detected_words,
        "mean_word_confidence_0_100": mean_confidence,
        "words_with_confidence_at_least_60": confident_words,
        "ocr_text": text,
    }


def process_image_directory(
    input_dir: Path,
    output_dir: Path,
    *,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input image directory does not exist: {input_dir}")
    if input_dir.resolve() == output_dir.resolve():
        raise ValueError("OCR output must not be written into the source-image folder.")

    images = sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if not images:
        raise FileNotFoundError(f"No supported images found in {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "ocr_candidates.csv"
    text_path = output_dir / "ocr_candidates.txt"
    if not overwrite and (csv_path.exists() or text_path.exists()):
        raise FileExistsError(
            f"OCR output already exists in {output_dir}; pass --overwrite to replace it."
        )

    _configure_tesseract()
    results: list[dict[str, object]] = []
    for index, image_path in enumerate(images, start=1):
        result = extract_image_text(image_path)
        results.append(result)
        print(
            f"[{index}/{len(images)}] {image_path.name}: "
            f"{result['detected_words']} words, "
            f"mean confidence {result['mean_word_confidence_0_100']}/100"
        )

    fieldnames = list(results[0])
    with csv_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    text_sections = [
        "NodeConnect batch OCR — UNVERIFIED candidate text from source photographs.",
        "Review every identifier, RSSI value, minus sign, timestamp, and coordinate against its source image.",
        "Mean OCR confidence is a software score, not an accuracy percentage.",
    ]
    for result in results:
        text_sections.extend(
            [
                "",
                (
                    f"===== {result['source_image']} | "
                    f"words={result['detected_words']} | "
                    f"mean_confidence={result['mean_word_confidence_0_100']}/100 ====="
                ),
                str(result["ocr_text"]) or "[No text recognized]",
            ]
        )
    text_path.write_text("\n".join(text_sections) + "\n", encoding="utf-8")
    return csv_path, text_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract unverified OCR text from NodeConnect survey photos."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=RAW_DATA_DIR / "DMGT EL",
        help="Folder containing source images (default: data/raw/DMGT EL).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROCESSED_DATA_DIR / "DMGT EL",
        help="Folder for OCR review files (default: data/processed/DMGT EL).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing OCR output files.",
    )
    args = parser.parse_args()

    csv_path, text_path = process_image_directory(
        args.input,
        args.output,
        overwrite=args.overwrite,
    )
    print(f"Review CSV: {csv_path}")
    print(f"Review text: {text_path}")


if __name__ == "__main__":
    main()

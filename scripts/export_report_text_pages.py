"""Export annual-report PDF pages to reviewable text rows."""

from argparse import ArgumentParser
from pathlib import Path
import re

import pandas as pd


FILENAME_PATTERN = re.compile(r"(?P<ticker>\d{6}\.(?:SZ|SH))_(?P<company>[^_]+)_(?P<date>\d{4}-\d{2}-\d{2})_")


def _load_pdfplumber():
    """按需导入 pdfplumber，避免主研究流程依赖 PDF 解析包。"""
    try:
        import pdfplumber
    except ImportError as exc:
        raise SystemExit("请先运行: pip install -r requirements-data.txt") from exc
    return pdfplumber


def _parse_report_meta(pdf_path: Path) -> dict:
    """从年报 PDF 文件名解析股票代码、公司名和披露日期。"""
    match = FILENAME_PATTERN.search(pdf_path.name)
    if not match:
        return {"ticker": "", "company_name": "", "report_date": ""}
    return {
        "ticker": match.group("ticker"),
        "company_name": match.group("company"),
        "report_date": match.group("date"),
    }


def clean_page_text(text: str, dedupe_chars: bool = False) -> str:
    """清洗 PDF 文本，保留换行和可打印字符。

    `dedupe_chars` 只用于少数 PDF 解析出现重复字符时的兜底处理，默认关闭，
    避免误删中文词语中的正常重复字。
    """
    if not text:
        return ""

    text = "".join(char for char in text if char.isprintable() or char in "\n\t")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    if not dedupe_chars:
        return text.strip()

    chars = []
    for char in text:
        if chars and char == chars[-1] and not char.isascii():
            continue
        chars.append(char)
    return "".join(chars).strip()


def export_report_text_pages(pdf_paths: list[Path], dedupe_chars: bool = False) -> pd.DataFrame:
    """逐页导出年报 PDF 文本，保留页码用于证据追溯。"""
    pdfplumber = _load_pdfplumber()
    rows = []

    for pdf_path in pdf_paths:
        meta = _parse_report_meta(pdf_path)
        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                for page_number, page in enumerate(pdf.pages, start=1):
                    raw_text = page.extract_text() or ""
                    text = clean_page_text(raw_text, dedupe_chars=dedupe_chars)
                    rows.append(
                        {
                            **meta,
                            "pdf_file": pdf_path.name,
                            "page_number": page_number,
                            "total_pages": total_pages,
                            "text_length": len(text),
                            "text": text,
                        }
                    )
        except Exception as exc:  # noqa: BLE001 - 单个 PDF 失败不影响整体导出
            rows.append(
                {
                    **meta,
                    "pdf_file": pdf_path.name,
                    "page_number": "",
                    "total_pages": "",
                    "text_length": 0,
                    "text": "",
                    "error": str(exc),
                }
            )

    return pd.DataFrame(rows)


def main() -> None:
    """命令行入口。"""
    parser = ArgumentParser(description="Export report PDF pages to text rows for downstream review.")
    parser.add_argument("--pdf-dir", default="data/raw/reports/2025", help="年报 PDF 目录")
    parser.add_argument("--output", default="data/raw/report_text_pages_2025.csv", help="逐页文本输出 CSV")
    parser.add_argument("--dedupe-chars", action="store_true", help="清理疑似 PDF 解析重复字符")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    pdf_dir = project_root / args.pdf_dir
    output_path = project_root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf_paths = sorted(path for path in pdf_dir.glob("*.pdf") if path.is_file())
    pages = export_report_text_pages(pdf_paths, dedupe_chars=args.dedupe_chars)
    pages.to_csv(output_path, index=False, encoding="utf-8-sig")

    print(f"Saved {len(pages):,} page rows from {len(pdf_paths):,} PDFs to {output_path}")


if __name__ == "__main__":
    main()

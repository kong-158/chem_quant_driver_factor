"""Extract capacity-related text snippets from annual-report PDFs.

The output is a review table, not a final structured capacity dataset. Annual
reports often mix product, line, project and subsidiary capacities, so manual
verification remains necessary before writing data/raw/product_capacity.csv.
"""

from argparse import ArgumentParser
from pathlib import Path

import pandas as pd


CAPACITY_TERMS = ["产能", "生产能力", "设计能力", "设计产能", "万吨/年", "吨/年"]


def _load_pdfplumber():
    """按需导入 pdfplumber，避免主流程依赖 PDF 解析包。"""
    try:
        import pdfplumber
    except ImportError as exc:
        raise SystemExit("请先运行: pip install -r requirements-data.txt") from exc
    return pdfplumber


def _load_product_keywords(project_root: Path) -> list[str]:
    """从产品-driver 映射中读取需要关注的产品关键词。"""
    path = project_root / "config" / "product_driver_map.csv"
    if not path.exists():
        return []
    product_map = pd.read_csv(path)
    return sorted(product_map["product_name"].dropna().astype(str).unique())


def _snippet(text: str, keyword: str, width: int = 180) -> str:
    """围绕关键词截取短文本，方便人工复核。"""
    position = text.find(keyword)
    if position < 0:
        return text[: width * 2]
    start = max(position - width, 0)
    end = min(position + width, len(text))
    return text[start:end].replace("\n", " ")


def extract_snippets(pdf_paths: list[Path], product_keywords: list[str]) -> pd.DataFrame:
    """从 PDF 中抽取含产能词或产品词的页面片段。"""
    pdfplumber = _load_pdfplumber()
    rows = []
    keywords = list(dict.fromkeys(CAPACITY_TERMS + product_keywords))

    for pdf_path in pdf_paths:
        with pdfplumber.open(pdf_path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                matched = [keyword for keyword in keywords if keyword in text]
                if not matched or not any(term in text for term in CAPACITY_TERMS):
                    continue

                rows.append(
                    {
                        "pdf_file": str(pdf_path),
                        "page_number": page_number,
                        "matched_keywords": ";".join(matched[:20]),
                        "snippet": _snippet(text, matched[0]),
                    }
                )

    return pd.DataFrame(rows)


def main() -> None:
    """命令行入口。"""
    parser = ArgumentParser(description="Extract capacity-related snippets from annual-report PDFs.")
    parser.add_argument("--pdf-dir", default="data/raw/reports", help="PDF 所在目录")
    parser.add_argument("--output", default="data/raw/capacity_snippets.csv", help="输出 CSV 路径")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    pdf_dir = project_root / args.pdf_dir
    output_path = project_root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf_paths = sorted(pdf_dir.glob("*.pdf"))
    product_keywords = _load_product_keywords(project_root)
    snippets = extract_snippets(pdf_paths, product_keywords)
    snippets.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Saved {len(snippets):,} rows to {output_path}")


if __name__ == "__main__":
    main()

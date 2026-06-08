"""Download CNINFO report PDFs from announcement metadata."""

from argparse import ArgumentParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import requests


CNINFO_DETAIL_API = "http://www.cninfo.com.cn/new/announcement/bulletin_detail"
CNINFO_STATIC_HOST = "http://static.cninfo.com.cn"


def _announcement_id_from_url(url: str) -> str:
    """从巨潮公告详情链接中解析 announcementId。"""
    query = parse_qs(urlparse(str(url)).query)
    values = query.get("announcementId")
    if not values:
        raise ValueError(f"公告链接缺少 announcementId: {url}")
    return values[0]


def _safe_filename(value: str) -> str:
    """生成适合作为文件名的字符串。"""
    keep = []
    for char in str(value):
        if char.isalnum() or char in ["-", "_", "."]:
            keep.append(char)
        else:
            keep.append("_")
    return "".join(keep).strip("_")


def get_pdf_url(row: pd.Series, session: requests.Session) -> str:
    """调用巨潮公告详情接口，获取 PDF 附件 URL。"""
    announcement_id = _announcement_id_from_url(row["公告链接"])
    params = {
        "announceId": announcement_id,
        "flag": "true",
        "announceTime": row["公告时间"],
    }
    response = session.post(
        CNINFO_DETAIL_API,
        params=params,
        timeout=30,
        headers={
            "Referer": row["公告链接"],
            "User-Agent": "Mozilla/5.0",
        },
    )
    response.raise_for_status()
    data = response.json()
    adjunct_url = data.get("announcement", {}).get("adjunctUrl")
    if not adjunct_url:
        raise ValueError(f"未找到 PDF 附件: {row.get('ticker')} {row.get('公告标题')}")
    return f"{CNINFO_STATIC_HOST}/{adjunct_url}"


def download_reports(metadata_path: Path, output_dir: Path) -> pd.DataFrame:
    """下载公告元数据对应的 PDF，并返回下载清单。"""
    metadata = pd.read_csv(metadata_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    rows = []

    for _, item in metadata.iterrows():
        ticker = item.get("ticker", "")
        company_name = item.get("company_name", item.get("简称", ""))
        announcement_time = str(item.get("公告时间", ""))
        announcement_title = item.get("公告标题", "")
        announcement_id = _announcement_id_from_url(item["公告链接"])

        try:
            pdf_url = get_pdf_url(item, session)
            filename = _safe_filename(f"{ticker}_{company_name}_{announcement_time}_{announcement_id}_{announcement_title}.pdf")
            pdf_path = output_dir / filename

            with session.get(pdf_url, timeout=60, headers={"User-Agent": "Mozilla/5.0"}, stream=True) as response:
                response.raise_for_status()
                with pdf_path.open("wb") as file:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            file.write(chunk)

            status = "success"
            error = ""
        except Exception as exc:  # noqa: BLE001 - 单个 PDF 失败不影响其他公司
            pdf_url = ""
            pdf_path = Path("")
            status = "failed"
            error = str(exc)
            print(f"[WARN] {ticker} {company_name} 下载失败: {error}")

        rows.append(
            {
                "ticker": ticker,
                "company_name": company_name,
                "announcement_time": announcement_time,
                "announcement_title": announcement_title,
                "announcement_id": announcement_id,
                "pdf_url": pdf_url,
                "pdf_path": str(pdf_path),
                "status": status,
                "error": error,
            }
        )

    return pd.DataFrame(rows)


def main() -> None:
    """命令行入口。"""
    parser = ArgumentParser(description="Download CNINFO report PDFs from metadata CSV.")
    parser.add_argument("--metadata", default="data/raw/cninfo_latest_reports.csv", help="公告元数据 CSV")
    parser.add_argument("--output-dir", default="data/raw/reports/2025", help="PDF 输出目录")
    parser.add_argument("--manifest", default="data/raw/cninfo_pdf_manifest.csv", help="下载清单输出路径")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    manifest = download_reports(project_root / args.metadata, project_root / args.output_dir)

    manifest_path = project_root / args.manifest
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(manifest_path, index=False, encoding="utf-8-sig")
    print(f"Saved manifest to {manifest_path}")
    print(manifest["status"].value_counts().to_string())


if __name__ == "__main__":
    main()

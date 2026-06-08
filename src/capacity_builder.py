import pandas as pd


CAPACITY_COLUMNS = [
    "ticker",
    "company_name",
    "sub_industry",
    "report_year",
    "report_date",
    "product_name",
    "capacity",
    "capacity_unit",
]

PRODUCT_DRIVER_COLUMNS = [
    "product_name",
    "driver_name",
    "driver_direction",
    "driver_share",
    "exposure_type",
]


def build_capacity_weight_mapping(
    product_capacity: pd.DataFrame,
    product_driver_map: pd.DataFrame,
) -> pd.DataFrame:
    """用产品产能占比生成公司-driver 权重。

    权重计算逻辑：
    1. 同一公司、同一报告期内，先计算各产品产能占比；
    2. 再通过 product_driver_map 映射到价格 driver；
    3. driver_direction 可表达产品价格正向暴露或原料价格负向暴露；
    4. report_date 作为 effective_date，避免在披露日前使用未来产能信息。
    """
    missing_capacity_cols = set(CAPACITY_COLUMNS) - set(product_capacity.columns)
    if missing_capacity_cols:
        raise ValueError(f"product_capacity 缺少字段: {sorted(missing_capacity_cols)}")

    missing_map_cols = set(PRODUCT_DRIVER_COLUMNS) - set(product_driver_map.columns)
    if missing_map_cols:
        raise ValueError(f"product_driver_map 缺少字段: {sorted(missing_map_cols)}")

    capacity = product_capacity[CAPACITY_COLUMNS].copy()
    capacity["report_year"] = pd.to_numeric(capacity["report_year"], errors="coerce").astype("Int64")
    capacity["report_date"] = pd.to_datetime(capacity["report_date"])
    capacity["capacity"] = pd.to_numeric(capacity["capacity"], errors="coerce")
    capacity = capacity.dropna(subset=["ticker", "report_date", "product_name", "capacity"])
    capacity = capacity[capacity["capacity"] > 0].copy()

    product_map = product_driver_map[PRODUCT_DRIVER_COLUMNS].copy()
    product_map["driver_direction"] = pd.to_numeric(product_map["driver_direction"], errors="coerce").fillna(1.0)
    product_map["driver_share"] = pd.to_numeric(product_map["driver_share"], errors="coerce").fillna(1.0)

    merged = capacity.merge(product_map, on="product_name", how="inner")
    if merged.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "company_name",
                "sub_industry",
                "driver_name",
                "driver_weight",
                "effective_date",
                "end_date",
                "weight_source",
            ]
        )

    group_cols = ["ticker", "report_date"]
    merged["total_capacity"] = merged.groupby(group_cols)["capacity"].transform("sum")
    merged["product_capacity_weight"] = merged["capacity"] / merged["total_capacity"]
    merged["driver_weight"] = (
        merged["product_capacity_weight"] * merged["driver_share"] * merged["driver_direction"]
    )

    mapping = (
        merged.groupby(
            [
                "ticker",
                "company_name",
                "sub_industry",
                "report_year",
                "report_date",
                "driver_name",
                "exposure_type",
            ],
            as_index=False,
        )
        .agg(
            driver_weight=("driver_weight", "sum"),
            product_capacity_weight=("product_capacity_weight", "sum"),
            capacity=("capacity", "sum"),
            capacity_unit=("capacity_unit", "first"),
        )
        .rename(columns={"report_date": "effective_date"})
    )

    # 用下一次披露日作为上一套权重的失效日，保证 point-in-time。
    periods = mapping[["ticker", "effective_date"]].drop_duplicates().sort_values(["ticker", "effective_date"])
    periods["end_date"] = periods.groupby("ticker")["effective_date"].shift(-1)
    mapping = mapping.merge(periods, on=["ticker", "effective_date"], how="left")
    mapping["weight_source"] = "capacity"

    ordered_cols = [
        "ticker",
        "company_name",
        "sub_industry",
        "driver_name",
        "driver_weight",
        "effective_date",
        "end_date",
        "weight_source",
        "report_year",
        "exposure_type",
        "capacity",
        "capacity_unit",
        "product_capacity_weight",
    ]
    return mapping[ordered_cols].sort_values(["ticker", "effective_date", "driver_name"]).reset_index(drop=True)

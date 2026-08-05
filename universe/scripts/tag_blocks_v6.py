"""
v6/scripts/tag_blocks_v6.py
===========================
Rule-based auto-tagger for the `block` column of `data/universe_v6/catalogue.csv`.

Resolves IMPLEMENTATION_PLAN.md D1 option C: substring/regex rules on
`underlying_name` (with `fund_type` as tiebreaker) that map every catalogue
row to one of the nine blocks defined in universe_v6.BLOCKS. First matching
rule wins; the rule table is ordered so the highest-signal keywords fire
before catch-alls.

Default run writes `data/universe_v6/catalogue_tagged.csv` for human audit —
one row per catalogue code with the proposed block and the rule that fired.
Pass `--commit` to overwrite the `block` column in `catalogue.csv` in place
(a timestamped backup is written first). Members (ever-admitted per
membership.parquet) are always tagged; a non-member with no match falls back
to 'UNTAGGED' since Phase 8/9 only cares about admitted names.

Usage
-----
    python scripts/tag_blocks_v6.py                 # audit only
    python scripts/tag_blocks_v6.py --commit        # apply to catalogue.csv
    python scripts/tag_blocks_v6.py --members-only  # only score ever-admitted
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

_HERE = Path(__file__).resolve()
# --- v6/common sys.path bootstrap ---
import sys as _v6_sys
from pathlib import Path as _V6Path
_v6_p = _V6Path(__file__).resolve().parent
while _v6_p.name != "v6" and _v6_p.parent != _v6_p:
    _v6_p = _v6_p.parent
_v6_sys.path.insert(0, str(_v6_p / "common"))
del _v6_p
# --------------------------------------
from universe_v6 import BLOCKS  # noqa: E402


# ---------------------------------------------------------------------- #
# Rule table
# ---------------------------------------------------------------------- #
# Each rule: (compiled_regex, fund_type_filter_or_None, block, reason_slug).
# First matching rule wins. Order is deliberate — cross-border keywords
# (港股通, 标普500, ...) come BEFORE sector/broad keywords so a name like
# "中证港股通医药卫生综合指数" tags as cross_border_hk, not sector_cn.
#
# Reason slugs are short so the audit CSV stays scannable.

def _rx(*patterns: str) -> re.Pattern:
    return re.compile("|".join(patterns))


# fmt: off
RULES: List[Tuple[re.Pattern, Optional[str], str, str]] = [
    # ---------- Precious/base metals (any fund_type) ----------
    (_rx(r"黄金", r"白银", r"上海金", r"SHAU"),                     None,         "metals",           "precious_metal"),
    (_rx(r"有色金属期货"),                                          None,         "metals",           "base_metal_futures"),

    # ---------- Other soft/energy commodities ----------
    (_rx(r"豆粕", r"大豆", r"白糖", r"能源化工", r"原油", r"石油沥青"),
                                                                    None,         "commodity_other",  "ag_energy_futures"),

    # ---------- Bonds — split by rates vs credit ----------
    (_rx(r"国债", r"政策性金融债", r"国开行", r"地方政府债"),        "BondIndex",  "bond_rates",       "gov_policy_bond"),
    (_rx(r"公司债", r"信用债", r"科技创新公司债", r"城投债",
         r"可转债", r"可交换", r"短融", r"中高等级"),                "BondIndex",  "bond_credit",      "credit_bond"),
    # Bond fallback → credit (any BondIndex name we didn't recognise;
    # rarely fires and gets flagged in the audit).
    (_rx(r".*"),                                                    "BondIndex",  "bond_credit",      "bond_fallback"),

    # ---------- Cross-border — HK (港股通/恒生/沪港深) ----------
    (_rx(r"港股通", r"恒生", r"沪港深", r"沪深港", r"香港",
         r"HSSC", r"HSHK"),                                         None,         "cross_border_hk",  "hk_exposure"),

    # ---------- Cross-border — DM / global (US, JP, EU, EM, offshore CN) ----------
    (_rx(r"标普500", r"标普\d", r"标普新中国", r"标普生物",
         r"标普石油", r"标普中国海外",
         r"纳斯达克", r"道琼斯", r"MSCI美国",
         r"日经", r"东证股价", r"东京证券",
         r"DAX", r"CAC40", r"巴黎",
         r"IBOVESPA", r"巴西",
         r"沙特",
         r"富时亚太", r"富时东南亚",
         r"新交所", r"泛东南亚",
         r"韩交所", r"韩国",
         r"全球中国", r"海外中国", r"中概"),                        None,         "cross_border_dm",  "dm_or_offshore_cn"),
    # QDII fallback → DM (any QDII name whose keyword we missed).
    (_rx(r".*"),                                                    "QDII",       "cross_border_dm",  "qdii_fallback"),

    # ---------- CN smallcap ----------
    (_rx(r"中证2000", r"国证2000", r"中证小盘",
         r"中小企业100", r"中小板"),                                None,         "smallcap_cn",      "smallcap"),

    # ---------- CN sectors / themes ----------
    (_rx(r"医药", r"生物医药", r"生物科技", r"医疗", r"器械",
         r"中药", r"创新药", r"疫苗", r"健康"),                     None,         "sector_cn",        "healthcare"),
    (_rx(r"半导体", r"芯片", r"集成电路", r"电子50", r"消费电子",
         r"中证电子", r"电子指数"),                                  None,         "sector_cn",        "semiconductors"),
    (_rx(r"新能源", r"光伏", r"绿色电力", r"电池", r"锂电",
         r"风电", r"储能", r"碳中和"),                              None,         "sector_cn",        "clean_energy"),
    (_rx(r"军工", r"国防", r"航天", r"航空", r"卫星",
         r"通用航空"),                                              None,         "sector_cn",        "defense_aero"),
    (_rx(r"银行", r"券商", r"证券公司", r"证券保险",
         r"保险", r"非银", r"金融科技",
         r"800地产", r"800证券"),                                   None,         "sector_cn",        "financials"),
    (_rx(r"消费", r"食品", r"饮料", r"白酒", r"家电", r"家用电器",
         r"畜牧", r"养殖", r"粮食", r"旅游", r"中证酒",
         r"中证主要消费", r"上证消费", r"上证主要消费"),            None,         "sector_cn",        "consumer"),
    (_rx(r"有色金属指数", r"细分有色", r"工业有色",
         r"有色金属矿业", r"申万有色", r"有色金属产业",
         r"钢铁", r"煤炭", r"石化", r"化工", r"石油",
         r"天然气", r"矿业", r"稀土", r"稀有金属",
         r"自然资源", r"大宗商品", r"农业", r"农产品",
         r"油气"),                                                  None,         "sector_cn",        "materials_energy"),
    (_rx(r"建材", r"建筑材料", r"建筑", r"基建", r"工程"),          None,         "sector_cn",        "construction"),
    (_rx(r"计算机", r"软件", r"通信", r"通信设备",
         r"云计算", r"大数据", r"人工智能", r"互联网",
         r"数字经济", r"信息技术", r"信创",
         r"信息安全", r"5G", r"科技50", r"科技龙头",
         r"中证科技", r"香港科技", r"科技传媒通信",
         r"金融科技", r"传媒", r"文化", r"动漫", r"游戏",
         r"教育", r"机器人"),                                       None,         "sector_cn",        "tmt"),
    (_rx(r"新能源汽车", r"智能汽车", r"汽车与零部件",
         r"800汽车", r"汽车产业", r"汽车",
         r"工程机械", r"机床", r"高端装备"),                        None,         "sector_cn",        "auto_industrial"),
    (_rx(r"房地产", r"地产"),                                       None,         "sector_cn",        "real_estate"),
    (_rx(r"环保", r"电力", r"公用事业", r"水利", r"燃气",
         r"电网设备"),                                              None,         "sector_cn",        "utilities"),
    (_rx(r"央企", r"国企", r"国资"),                                None,         "sector_cn",        "soe_theme"),

    # ---------- CN broad — pure market-cap + broad-market factor tilts ----------
    (_rx(r"沪深300", r"中证500", r"中证800",
         r"中证A50", r"中证A100", r"中证A500", r"中证A股",
         r"中证100", r"中证1000",
         r"上证50", r"上证100", r"上证180", r"上证380",
         r"上证综合",
         r"深证100", r"深证成份", r"深证成分",
         r"深证基本面",
         r"创业板50", r"创业板指", r"创业板大盘",
         r"创业板动量", r"创业板低波", r"创业板成长",
         r"MSCI中国A", r"标普中国A",
         r"中证国信价值"),                                          None,         "broad_cn",         "broad_marketcap"),
    (_rx(r"红利", r"高股息", r"低波",
         r"自由现金流", r"红利质量", r"红利低波", r"价值100",
         r"成长100", r"大盘价值", r"大盘成长",
         r"央企创新驱动", r"央企结构调整", r"央企红利",
         r"央企股东回报", r"央企科技引领",
         r"上证红利", r"深证红利", r"上证国有企业红利"),            None,         "broad_cn",         "broad_smart_beta"),

    # ---------- Final fallback ----------
    # Any remaining CN-listed equity ETF — includes fund_type 'Stock' (used
    # for enhanced-strategy 增强ETFs on 创业板/科创板) alongside 'StockIndex'.
    (_rx(r".*"),                                                    "StockIndex", "sector_cn",        "sector_fallback"),
    (_rx(r".*"),                                                    "Stock",      "sector_cn",        "sector_fallback"),
    (_rx(r".*"),                                                    None,         "UNTAGGED",         "no_match"),
]
# fmt: on


def tag_row(underlying_name: str, fund_type: str) -> Tuple[str, str]:
    """Return (block, reason) for a single catalogue row."""
    text = underlying_name if isinstance(underlying_name, str) else ""
    for regex, ft_filter, block, reason in RULES:
        if ft_filter is not None and fund_type != ft_filter:
            continue
        if regex.search(text):
            return block, reason
    return "UNTAGGED", "no_match"


# ---------------------------------------------------------------------- #
# Driver
# ---------------------------------------------------------------------- #
def run(data_dir: Path, members_only: bool = False,
        commit: bool = False) -> pd.DataFrame:
    cat_path = data_dir / "catalogue.csv"
    mem_path = data_dir / "membership.parquet"
    cat = pd.read_csv(cat_path)

    if mem_path.exists():
        membership = pd.read_parquet(mem_path)
        ever = set(membership.columns[membership.any(axis=0)])
    else:
        print("[tag_blocks] WARNING: membership.parquet not found — treating "
              "every catalogue row as a non-member for the audit summary.")
        ever = set()

    proposed, reasons = [], []
    for _, r in cat.iterrows():
        b, why = tag_row(r.get("underlying_name", ""), r.get("fund_type", ""))
        proposed.append(b)
        reasons.append(why)

    cat_out = cat.copy()
    cat_out["ever_member"] = cat_out["code"].isin(ever)
    cat_out["current_block"] = cat_out["block"]
    cat_out["proposed_block"] = proposed
    cat_out["rule_fired"] = reasons

    if members_only:
        cat_out = cat_out[cat_out["ever_member"]].reset_index(drop=True)

    audit_cols = ["code", "name_cn", "underlying_name", "fund_type",
                  "ever_member", "current_block", "proposed_block",
                  "rule_fired"]
    audit = cat_out[audit_cols].sort_values(
        by=["ever_member", "proposed_block", "fund_type", "code"],
        ascending=[False, True, True, True],
    ).reset_index(drop=True)

    audit_path = data_dir / "catalogue_tagged.csv"
    audit.to_csv(audit_path, index=False)
    print(f"[tag_blocks] wrote {audit_path}  ({len(audit)} rows)")

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #
    print()
    print("=== proposed_block × ever_member (counts) ===")
    print(pd.crosstab(audit["proposed_block"], audit["ever_member"],
                      margins=True))
    print()
    unt_members = audit[(audit["proposed_block"] == "UNTAGGED")
                        & (audit["ever_member"])]
    if len(unt_members):
        print(f"WARNING: {len(unt_members)} ever-member codes hit no rule:")
        print(unt_members[["code", "fund_type", "underlying_name"]]
              .to_string(index=False))
        print()

    fallback_members = audit[(audit["rule_fired"].isin(
        {"sector_fallback", "bond_fallback", "qdii_fallback"}))
                             & (audit["ever_member"])]
    if len(fallback_members):
        print(f"[tag_blocks] {len(fallback_members)} ever-member codes matched "
              f"a *_fallback rule — worth eyeballing in the audit CSV.")

    # ------------------------------------------------------------------ #
    # Commit
    # ------------------------------------------------------------------ #
    if commit:
        ts = time.strftime("%Y%m%d_%H%M%S")
        backup = data_dir / f"catalogue.backup_{ts}.csv"
        shutil.copy(cat_path, backup)
        cat["block"] = proposed
        cat.to_csv(cat_path, index=False)
        print(f"[tag_blocks] committed: {cat_path}  (backup: {backup.name})")

    return audit


def main() -> None:
    ap = argparse.ArgumentParser(description="Auto-tag catalogue blocks (v6)")
    default = _HERE.parents[2] / "data" / "universe_v6"
    ap.add_argument("--data-dir", default=str(default))
    ap.add_argument("--members-only", action="store_true",
                    help="only tag ever-admitted codes in the audit CSV")
    ap.add_argument("--commit", action="store_true",
                    help="overwrite the block column in catalogue.csv")
    args = ap.parse_args()
    run(Path(args.data_dir),
        members_only=args.members_only,
        commit=args.commit)


if __name__ == "__main__":
    main()

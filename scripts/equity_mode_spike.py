"""
Equity-mode spike — decision gate for Task 2.

For each of the six organ scores (+ composite), runs an OLS regression of
score on IMD 2025 overall rank (n=33, one regression per organ) and reports:
  - slope, intercept
  - Pearson r + R²  (how much of the score variance is explained by IMD)
  - top-3 positive residuals (boroughs outperforming their IMD expectation)
  - top-3 negative residuals (boroughs underperforming)

Usage:
    python scripts/equity_mode_spike.py           # reads data/cityscan.duckdb
    python scripts/equity_mode_spike.py --read    # reads the read replica instead

Decision gate:
  - If at least 2–3 organs have |r| > 0.35 AND visually cleanly narratable
    outliers → proceed with Task 2 implementation.
  - If all organs are noisy (|r| < 0.2 everywhere) → narrow scope or skip.
"""

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
IMD_PATH = ROOT / "data" / "static" / "imd_borough.json"


def run(db_path: Path) -> int:
    with open(IMD_PATH) as f:
        imd_raw = json.load(f)
    imd_rank = {code: info["imd_rank"] for code, info in imd_raw["boroughs"].items()}
    borough_names = {code: info["name"] for code, info in imd_raw["boroughs"].items()}
    print(f"IMD: {len(imd_rank)} boroughs, rank range {min(imd_rank.values())}..{max(imd_rank.values())}")
    print("(1 = most deprived in England, 296 = least deprived)\n")

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        gold = con.execute("""
            SELECT borough_code, borough_name, air_score, air_quality_modelled_score,
                   transit_score, sentiment_score, immune_score,
                   green_space_score, green_space_access_score, composite_score
            FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY borough_code ORDER BY ingested_at DESC
                ) AS rn
                FROM gold_scores
            )
            WHERE rn = 1
        """).fetchall()
    finally:
        con.close()
    print(f"Gold: {len(gold)} latest-per-borough rows loaded from {db_path.name}\n")

    organs = [
        ("air_score",                 2),
        ("air_quality_modelled_score", 3),
        ("transit_score",             4),
        ("sentiment_score",           5),
        ("immune_score",              6),
        ("green_space_score",         7),
        ("green_space_access_score",  8),
        ("composite_score",           9),
    ]

    print("=" * 82)
    print(f"{'Organ':<28} {'n':>3} {'slope':>8} {'intercept':>10} {'r':>7} {'R^2':>6}")
    print("=" * 82)

    results = {}
    for organ_name, col_idx in organs:
        pairs = []
        for row in gold:
            code = row[0]
            score = row[col_idx]
            if score is None or code not in imd_rank:
                continue
            pairs.append((imd_rank[code], float(score), code))
        if len(pairs) < 10:
            print(f"{organ_name:<28} {len(pairs):>3}   (too few for regression — check silver freshness)")
            continue
        x = np.array([p[0] for p in pairs], dtype=float)
        y = np.array([p[1] for p in pairs], dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        predicted = slope * x + intercept
        residuals = y - predicted
        r = float(np.corrcoef(x, y)[0, 1])
        ss_res = float(np.sum(residuals ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        results[organ_name] = {"pairs": pairs, "residuals": residuals, "r": r, "r2": r2}
        print(f"{organ_name:<28} {len(pairs):>3} {slope:>8.3f} {intercept:>10.2f} {r:>7.3f} {r2:>6.3f}")

    print()
    print("=" * 82)
    print("TOP OUTLIERS PER ORGAN")
    print("=" * 82)
    for organ_name, data in results.items():
        pairs = data["pairs"]
        residuals = data["residuals"]
        ranked = sorted(zip(pairs, residuals), key=lambda t: t[1])
        most_neg = ranked[:3]
        most_pos = ranked[-3:][::-1]
        strength = "STRONG" if abs(data["r"]) >= 0.5 else "MODERATE" if abs(data["r"]) >= 0.3 else "WEAK"
        print(f"\n{organ_name}  (R² = {data['r2']:.2f}, r = {data['r']:.2f}, signal: {strength})")
        print(f"  Outperforming IMD expectation:")
        for (rank, score, code), resid in most_pos:
            name = borough_names.get(code, code)
            print(f"    +{resid:6.1f}   {name:<24}  (IMD rank {rank}, score {score:.1f})")
        print(f"  Underperforming IMD expectation:")
        for (rank, score, code), resid in most_neg:
            name = borough_names.get(code, code)
            print(f"    {resid:>+6.1f}   {name:<24}  (IMD rank {rank}, score {score:.1f})")

    print()
    print("=" * 82)
    print("DECISION GATE SUMMARY")
    print("=" * 82)
    strong = [o for o, d in results.items() if abs(d["r"]) >= 0.5]
    moderate = [o for o, d in results.items() if 0.3 <= abs(d["r"]) < 0.5]
    weak = [o for o, d in results.items() if abs(d["r"]) < 0.3]
    print(f"Strong (|r|≥0.5):   {len(strong)}  {strong}")
    print(f"Moderate (0.3–0.5): {len(moderate)}  {moderate}")
    print(f"Weak (|r|<0.3):     {len(weak)}  {weak}")
    if len(strong) + len(moderate) >= 2:
        print("\n>>> GO: at least 2 organs have narratable IMD-residual patterns.")
    elif len(strong) + len(moderate) == 1:
        print("\n>>> NARROW: one organ carries the story; consider single-organ equity view rather than full mode.")
    else:
        print("\n>>> SKIP: residuals too noisy across the board; invest elsewhere.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--read", action="store_true", help="Read the read replica instead of write DB")
    args = parser.parse_args()
    db = ROOT / "data" / ("cityscan_read.duckdb" if args.read else "cityscan.duckdb")
    if not db.exists():
        print(f"ERROR: {db} not found")
        raise SystemExit(1)
    raise SystemExit(run(db))

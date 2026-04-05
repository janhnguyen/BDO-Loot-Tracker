import argparse
import csv
from pathlib import Path

from core.arsha_market_source import fetch_arsha_full_catalog, fetch_arsha_hotlist

def main() -> int:
    parser = argparse.ArgumentParser(description="Export Arsha BDO market hot-list into a name,value CSV.")
    parser.add_argument("--region", default="na", help="Market region code (e.g. na, eu, sea, mena).")
    parser.add_argument("--output", default="items/items.arsha.csv", help="Output CSV file path.")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--mode",
        choices=("hotlist", "full"),
        default="full",
        help="hotlist exports trending items only; full crawls categories for a bigger catalog.",
    )
    parser.add_argument("--max-main-category", type=int, default=30, help="Upper main-category bound for full crawl.")
    parser.add_argument("--max-sub-category", type=int, default=60, help="Upper sub-category bound for full crawl.")
    args = parser.parse_args()

    if args.mode == "hotlist":
        values = fetch_arsha_hotlist(region=args.region, timeout_seconds=args.timeout)
    else:
        values = fetch_arsha_full_catalog(
            region=args.region,
            timeout_seconds=args.timeout,
            max_main_category=args.max_main_category,
            max_sub_category=args.max_sub_category,
        )

    if not values:
        print("No market rows were parsed. Check mode/region and endpoint availability.")
        return 1

    output_path = Path(args.output)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["name", "value"])
        for name in sorted(values):
            writer.writerow([name, int(values[name]) if values[name].is_integer() else values[name]])

    print(f"Wrote {len(values)} rows to {output_path} (mode={args.mode})")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

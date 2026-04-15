from __future__ import annotations

import argparse
import json
from pathlib import Path

from luminite.backup import LuminiteBackup


def build_report(backup: LuminiteBackup) -> dict:
    return {
        **backup.to_structured_dict(),
        "reverse_engineering_notes": {
            "song_table_confirmed": {
                "base_offset_hex": "0x00004C0C",
                "stride_hex": "0x2C",
                "record_count": backup.layout.song_count,
                "observation": "The last 10 bytes of each song record behave like references to the preset pool.",
            },
            "setlist_table_confirmed": {
                "base_offset_hex": "0x000060AC",
                "stride_hex": "0x2C",
                "slot_map_base_hex": "0x0000754C",
                "slot_entry_size_bytes": 4,
                "slots_per_setlist": 20,
            },
            "encoder_candidates": {
                "expression_block_base_hex": "0x0000763C",
                "candidate_custom_block_hex": "0x00007E20-0x00007E7F",
                "note": (
                    "EC1/EC2/Push labels are not present as plain ASCII in this backup. "
                    "The strongest candidate is the global Custom block after the Exp records; "
                    "part of the surrounding region appears compacted or obfuscated."
                ),
            },
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a Luminite .bak backup and export a JSON report.")
    parser.add_argument("backup", type=Path, help="Path to the .bak file")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backup_analysis.json"),
        help="Output JSON path",
    )
    args = parser.parse_args()

    backup = LuminiteBackup.from_file(args.backup)
    report = build_report(backup)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Wrote analysis report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

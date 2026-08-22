#!/usr/bin/env python3
"""Inject the real snapshot JSON into the dashboard template -> dashboard.html.

Keeps the dashboard truthful and reproducible: the HTML is a pure view; every
number comes from data/dashboard_snapshot.json, produced by the connectors.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "dashboard" / "template.html"
SNAPSHOT = ROOT / "data" / "dashboard_snapshot.json"
OUT = ROOT / "dashboard" / "dashboard.html"


def main() -> int:
    if not SNAPSHOT.exists():
        print("ERROR: snapshot missing — run build_dashboard_snapshot.py first",
              file=sys.stderr)
        return 1
    tpl = TEMPLATE.read_text()
    data = json.loads(SNAPSHOT.read_text())  # validate it parses
    # Embed as compact JSON; escape </ so it can't break out of the <script>.
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    if "/*__SNAPSHOT__*/" not in tpl:
        print("ERROR: template marker /*__SNAPSHOT__*/ not found", file=sys.stderr)
        return 1
    OUT.write_text(tpl.replace("/*__SNAPSHOT__*/", blob))
    print(f"OK — {OUT}  ({OUT.stat().st_size/1024:.0f} KB, "
          f"{len(data['prices'])} prices, {len(data['signals'])} signals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read-only post-deploy checks. No FTP credentials or writes.

Usage: python3 deploy/scripts/verify_round_two_readiness.py
"""
import argparse
import json
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def get(url):
    try:
        with urlopen(Request(url, headers={"User-Agent": "election-round-readiness/1", "Cache-Control": "no-cache"}), timeout=15) as response:
            return response.status, response.read(2_000_000)
    except HTTPError as exc:
        return exc.code, b""
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("network_error") from exc


def probe(base):
    homepage_status, homepage = get(base + "/")
    html = homepage.decode("utf-8", "replace")
    ui = homepage_status == 200 and 'id="round-first"' in html and 'id="round-second"' in html
    first_status, first_raw = get(base + "/data/version.json")
    first_valid = False
    if first_status == 200:
        try:
            first_valid = isinstance(json.loads(first_raw).get("snapshot_id"), str)
        except (ValueError, AttributeError):
            pass
    second_status, second_raw = get(base + "/data/turnos/2/version.json")
    second_state = "awaiting_official_release"
    if second_status == 200:
        try:
            second = json.loads(second_raw)
            sid = second.get("snapshot_id")
            if not isinstance(sid, str) or not re.fullmatch(r"[a-f0-9]{64}", sid):
                second_state = "invalid_second_round_marker"
            else:
                status, raw = get(base + "/data/turnos/2/releases/" + sid + "/manifest.json")
                manifest = json.loads(raw) if status == 200 else {}
                rows = manifest.get("results")
                if (manifest.get("environment") == "oficial" and isinstance(rows, list)
                        and rows and all(type(row.get("round")) is int and row["round"] == 2 for row in rows)):
                    second_state = "official_second_round_available"
                else:
                    second_state = "invalid_second_round_manifest"
        except (ValueError, AttributeError, TypeError):
            second_state = "invalid_second_round_manifest"
    elif second_status != 404:
        second_state = "unexpected_second_round_http_" + str(second_status)
    return {"frontend_round_switch_live": ui, "first_round_marker_accessible": first_valid,
            "second_round": second_state,
            "ready_waiting_for_official_data": ui and first_valid and second_state == "awaiting_official_release"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="https://afgnet.com.br/eleicoes")
    args = parser.parse_args()
    try:
        result = probe(args.base.rstrip("/"))
    except RuntimeError as exc:
        print(json.dumps({"status": "unknown", "reason": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if (result["ready_waiting_for_official_data"] or
                 (result["frontend_round_switch_live"] and result["first_round_marker_accessible"]
                  and result["second_round"] == "official_second_round_available")) else 1


if __name__ == "__main__":
    sys.exit(main())

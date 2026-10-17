"""Read-only second-round latency audit; never accesses TSE or writes to hosting."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

MARKER = "https://afgnet.com.br/data/turnos/2/version.json"
STATUS = "https://afgnet.com.br/data/turnos/2/status.json"


def epoch(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.timestamp() if dt.tzinfo else None
    except (ValueError, AttributeError, TypeError):
        return None


def seconds_between(later, earlier):
    a, b = epoch(later), epoch(earlier)
    return round(a - b, 3) if a is not None and b is not None else None


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def public_json(url):
    # Fixed HTTPS destinations: no user-provided URLs, redirects, credentials or writes.
    from urllib.request import build_opener, HTTPRedirectHandler
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    request = Request(url, headers={"Accept": "application/json", "Cache-Control": "no-cache",
                                     "User-Agent": "election-round2-readonly-audit/1"}, method="GET")
    try:
        with build_opener(NoRedirect).open(request, timeout=8) as response:
            body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise ValueError("response_too_large")
            return {"http_status": response.status, "payload": json.loads(body),
                    "cache_control": response.headers.get("Cache-Control"),
                    "age": response.headers.get("Age")}
    except (HTTPError, URLError, OSError, ValueError) as error:
        return {"error": type(error).__name__, "http_status": getattr(error, "code", None)}


def report(state, *, marker=None, public_status=None, current_time=None):
    health = read_json(Path(state) / "health.json") or {}
    checkpoint = read_json(Path(state) / "checkpoint.json") or {}
    history = read_json(Path(state) / "metrics-history.json") or []
    now = current_time or datetime.now(timezone.utc).isoformat()
    observed_id = health.get("observed_snapshot_id")
    published_id = checkpoint.get("snapshot_id")
    public_id = (marker or {}).get("payload", {}).get("snapshot_id")
    public_status_id = (public_status or {}).get("payload", {}).get("snapshot_id")
    # Distinguish observation-to-confirmation from TSE's unknown original upload time.
    observed_at = health.get("observed_snapshot_since")
    verified_at = checkpoint.get("verified_at")
    source_at = health.get("last_source_success_at")
    same_snapshot = bool(observed_id and observed_id == published_id)
    return {
        "scope": "read_only_local_observation_and_public_https",
        "sampled_at": now,
        "source_upload_time_known": False,
        "health_status": health.get("status"),
        "election_state": health.get("election_state"),
        "transport": health.get("transport"),
        "observed_snapshot_id": observed_id,
        "checkpoint_snapshot_id": published_id,
        "public_snapshot_id": public_id,
        "public_status_snapshot_id": public_status_id,
        "observed_equals_checkpoint": same_snapshot,
        "checkpoint_equals_public": bool(published_id and published_id == public_id),
        "source_last_success_age_seconds": seconds_between(now, source_at),
        "last_cycle_seconds": health.get("cycle_seconds"),
        "observed_to_verified_seconds": (
            seconds_between(verified_at, observed_at) if same_snapshot else None
        ),
        "https_marker_after_activation_seconds": seconds_between(
            checkpoint.get("https_marker_observed_at"), checkpoint.get("activation_completed_at")
        ),
        "publication_verified_at": verified_at,
        "last_official_change_observed_at": health.get("last_official_change_at"),
        "metrics_history_samples": len(history) if isinstance(history, list) else 0,
        "latest_phase_durations_seconds": {
            key: row["duration_seconds"]
            for key, row in (health.get("metrics") or {}).items()
            if isinstance(row, dict) and isinstance(row.get("duration_seconds"), (int, float))
        },
        "marker_http_status": (marker or {}).get("http_status"),
        "marker_error": (marker or {}).get("error"),
        "public_status_http_status": (public_status or {}).get("http_status"),
        "public_status_error": (public_status or {}).get("error"),
        "marker_cache_control": (marker or {}).get("cache_control"),
        "marker_age_header": (marker or {}).get("age"),
        "caveat": "Observation times are not proof of the instant TSE originally published data; browser detection is not measured here."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path("/var/lib/election-round2"))
    parser.add_argument("--local-only", action="store_true", help="Skip two public HTTPS GETs")
    args = parser.parse_args()
    marker = public_json(MARKER) if not args.local_only else None
    public_status = public_json(STATUS) if not args.local_only else None
    print(json.dumps(report(args.state, marker=marker, public_status=public_status),
                     ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

import requests


DEFAULT_TIMEOUT = (3.05, 10)

USER_AGENT = (
    "election-results-platform/0.1 "
    "(portfolio project; official data source: TSE)"
)


@dataclass(frozen=True, slots=True)
class TseFetchResult:
    url: str
    status_code: int
    etag: str | None
    last_modified: str | None
    sha256: str | None
    payload: dict[str, Any] | None


class TseClient:
    def __init__(
        self,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    ) -> None:
        self.timeout = timeout

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            }
        )

    def fetch_json(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> TseFetchResult:
        headers: dict[str, str] = {}

        if etag:
            headers["If-None-Match"] = etag

        if last_modified:
            headers["If-Modified-Since"] = last_modified

        response = self.session.get(
            url,
            headers=headers,
            timeout=self.timeout,
        )

        response_etag = response.headers.get("ETag")
        response_last_modified = response.headers.get("Last-Modified")

        if response.status_code == 304:
            return TseFetchResult(
                url=url,
                status_code=304,
                etag=response_etag or etag,
                last_modified=response_last_modified or last_modified,
                sha256=None,
                payload=None,
            )

        response.raise_for_status()

        raw_payload = response.content

        payload = json.loads(
            raw_payload.decode("utf-8-sig")
        )

        if not isinstance(payload, dict):
            raise ValueError(
                "Expected the TSE payload root to be a JSON object."
            )

        payload_sha256 = hashlib.sha256(
            raw_payload
        ).hexdigest()

        return TseFetchResult(
            url=url,
            status_code=response.status_code,
            etag=response_etag,
            last_modified=response_last_modified,
            sha256=payload_sha256,
            payload=payload,
        )


def main() -> None:
    url = (
        "https://resultados-sim.tse.jus.br/"
        "simulado/simulado2026/"
        "ele2026/21272/dados/ac/"
        "ac-c0003-e021272-u.json"
    )

    client = TseClient()
    result = client.fetch_json(url)

    payload = result.payload or {}

    summary = {
        "status_code": result.status_code,
        "etag": result.etag,
        "last_modified": result.last_modified,
        "sha256": result.sha256,
        "election": payload.get("ele"),
        "round": payload.get("t"),
        "scope_type": payload.get("tpabr"),
        "scope": payload.get("cdabr"),
        "generated_date": payload.get("dg"),
        "generated_time": payload.get("hg"),
        "idg": payload.get("idg"),
        "offices": [
            {
                "code": office.get("cd"),
                "name": office.get("nmn"),
                "seats": office.get("nv"),
                "groups": len(office.get("agr", [])),
            }
            for office in payload.get("carg", [])
        ],
    }

    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

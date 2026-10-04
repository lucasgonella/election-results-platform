import json

import collector.src.static_site_builder as builder
from collector.src.static_site_builder import (
    StaticExportTarget,
    build_static_site,
    result_relative_path,
)


def payload(
    *,
    scope,
    office,
    name,
    count,
):
    return {
        "schema_version": 1,
        "environment": "simulado2026",

        "election": {
            "code": (
                21270
                if office == 1
                else 21272
            ),
            "round": 1,
        },

        "scope": {
            "code": scope,
            "type": (
                "br"
                if scope == "br"
                else "uf"
            ),
            "uf": (
                None
                if scope == "br"
                else scope.upper()
            ),
        },

        "office": {
            "code": office,
            "name": name,
            "seats": None,
        },

        "snapshot": {
            "tse_idg": 123456,
            "captured_at":
                "2026-10-03T12:00:00-03:00",
        },

        "candidate_count": count,
        "candidates": [],
    }


def test_result_relative_paths():
    assert (
        result_relative_path(
            StaticExportTarget(
                scope_code="br",
                office_code=1,
            )
        ).as_posix()
        == "br/president.json"
    )

    assert (
        result_relative_path(
            StaticExportTarget(
                scope_code="go",
                office_code=7,
            )
        ).as_posix()
        == "go/state-deputy.json"
    )

    assert (
        result_relative_path(
            StaticExportTarget(
                scope_code="df",
                office_code=8,
            )
        ).as_posix()
        == "df/district-deputy.json"
    )


def test_build_static_site(
    tmp_path,
    monkeypatch,
):
    targets = (
        StaticExportTarget(
            scope_code="br",
            office_code=1,
        ),
        StaticExportTarget(
            scope_code="go",
            office_code=7,
        ),
    )

    monkeypatch.setattr(
        builder,
        "list_export_targets",
        lambda **kwargs: targets,
    )

    def fake_load_latest_result(
        *,
        environment,
        scope_code,
        office_code,
        connection=None,
    ):
        if office_code == 1:
            return payload(
                scope=scope_code,
                office=1,
                name="Presidente",
                count=13,
            )

        return payload(
            scope=scope_code,
            office=7,
            name="Deputado Estadual",
            count=943,
        )

    monkeypatch.setattr(
        builder,
        "load_latest_result",
        fake_load_latest_result,
    )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(
            self,
            exc_type,
            exc_value,
            traceback,
        ):
            return False

    connection = FakeConnection()

    monkeypatch.setattr(
        builder,
        "get_connection",
        lambda: connection,
    )

    manifest = build_static_site(
        environment="simulado2026",
        output_dir=tmp_path,
    )

    assert manifest["result_count"] == 2

    assert (
        manifest["candidate_count"]
        == 956
    )

    assert (
        tmp_path
        / "br"
        / "president.json"
    ).is_file()

    assert (
        tmp_path
        / "go"
        / "state-deputy.json"
    ).is_file()

    manifest_path = (
        tmp_path
        / "manifest.json"
    )

    assert manifest_path.is_file()

    version_path = (
        tmp_path
        / "version.json"
    )

    assert version_path.is_file()

    version = json.loads(
        version_path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        version["environment"]
        == "simulado2026"
    )

    assert (
        version["generated_at"]
        == manifest["generated_at"]
    )

    saved = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )

    assert saved["result_count"] == 2

    assert saved["results"][0][
        "path"
    ] == "br/president.json"

    assert saved["results"][1][
        "path"
    ] == "go/state-deputy.json"
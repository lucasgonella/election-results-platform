from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SCRIPT = (
    ROOT
    / "deploy"
    / "scripts"
    / "run-collector.sh"
)


PUBLISH_SCRIPT = (
    ROOT
    / "deploy"
    / "scripts"
    / "publish-results.sh"
)

SERVICE = (
    ROOT
    / "deploy"
    / "systemd"
    / "election-collector.service"
)

TIMER = (
    ROOT
    / "deploy"
    / "systemd"
    / "election-collector.timer"
)

ENV_EXAMPLE = (
    ROOT
    / "deploy"
    / "env"
    / "collector.env.example"
)


def test_deploy_files_exist():
    assert SCRIPT.is_file()
    assert PUBLISH_SCRIPT.is_file()
    assert SERVICE.is_file()
    assert TIMER.is_file()
    assert ENV_EXAMPLE.is_file()


def test_runner_script_uses_operational_runner():
    text = SCRIPT.read_text(
        encoding="utf-8"
    )

    assert (
        "collector.src.collector_runner"
        in text
    )

    assert "--execute" in text
    assert "--batch-size" in text
    assert "--cycles" in text


def test_official_execution_is_explicit():
    script = SCRIPT.read_text(
        encoding="utf-8"
    )

    env = ENV_EXAMPLE.read_text(
        encoding="utf-8"
    )

    assert (
        "COLLECTOR_ALLOW_OFFICIAL=false"
        in env
    )

    assert "--allow-official" in script


def test_systemd_service_uses_environment_file():
    text = SERVICE.read_text(
        encoding="utf-8"
    )

    assert (
        "EnvironmentFile="
        "/etc/election-results-platform/"
        "collector.env"
        in text
    )

    assert (
        "run-collector.sh"
        in text
    )


def test_systemd_timer_invokes_service():
    text = TIMER.read_text(
        encoding="utf-8"
    )

    assert (
        "Unit=election-collector.service"
        in text
    )

    assert "OnActiveSec=2min" in text

    assert (
        "OnUnitInactiveSec=10s"
        in text
    )

    assert (
        "OnUnitActiveSec="
        not in text
    )

    assert "OnBootSec=" not in text

    assert (
        "RandomizedDelaySec=0"
        in text
    )

    assert "AccuracySec=1s" in text

    assert "Persistent=false" in text


def test_secret_is_not_present_in_example():
    text = ENV_EXAMPLE.read_text(
        encoding="utf-8"
    )

    assert (
        "POSTGRES_PASSWORD=change_me"
        in text
    )


def test_static_publish_script():
    text = PUBLISH_SCRIPT.read_text(
        encoding="utf-8"
    )

    assert (
        "collector.src.static_site_builder"
        in text
    )

    assert (
        "PUBLISH_EXPECTED_TARGETS"
        in text
    )

    assert (
        "manifest.json"
        in text
    )

    assert (
        "REMOTE BUNDLE: OK"
        in text
    )

    assert (
        "STATIC PUBLISH: OK"
        in text
    )


def test_static_publish_environment_example():
    text = ENV_EXAMPLE.read_text(
        encoding="utf-8"
    )

    assert (
        "PUBLISH_EXPECTED_TARGETS=85"
        in text
    )

    assert (
        "PUBLISH_REMOTE_HOST="
        in text
    )

    assert (
        "PUBLISH_REMOTE_DIR="
        in text
    )



def test_conditional_static_publish():
    text = SCRIPT.read_text(
        encoding="utf-8"
    )

    assert (
        "PUBLISH_AFTER_COLLECT"
        in text
    )

    assert (
        "state_updates_committed"
        in text
    )

    assert (
        'after["pending_items"] == 0'
        in text
    )

    assert (
        'after["error_items"] == 0'
        in text
    )

    assert (
        'after["health"] == "ok"'
        in text
    )

    assert (
        "publish.pending"
        in text
    )

    assert (
        "publish-results.sh"
        in text
    )


    assert (
        '${PUBLISH_STATE_DIR}/runtime/publish.pending'
        in text
    )

    assert (
        'dirname "${PUBLISH_PENDING_FILE}"'
        in text
    )


def test_auto_publish_is_disabled_by_default():
    text = ENV_EXAMPLE.read_text(
        encoding="utf-8"
    )

    assert (
        "PUBLISH_AFTER_COLLECT=false"
        in text
    )


    assert (
        "PUBLISH_PENDING_FILE="
        "/var/lib/election-results-platform/"
        "runtime/publish.pending"
        in text
    )

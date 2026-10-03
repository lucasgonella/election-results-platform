from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SCRIPT = (
    ROOT
    / "deploy"
    / "scripts"
    / "run-collector.sh"
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
        "OnUnitInactiveSec=2min"
        in text
    )

    assert (
        "OnUnitActiveSec="
        not in text
    )

    assert "OnBootSec=" not in text

    assert (
        "RandomizedDelaySec=15s"
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

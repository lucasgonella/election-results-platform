from pathlib import Path
import subprocess


ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

SCRIPT = (
    ROOT
    / "deploy"
    / "scripts"
    / "publish-live-results.sh"
)


def test_live_publish_script_has_valid_bash_syntax():
    subprocess.run(
        [
            "bash",
            "-n",
            str(SCRIPT),
        ],
        check=True,
    )


def test_live_publish_retries_transient_ssh_failures():
    text = SCRIPT.read_text(
        encoding="utf-8"
    )

    assert (
        'LIVE_PUBLISH_SSH_RETRIES'
        in text
    )
    assert (
        'retry_operation'
        in text
    )
    assert (
        'ConnectTimeout=5'
        in text
    )


def test_remote_activation_is_retry_safe():
    text = SCRIPT.read_text(
        encoding="utf-8"
    )

    assert (
        'cp \\'
        in text
    )
    assert (
        'mv \\'
        not in text
    )
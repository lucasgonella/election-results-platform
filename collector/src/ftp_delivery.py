"""Signed, immutable deliveries. FTP carries bytes; HTTPS carries control only."""
from __future__ import annotations

import argparse
import ftplib
import hashlib
import hmac
import io
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import time
import urllib.request
import urllib.parse

from .ftp_safety import assert_transport_isolated, validate_inbox


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def key_from_file(path):
    key = bytes.fromhex(Path(path).read_text().strip())
    if len(key) != 32:
        raise ValueError("invalid_key")
    return key


def freeze(stage: Path, spool: Path, key: bytes, baseline: str | None):
    files = {}
    for path in sorted(stage.rglob("*.json")):
        if path.is_symlink():
            raise ValueError("symlink")
        relative = path.relative_to(stage).as_posix()
        if relative not in {"manifest.json", "version.json", "alerts.json"} and not (
            len(PurePosixPath(relative).parts) == 2 and relative.endswith(".json")
        ):
            raise ValueError("invalid_path")
        raw = path.read_bytes()
        files[relative] = {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    if not {"manifest.json", "version.json", "alerts.json"} <= files.keys():
        raise ValueError("missing_metadata")
    descriptor = canonical({"schema_version": 1, "base_snapshot_id": baseline, "files": files})
    delivery_id = hashlib.sha256(descriptor).hexdigest()
    destination = spool / delivery_id
    destination.mkdir(parents=True, exist_ok=True)
    for name in files:
        target = destination / "files" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = (stage / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != files[name]["sha256"]:
            raise ValueError("stage_changed")
        if target.exists() and target.read_bytes() != raw:
            raise ValueError("delivery_changed")
        target.write_bytes(raw)
    (destination / "delivery.json").write_bytes(descriptor)
    (destination / "delivery.sig").write_text(hmac.new(key, descriptor, "sha256").hexdigest())
    (destination / "READY").write_text(delivery_id)
    return destination


def upload(delivery: Path, remote_root: str, host: str, user: str, password: str,
           ftp_factory=ftplib.FTP):
    """Write only a private inbox; READY last. Retrieve every file to verify bytes."""
    validate_inbox(remote_root)
    if len(delivery.name) != 64 or any(c not in "0123456789abcdef" for c in delivery.name):
        raise ValueError("invalid_delivery_id")
    ftp = ftp_factory()
    try:
        ftp.connect(host, 21, timeout=30)
        ftp.login(user, password)
        assert_transport_isolated(ftp)
        ftp.set_pasv(True)
        root = remote_root.rstrip("/") + "/" + delivery.name
        entries = [p for p in sorted(delivery.rglob("*")) if p.is_file() and p.name != "READY"]
        entries.append(delivery / "READY")
        for path in entries:
            if path.is_symlink():
                raise ValueError("symlink")
            remote = root + "/" + path.relative_to(delivery).as_posix()
            parent = PurePosixPath(remote).parent
            current = "/" if str(parent).startswith("/") else ""
            for part in parent.parts:
                if part == "/":
                    continue
                current = current.rstrip("/") + "/" + part if current else part
                try:
                    ftp.mkd(current)
                except ftplib.error_perm:
                    # Verify it really exists; don't mask permission errors.
                    old = ftp.pwd()
                    ftp.cwd(current)
                    ftp.cwd(old)
            raw = path.read_bytes()
            temporary = remote + ".part"
            ftp.storbinary("STOR " + temporary, io.BytesIO(raw))
            check = bytearray()
            ftp.retrbinary("RETR " + temporary, check.extend)
            if bytes(check) != raw:
                raise ValueError("ftp_integrity_error")
            ftp.rename(temporary, remote)
    finally:
        ftp.close()


class Control:
    def __init__(self, url, key):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("https_required")
        self.url, self.key = url, key

    def request(self, action, delivery_id):
        raw = canonical({"action": action, "delivery_id": delivery_id})
        timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
        signature = hmac.new(self.key, timestamp.encode() + b"\n" + nonce.encode() + b"\n" + raw, "sha256").hexdigest()
        request = urllib.request.Request(self.url, raw, {
            "Content-Type": "application/json", "X-Timestamp": timestamp,
            "X-Nonce": nonce, "X-Signature": signature,
        })
        # Redirects must not carry authentication to a different endpoint.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        with urllib.request.build_opener(NoRedirect).open(request, timeout=60) as response:
            return json.load(response)


def publish(delivery, control, transfer):
    """Reconcile first and after an ambiguous activation; never rebuild on retry."""
    receipt = control.request("status", delivery.name)
    if receipt.get("status") != "published":
        transfer()
        try:
            receipt = control.request("activate", delivery.name)
        except (OSError, TimeoutError):
            receipt = control.request("status", delivery.name)
    if (receipt.get("status") != "published" or receipt.get("delivery_id") != delivery.name
            or receipt.get("snapshot_id") != delivery.name):
        raise RuntimeError("publication_not_confirmed")
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("delivery", type=Path)
    args = parser.parse_args()
    if os.environ.get('LOCAWEB_FTP_ISOLATION_APPROVED') != 'true' or os.environ.get('LOCAWEB_FTP_PORT','21') != '21':
        raise ValueError('unapproved_ftp_configuration')
    key = key_from_file(os.environ["ELECTION_HMAC_KEY_FILE"])
    receipt = publish(args.delivery, Control(os.environ["ELECTION_FTP_CONTROL_URL"], key), lambda: upload(
        args.delivery, os.environ["LOCAWEB_FTP_ELECTION_INBOX_DIR"], os.environ["LOCAWEB_FTP_HOST"],
        os.environ["LOCAWEB_FTP_USER"], os.environ["LOCAWEB_FTP_PASSWORD"]))
    print(json.dumps(receipt))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({'status':'failed','error_type':type(error).__name__}))
        raise SystemExit(1)

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import platform
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from tme3bot.api.backend import create_backend_app
from tme3bot.infrastructure.device_auth import DeviceAuthService
from tools.trusted_device import command_init, command_prepare
from tools.trusted_device_browser import open_trusted_context
from tools.trusted_device_store import LinuxPassphraseProtector


ROOT = Path(__file__).resolve().parents[1]
CHROME_CANDIDATES = [
    Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Microsoft/Edge/Application/msedge.exe",
]
CHROME = next((path for path in CHROME_CANDIDATES if path.is_file()), None)
CERTUTIL = Path(os.environ.get("WINDIR", "C:/Windows")) / "System32/certutil.exe"
RUN_E2E = os.environ.get("TME3_RUN_TRUSTED_DEVICE_BROWSER_E2E") == "1"


def make_test_certificates(folder: Path) -> tuple[Path, Path, Path, Path, str]:
    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "tme3 local e2e ephemeral CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    server_key = ec.generate_private_key(ec.SECP256R1())
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(minutes=30))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    ca_der = folder / "local-test-ca.cer"
    ca_pem = folder / "local-test-ca.pem"
    server_cert_path = folder / "server-cert.pem"
    server_key_path = folder / "server-key.pem"
    ca_der.write_bytes(ca_cert.public_bytes(serialization.Encoding.DER))
    ca_pem.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    server_cert_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    server_key_path.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    thumbprint = hashlib.sha1(ca_cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    return ca_der, ca_pem, server_cert_path, server_key_path, thumbprint


@unittest.skipUnless(
    os.name == "nt" and RUN_E2E and CHROME is not None and CERTUTIL.is_file(),
    "Set TME3_RUN_TRUSTED_DEVICE_BROWSER_E2E=1; requires Windows, Chrome/Edge and certutil",
)
class TrustedDevicePlaywrightHttpsE2ETests(unittest.TestCase):
    def test_helper_state_imports_in_chrome_and_revoke_invalidates_it(self):
        from tests.test_backend_api import BackendApiTests

        fixture = BackendApiTests()
        fixture.setUp()
        temp = tempfile.TemporaryDirectory(prefix="tme3-device-e2e-")
        folder = Path(temp.name)
        ca_thumbprint = None
        server = None
        server_thread = None
        added_ca = False
        try:
            local_app_data = folder / "local-app-data"
            local_app_data.mkdir()
            port_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            port_socket.bind(("127.0.0.1", 0))
            port = port_socket.getsockname()[1]
            port_socket.close()
            origin = f"https://127.0.0.1:{port}"

            ca_der, ca_pem, cert_path, key_path, ca_thumbprint = make_test_certificates(folder)
            imported = subprocess.run(
                [str(CERTUTIL), "-user", "-addstore", "Root", str(ca_der)],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(imported.returncode, 0, "Could not trust the temporary localhost CA in CurrentUser Root")
            added_ca = True

            fixture.context.config.web_cookie_secure = True
            fixture.context.config.web_public_origin = origin
            fixture.context.device_auth = DeviceAuthService(fixture.auth_repository, fixture.auth, origin)
            app = create_backend_app(fixture.context)
            server = uvicorn.Server(
                uvicorn.Config(
                    app,
                    host="127.0.0.1",
                    port=port,
                    ssl_certfile=str(cert_path),
                    ssl_keyfile=str(key_path),
                    log_level="critical",
                    access_log=False,
                )
            )
            server_thread = threading.Thread(target=server.run, daemon=True)
            server_thread.start()
            deadline = time.monotonic() + 10
            while not server.started and server_thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(server.started, "Local HTTPS API fixture did not start")

            helper_env = os.environ.copy()
            helper_env["LOCALAPPDATA"] = str(local_app_data)
            helper_env["SSL_CERT_FILE"] = str(ca_pem)
            init = subprocess.run(
                [sys.executable, "-m", "tools.trusted_device", "init", "--origin", origin, "--name", "Local E2E"],
                cwd=ROOT,
                env=helper_env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(init.returncode, 0, "Local helper init failed: " + init.stderr)
            enrollment = json.loads(init.stdout)
            enrollment_doc = json.loads(Path(enrollment["enrollment_file"]).read_text(encoding="utf-8"))

            browser_client = TestClient(app, base_url=origin)
            pair = fixture.auth._new_web_session(42)
            csrf = "local-device-enrollment-csrf"
            browser_client.cookies.set("tme3_access", pair.access_token)
            browser_client.cookies.set("tme3_refresh", pair.refresh_token)
            browser_client.cookies.set("tme3_csrf", csrf)
            registered = browser_client.post(
                "/api/v1/auth/devices",
                headers={"Origin": origin, "X-CSRF-Token": csrf},
                json=enrollment_doc,
            )
            self.assertEqual(registered.status_code, 201, registered.text)
            device_id = enrollment_doc["device_id"]

            def prepare_state() -> Path:
                prepared = subprocess.run(
                    [sys.executable, "-m", "tools.trusted_device", "prepare-browser", "--origin", origin],
                    cwd=ROOT,
                    env=helper_env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(prepared.returncode, 0, "Local helper login failed: " + prepared.stderr)
                return Path(json.loads(prepared.stdout)["browser_state_file"])

            first_state = prepare_state()
            local_status = subprocess.run(
                [sys.executable, "-m", "tools.trusted_device", "status", "--origin", origin],
                cwd=ROOT,
                env=helper_env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(local_status.returncode, 0, "Credential status after first helper call failed: " + local_status.stderr)
            second_state = prepare_state()
            runner = [
                sys.executable,
                "-m",
                "tools.trusted_device_browser",
                "--origin",
                origin,
                "--browser-executable",
                str(CHROME),
            ]
            first = subprocess.run(
                runner + ["--state-file", str(first_state)],
                cwd=ROOT,
                env=helper_env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(first.returncode, 0, "Chrome failed to import the Playwright state: " + first.stderr)
            first_result = json.loads(first.stdout)
            self.assertEqual(first_result["status"], 200)
            self.assertTrue(first_result["authenticated"])
            self.assertEqual(first_result["actor_id"], 42)
            self.assertFalse(first_state.exists(), "Runner must remove the imported state file")

            revoked = browser_client.delete(
                f"/api/v1/auth/devices/{device_id}",
                headers={"Origin": origin, "X-CSRF-Token": csrf},
            )
            self.assertEqual(revoked.status_code, 200, revoked.text)
            second = subprocess.run(
                runner + ["--state-file", str(second_state)],
                cwd=ROOT,
                env=helper_env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(second.returncode, 1, "A revoked device session must not authenticate")
            self.assertEqual(json.loads(second.stdout)["status"], 401)
            self.assertFalse(second_state.exists(), "Runner must remove state after rejected import too")
        finally:
            if server is not None:
                server.should_exit = True
            if server_thread is not None:
                server_thread.join(timeout=5)
            if added_ca and ca_thumbprint:
                subprocess.run(
                    [str(CERTUTIL), "-user", "-delstore", "Root", ca_thumbprint],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
            fixture.tearDown()
            temp.cleanup()


@unittest.skipUnless(
    platform.system() == "Linux" and RUN_E2E,
    "Set TME3_RUN_TRUSTED_DEVICE_BROWSER_E2E=1; requires Linux and Playwright Chromium",
)
class TrustedDeviceLinuxPlaywrightHttpsE2ETests(unittest.TestCase):
    def test_linux_enrollment_v1_and_playwright_session_revocation(self):
        from tests.test_backend_api import BackendApiTests
        from playwright.sync_api import sync_playwright

        fixture = BackendApiTests()
        fixture.setUp()
        temp = tempfile.TemporaryDirectory(prefix="tme3-device-linux-e2e-")
        folder = Path(temp.name)
        server = None
        server_thread = None
        try:
            config_home = folder / "config"
            config_home.mkdir()
            port_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            port_socket.bind(("127.0.0.1", 0))
            port = port_socket.getsockname()[1]
            port_socket.close()
            origin = f"https://127.0.0.1:{port}"

            _, ca_pem, cert_path, key_path, _ = make_test_certificates(folder)
            fixture.context.config.web_cookie_secure = True
            fixture.context.config.web_public_origin = origin
            fixture.context.device_auth = DeviceAuthService(fixture.auth_repository, fixture.auth, origin)
            app = create_backend_app(fixture.context)
            server = uvicorn.Server(
                uvicorn.Config(
                    app,
                    host="127.0.0.1",
                    port=port,
                    ssl_certfile=str(cert_path),
                    ssl_keyfile=str(key_path),
                    log_level="critical",
                    access_log=False,
                )
            )
            server_thread = threading.Thread(target=server.run, daemon=True)
            server_thread.start()
            deadline = time.monotonic() + 10
            while not server.started and server_thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(server.started, "Local HTTPS API fixture did not start")

            helper_env = {"XDG_CONFIG_HOME": str(config_home), "SSL_CERT_FILE": str(ca_pem)}
            passphrase = b"trusted-device e2e passphrase"
            with patch.dict(os.environ, helper_env):
                with patch.object(LinuxPassphraseProtector, "_read_passphrase", return_value=passphrase):
                    initialized = command_init(
                        SimpleNamespace(origin=origin, name="Linux Playwright E2E")
                    )
                enrollment_path = Path(initialized["enrollment_file"])
                enrollment = json.loads(enrollment_path.read_text(encoding="utf-8"))
                self.assertEqual(enrollment["version"], 1)
                self.assertEqual(enrollment["origin"], origin)
                self.assertNotIn("private_key_scrypt", enrollment)

                browser_client = TestClient(app, base_url=origin)
                pair = fixture.auth._new_web_session(42)
                csrf = "local-linux-device-enrollment-csrf"
                browser_client.cookies.set("tme3_access", pair.access_token)
                browser_client.cookies.set("tme3_refresh", pair.refresh_token)
                browser_client.cookies.set("tme3_csrf", csrf)
                registered = browser_client.post(
                    "/api/v1/auth/devices",
                    headers={"Origin": origin, "X-CSRF-Token": csrf},
                    json=enrollment,
                )
                self.assertEqual(registered.status_code, 201, registered.text)
                device_id = enrollment["device_id"]

                def prepare_state() -> Path:
                    with patch.object(
                        LinuxPassphraseProtector,
                        "_read_passphrase",
                        return_value=passphrase,
                    ):
                        result = command_prepare(SimpleNamespace(origin=origin))
                    return Path(result["browser_state_file"])

                first_state = prepare_state()
                with sync_playwright() as playwright:
                    chromium = Path(playwright.chromium.executable_path)
                self.assertTrue(chromium.is_file(), "Playwright Chromium is not installed")
                browser_wrapper = folder / "chromium-test-wrapper"
                browser_wrapper.write_text(
                    "#!/bin/sh\n"
                    f"exec {shlex.quote(str(chromium))} --ignore-certificate-errors \"$@\"\n",
                    encoding="utf-8",
                )
                browser_wrapper.chmod(0o700)

                with open_trusted_context(
                    origin=origin,
                    storage_state=first_state,
                    headless=True,
                    executable_path=str(browser_wrapper),
                ) as context:
                    page = context.new_page()
                    response = page.goto(
                        f"{origin}/api/v1/auth/browser/session",
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                    self.assertEqual(response.status if response else None, 200)
                    payload = response.json()
                    self.assertTrue(payload["authenticated"])
                    self.assertEqual(payload["actor"]["telegram_user_id"], 42)
                self.assertFalse(first_state.exists(), "Imported browser state must be consumed")

                second_state = prepare_state()
                revoked = browser_client.delete(
                    f"/api/v1/auth/devices/{device_id}",
                    headers={"Origin": origin, "X-CSRF-Token": csrf},
                )
                self.assertEqual(revoked.status_code, 200, revoked.text)
                with open_trusted_context(
                    origin=origin,
                    storage_state=second_state,
                    headless=True,
                    executable_path=str(browser_wrapper),
                ) as context:
                    page = context.new_page()
                    response = page.goto(
                        f"{origin}/api/v1/auth/browser/session",
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                    self.assertEqual(response.status if response else None, 401)
                self.assertFalse(second_state.exists(), "Rejected browser state must also be consumed")
        finally:
            if server is not None:
                server.should_exit = True
            if server_thread is not None:
                server_thread.join(timeout=5)
            fixture.tearDown()
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()

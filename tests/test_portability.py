"""Offline checks for configuration and entry points on Linux, macOS, and Windows."""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from alpaca_cli import cli, config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name) / "profile space é"
        self.path = self.directory / "config.json"
        for target, value in (("CONFIG_DIR", self.directory), ("CONFIG_PATH", self.path)):
            mock = patch.object(config, target, value)
            mock.start()
            self.addCleanup(mock.stop)
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        network = patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden"))
        network.start()
        self.addCleanup(network.stop)

    def test_setup_update_and_resolve_unicode_profile(self):
        runner = CliRunner()
        with patch.object(cli, "CONFIG_PATH", self.path):
            for key in ("test-key", "updated-key"):
                result = runner.invoke(cli.main, ["setup", "--profile", "épargne"],
                                       input=f"{key}\ntest-secret\nn\n")
                self.assertEqual(result.exit_code, 0, result.output)
                creds = config.resolve_credentials("épargne")
                self.assertEqual(creds.api_key, key)
                self.assertTrue(creds.paper)
        result = runner.invoke(cli.main, ["profile", "use", "épargne"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(config.resolve_credentials().source, "profile:épargne")
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), config.load_config())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_reads_utf8_from_other_platform(self):
        self.directory.mkdir()
        self.path.write_bytes('{"default_profile":"épargne","profiles":{}}\r\n'.encode("utf-8"))
        self.assertEqual(config.load_config()["default_profile"], "épargne")

    def test_invalid_encoding_reports_config_error(self):
        self.directory.mkdir()
        self.path.write_bytes(b'\xff')
        with self.assertRaises(config.ConfigError):
            config.load_config()

    @unittest.skipUnless(os.name == "nt", "Windows uses inherited ACLs")
    def test_windows_does_not_apply_posix_modes(self):
        with patch.object(config.os, "chmod", side_effect=AssertionError("POSIX-only operation")):
            config.save_config({"profiles": {}})
            config.save_config({"profiles": {}, "default_profile": "new"})
        self.assertEqual(config.load_config()["default_profile"], "new")


class EntryPointTests(unittest.TestCase):
    def test_module_and_installed_command_match(self):
        executable = Path(sys.executable).parent / ("alpaca.exe" if os.name == "nt" else "alpaca")
        command = str(executable) if executable.exists() else shutil.which("alpaca")
        self.assertIsNotNone(command, "Install the project before running tests")
        for args in (["--help"], ["--version"]):
            with self.subTest(args=args):
                module = subprocess.run([sys.executable, "-m", "alpaca_cli", *args],
                                        capture_output=True, check=True)
                installed = subprocess.run([command, *args], capture_output=True, check=True)
                # Help names the entry point used to invoke it.
                self.assertEqual(module.stdout.replace(b"python -m alpaca_cli", b"alpaca"),
                                 installed.stdout)

    def test_config_override_with_spaces_and_unicode(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "profile space é"
            env = dict(os.environ, ALPACA_CONFIG_DIR=str(directory))
            result = subprocess.run(
                [sys.executable, "-c",
                 "from alpaca_cli.config import CONFIG_DIR; print(str(CONFIG_DIR).encode('utf-8').hex())"],
                env=env, capture_output=True, check=True,
            )
            self.assertEqual(bytes.fromhex(result.stdout.decode().strip()).decode("utf-8"), str(directory))


if __name__ == "__main__":
    unittest.main()

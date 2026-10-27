"""Native runtime archive integrity and safe atomic installation."""

import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audio_catalog import RUNTIME_NAME
from prepare_audio_runtime import install_runtime


def archive(root, *, malicious=None):
    folder = root / "packages"
    folder.mkdir(exist_ok=True)
    path = folder / RUNTIME_NAME
    with tarfile.open(path, "w:gz") as tar:
        member = tarfile.TarInfo("bin/audiocpp_server")
        data = b"native-test"
        member.size = len(data)
        member.mode = 0o755
        tar.addfile(member, io.BytesIO(data))
        if malicious:
            name, link = malicious
            member = tarfile.TarInfo(name)
            if link:
                member.type = tarfile.SYMTYPE
                member.linkname = link
                tar.addfile(member)
            else:
                member.size = 1
                tar.addfile(member, io.BytesIO(b"x"))
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RuntimePrepareTests(unittest.TestCase):
    def test_install_and_repair_missing_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            digest = archive(root)
            with patch("prepare_audio_runtime.RUNTIME_SHA256", digest):
                install_runtime(root)
                marker = json.loads((root / "runtime/.studio-runtime.json").read_text())
                exe = root / "runtime" / marker["binary"]
                self.assertTrue(exe.is_file())
                exe.unlink()
                install_runtime(root)
                self.assertTrue(exe.is_file())
                self.assertFalse((root / "runtime.old").exists())

    def test_checksum_mismatch_never_extracts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive(root)
            with self.assertRaisesRegex(IOError, "SHA256 mismatch"):
                install_runtime(root)
            self.assertFalse((root / "runtime").exists())

    def test_traversal_and_links_are_rejected_without_replacing_old_runtime(self):
        for malicious in [("../../escaped", None), ("link", "/outside")]:
            with (
                self.subTest(malicious=malicious),
                tempfile.TemporaryDirectory() as folder,
            ):
                root = Path(folder)
                old = root / "runtime"
                old.mkdir()
                (old / "preserved").write_text("old runtime")
                digest = archive(root, malicious=malicious)
                with patch("prepare_audio_runtime.RUNTIME_SHA256", digest):
                    with self.assertRaises(ValueError):
                        install_runtime(root)
                self.assertTrue((old / "preserved").is_file())
                self.assertFalse((root / "runtime.new").exists())


class DownloadCredentialTests(unittest.TestCase):
    def test_hf_credentials_do_not_reach_github_assets(self):
        import os
        from model_download import download_token, SafeRedirect
        from urllib.request import Request

        with patch.dict(
            os.environ,
            {"HF_TOKEN": "test-secret", "HF_ENDPOINT": "https://hf-mirror.com"},
        ):
            self.assertIsNone(
                download_token("https://github.com/project/releases/runtime.tar.gz")
            )
            self.assertEqual(
                download_token("https://hf-mirror.com/org/model/file.gguf"),
                "test-secret",
            )
            request = Request(
                "https://hf-mirror.com/org/model/file.gguf",
                headers={"Authorization": "Bearer test-secret"},
            )
            redirected = SafeRedirect().redirect_request(
                request, None, 302, "Found", {}, "https://cdn.example/model.gguf"
            )
            self.assertIsNone(redirected.get_header("Authorization"))

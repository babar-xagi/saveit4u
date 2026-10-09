"""Developer build: standalone desktop app + verified, self-contained Setup EXE."""

import hashlib
import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "companion"))
from saveit4u import __version__
from saveit4u.engine import executable, javascript_runtime
from saveit4u.identity import extension_id
from saveit4u.installation import sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    distribution = args.output_dir.resolve()
    if os.name != "nt":
        raise SystemExit("Build Windows releases on Windows x64.")
    runtime = ROOT / ".tools/runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    name, node = javascript_runtime()
    if name != "node":
        node = shutil.which("node")
    if not node:
        raise SystemExit("Install a supported Node runtime on the build machine.")
    if not executable("ffmpeg") or not executable("ffprobe"):
        raise SystemExit("Run scripts/install_ffmpeg.py on the build machine first.")
    shutil.copy2(node, runtime / "node.exe")
    version = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    with urllib.request.urlopen(f"https://raw.githubusercontent.com/nodejs/node/{version}/LICENSE", timeout=30) as response:
        (runtime / "NODE-LICENSE.txt").write_bytes(response.read(512000))
    icon_data = (ROOT / "extension/icons/128.png").read_bytes()
    (ROOT / ".tools/app.ico").write_bytes(struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 128, 128, 0, 0, 1, 32, len(icon_data), 22) + icon_data)
    manifest_data = json.loads((ROOT / "extension/manifest.json").read_text(encoding="utf-8"))
    if extension_id(manifest_data["key"]) != extension_id():
        raise SystemExit("The installer and extension release identities do not match.")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(distribution),
                    "--workpath", str(ROOT / "build/freeze"), str(ROOT / "packaging/windows.spec")], check=True, cwd=ROOT)
    application = distribution / "SaveIt4U"
    shutil.copytree(ROOT / "extension", application / "extension", dirs_exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", application / "LICENSE")
    files = {file.relative_to(application).as_posix(): sha256(file) for file in sorted(application.rglob("*")) if file.is_file() and file.name != "release-manifest.json"}
    manifest = {"version": __version__, "extension_id": extension_id(), "files": files}
    (application / "release-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    installer = ROOT / "build/installer"
    installer.mkdir(parents=True, exist_ok=True)
    archive = installer / "payload.zip"
    print("Compressing verified application payload…", flush=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for file in sorted(application.rglob("*")):
            if file.is_file(): bundle.write(file, file.relative_to(application))
    (installer / "payload.sha256").write_text(sha256(archive), encoding="ascii")
    setup_name = f"SaveIt4U-Setup-{__version__}"
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed", "--name", setup_name,
                    "--paths", str(ROOT / "companion"), "--distpath", str(distribution), "--workpath", str(ROOT / "build/setup"),
                    "--specpath", str(ROOT / "build"), "--icon", str(ROOT / ".tools/app.ico"),
                    "--add-data", str(archive) + ";.", "--add-data", str(installer / "payload.sha256") + ";.",
                    str(ROOT / "scripts/installer_entry.py")], check=True, cwd=ROOT)
    subprocess.run([sys.executable, str(ROOT / "scripts/package_extension.py")], check=True)
    print(f"Ready: {distribution / (setup_name + '.exe')}", flush=True)


if __name__ == "__main__":
    main()

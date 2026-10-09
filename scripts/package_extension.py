"""Create an installable unpacked-extension ZIP without local companion data."""

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
output = ROOT / "dist" / f"saveit4u-extension-{manifest['version']}.zip"
output.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for file in sorted((ROOT / "extension").rglob("*")):
        if file.is_file():
            archive.write(file, file.relative_to(ROOT / "extension"))
print(output)

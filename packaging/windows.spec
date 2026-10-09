# One shared runtime directory, with a GUI EXE and console native/worker EXE.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
yd_datas, yd_bins, yd_hidden = collect_all('yt_dlp')
ejs_datas, ejs_bins, ejs_hidden = collect_all('yt_dlp_ejs')
datas = yd_datas + ejs_datas + copy_metadata('yt-dlp') + copy_metadata('yt-dlp-ejs')
datas += [(str(root / '.tools/ffmpeg'), 'tools/ffmpeg'), (str(root / '.tools/runtime/node.exe'), 'tools/node'), (str(root / '.tools/runtime/NODE-LICENSE.txt'), 'tools/node')]
a = Analysis([str(root / 'scripts/app_entry.py')], pathex=[str(root / 'companion')], binaries=yd_bins + ejs_bins, datas=datas,
             hiddenimports=yd_hidden + ejs_hidden + collect_submodules('saveit4u'), hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
native = EXE(pyz, a.scripts, [], exclude_binaries=True, name='saveit4u-host', console=True, icon=str(root / '.tools/app.ico'))
desktop = EXE(pyz, a.scripts, [], exclude_binaries=True, name='SaveIt4U', console=False, icon=str(root / '.tools/app.ico'))
coll = COLLECT(native, desktop, a.binaries, a.datas, strip=False, upx=False, name='SaveIt4U')

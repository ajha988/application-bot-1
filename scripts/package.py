"""Package source + built dashboard; never include secrets or runtime data."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root=Path(__file__).resolve().parents[1]
output=root.parent/'application-bot-mvp.zip'
allowed={'backend','frontend','scripts','deploy'}
excluded={'node_modules','__pycache__','.pytest_cache'}
with ZipFile(output,'w',ZIP_DEFLATED) as z:
    for path in root.rglob('*'):
        if not path.is_file(): continue
        relative=path.relative_to(root)
        if any(part in excluded for part in relative.parts): continue
        if len(relative.parts)>1 and relative.parts[0] not in allowed: continue
        if len(relative.parts)==1 and relative.name not in {'.env.example','.gitignore','README.md','sample-profile.json','sample-jobs.json','VERIFICATION.md','start.ps1','Dockerfile','.dockerignore','compose.yaml','render.yaml','DEPLOYMENT.md','selected-live-job.json'}: continue
        z.write(path,Path(root.name)/relative)
with ZipFile(output) as z:
    assert z.testzip() is None
    assert not any('/data/' in x or '/.env'==x[-5:] or '/node_modules/' in x for x in z.namelist())
print(f'{output}: {output.stat().st_size:,} bytes')

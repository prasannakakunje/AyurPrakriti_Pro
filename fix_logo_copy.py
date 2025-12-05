# fix_logo_copy.py
from pathlib import Path
import shutil

ROOT = Path('.').resolve()
py_files = list(ROOT.rglob('*.py'))

def backup(p):
    b = p.with_suffix(p.suffix + '.bak')
    shutil.copy(p, b)

for p in py_files:
    s = p.read_text(encoding='utf-8')
        backup(p)
        lines = s.splitlines()
        new_lines = []
        skip_next = False
        for i, L in enumerate(lines):
                # skip this line (usually shutil.copy(...))
                continue
                # skip that whole if block by not adding this line; try to skip small indented block
                # we will skip next few indented lines if they belong to the if
                continue
            new_lines.append(L)
        p.write_text("\n".join(new_lines), encoding='utf-8')
        print("Fixed:", p)
print("Done. Backups (*.bak) created for changed files.")
from __future__ import annotations

import json
import sys
from pathlib import Path

from lodex_core.management import worktrees
from lodex_core.management.project_config import CONFIG


def recipe(repo: Path, *, secret: bool = True) -> None:
    (repo / "prepare.py").write_text(
        "import json, os\nfrom pathlib import Path\n"
        "print(os.getenv('TOKEN','ordinary'))\n"
        "Path(os.environ['LODEX_RESULT_FILE']).write_text(json.dumps({'resources':[{"
        "'name':'db','kind':'fixture','id':os.environ['LODEX_TASKENV_ID'],"
        "'scope':'exclusive','state':'present'}], 'urls':[]}))\n"
    )
    worktrees.git(repo, "add", "prepare.py")
    worktrees.git(repo, "commit", "-qm", "fixture prepare")
    (repo / CONFIG).write_text(
        'schema_version=1\n[env]\nDB="app_${LODEX_TASKENV_ID}"\n'
        + ('[secrets]\nTOKEN="secret:fixture"\n' if secret else "")
        + "[commands.prepare]\n"
        + f'argv=[{json.dumps(sys.executable)},"prepare.py"]\nscripts=["prepare.py"]\n'
        + "[commands.verify]\n"
        + f'argv=[{json.dumps(sys.executable)},"-c","raise SystemExit(3)"]\n'
        + "[commands.cleanup]\n"
        + f'argv=[{json.dumps(sys.executable)},"-c","print(123)"]\n'
    )

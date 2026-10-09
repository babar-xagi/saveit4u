"""Source-checkout native launcher (also works after an editable install)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion"))
from saveit4u.host import main

raise SystemExit(main())

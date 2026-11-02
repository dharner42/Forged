"""Put the repo root on sys.path when Streamlit launches a page file."""

import sys
from pathlib import Path


def install(start: str | Path) -> Path:
    here = Path(start).resolve()
    here = here if here.is_dir() else here.parent
    for candidate in [here, *here.parents]:
        if (candidate / "config.py").exists():
            root = str(candidate)
            if root not in sys.path:
                sys.path.insert(0, root)
            return candidate
    raise RuntimeError("Could not find the Forged Machine Monitoring repo root.")

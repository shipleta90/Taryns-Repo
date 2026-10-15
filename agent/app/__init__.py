import sys

if sys.version_info < (3, 10):
    raise SystemExit(
        f"Personal Agent needs Python 3.10 or newer, but this is {sys.version.split()[0]}. "
        "Install a newer Python (python.org), recreate the .venv with it, and try again."
    )

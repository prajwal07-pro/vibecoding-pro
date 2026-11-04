from pathlib import Path
import sys

# Ensure project root is on sys.path so main.py can be imported cleanly in Vercel's runtime
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from main import app  # noqa: E402, F401
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kde_bot import legacy_core

# Keep the preserved matching regression suite intact.
sys.modules["kde_downloader_core"] = legacy_core

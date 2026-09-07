#!/usr/bin/env python3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.web_dashboard import serve


if __name__ == "__main__":
    print("Dashboard: http://127.0.0.1:8765")
    serve()

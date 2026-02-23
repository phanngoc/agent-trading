"""
Entry point: python -m chatbot  (or console_script trend-chatbot)

Launches the Chainlit UI on the configured port.
"""
import os
import subprocess
import sys
from pathlib import Path


def main():
    # Locate app.py relative to this package
    app_py = Path(__file__).parent / "app.py"
    port = os.getenv("CHAINLIT_PORT", "8001")
    host = os.getenv("CHAINLIT_HOST", "0.0.0.0")

    cmd = [
        sys.executable, "-m", "chainlit", "run",
        str(app_py),
        "--host", host,
        "--port", port,
    ]
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()

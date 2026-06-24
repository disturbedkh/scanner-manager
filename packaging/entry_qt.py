"""PyInstaller entry — imports gui.app as a package (not as app.py __main__)."""
from gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())

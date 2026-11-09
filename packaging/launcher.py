"""Entry script PyInstaller freezes into Organize photos.app.

It starts the shell, which may swap in newer sorting code from GitHub
Releases before running it (see app_shell/).
"""

import sys

from app_shell.launch import main

if __name__ == "__main__":
    sys.exit(main())

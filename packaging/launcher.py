"""Entry script PyInstaller freezes into Organize photos.app.

It starts the shell, which may swap in newer sorting code from GitHub
Releases before running it (see app_shell/).
"""

import sys

from app_shell.launch import main


def _bundle_built_in_code():  # never called
    """The shell loads the sorting code by name at runtime, which PyInstaller
    can't see. This plain import makes sure the whole package is bundled."""
    import photo_organizer.__main__  # noqa: F401


if __name__ == "__main__":
    sys.exit(main())

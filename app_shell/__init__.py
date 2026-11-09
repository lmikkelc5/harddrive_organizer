"""The fixed part of Organize photos.app: checks GitHub for newer sorting code,
then starts it. This package ships inside the app and is never updated
remotely, so keep it small, careful, and well tested.

Bump SHELL_API only when the shell itself changes in a way new sorting code
depends on. Code that needs a newer shell (photo_organizer.REQUIRES_SHELL)
is never installed; it needs a new app instead.
"""

SHELL_API = 1

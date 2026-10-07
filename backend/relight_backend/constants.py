"""Single place for the app name and other fixed values."""

APP_NAME = "Relight"
APP_VERSION = "0.1.0"

HOST = "127.0.0.1"

# Electron passes the per-launch auth token through this environment variable
# (not argv, which other processes can read).
TOKEN_ENV = "RELIGHT_TOKEN"

# Overrides where models, sessions, and logs live (default: %APPDATA%/<APP_NAME>).
DATA_DIR_ENV = "RELIGHT_DATA_DIR"

# Maps are computed at this size (long edge, pixels); the original is kept untouched.
WORKING_LONG_EDGE = 1536

# Depth maps are relative, in [0, 1]. This factor turns them into scene depth in
# image-width units. The live-preview shader must use the same value.
DEPTH_SCALE = 0.4

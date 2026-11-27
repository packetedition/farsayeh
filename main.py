"""Entry point: importing the modules registers their @expose functions."""

from bridge import run
from module import cleaner, demo, rose, wind_speed  # noqa: F401  (import registers handlers)

if __name__ == "__main__":
    cleaner.clear_assets_files()  # clear every Files in assets Directory!
    run()

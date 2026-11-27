"""Entry point: importing the modules registers their @expose functions."""

from bridge import run
from module import demo, rose, wind_speed, cleaner  # noqa: F401  (import registers handlers)





if __name__ == "__main__":
    cleaner.clear_assets_files() # clear every Files in assets Directory!
    run()

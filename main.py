"""Entry point: importing the modules registers their @expose functions."""

from bridge import run
from module import demo, rose, wind_speed  # noqa: F401  (import registers handlers)

if __name__ == "__main__":
    run() 

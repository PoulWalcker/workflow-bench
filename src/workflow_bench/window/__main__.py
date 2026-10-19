"""Command-line entry point for task-owned observation windows."""

import logging

from workflow_bench.window import driver

if __name__ == "__main__":
    driver.LOGGER = logging.getLogger(__name__)
    raise SystemExit(driver.main())

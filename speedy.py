#!/usr/bin/env python3
"""SpeedyLock entry point: `python speedy.py <command>`."""

import sys

from speedylock.cli import main

if __name__ == "__main__":
    sys.exit(main())

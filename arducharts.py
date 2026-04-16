#!/usr/bin/env python3
"""Entry point for arducharts. The actual code lives in the arducharts/ package.

Usage:
    python arducharts.py <command> [args]
    python -m arducharts <command> [args]
"""

from arducharts.cli import main

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Retired first-generation deployment bootstrap; intentionally never executes work."""
import sys


def main():
    print("WikiContext bootstrap retired; use the maintained once-pocketcontext-v2 scaffold and explicit container init command.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

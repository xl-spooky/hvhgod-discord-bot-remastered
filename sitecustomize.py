"""Project-wide Python startup customization.

This file is imported automatically by Python (via the `site` module) if it is
on `sys.path` at interpreter startup. We turn off bytecode writing globally so
`__pycache__` directories and `.pyc` files are not created during development.

If you prefer an environment toggle, set `PYTHONDONTWRITEBYTECODE=1` instead or
start Python with the `-B` flag. Keeping this file ensures consistent behavior
for all entry points without extra flags.
"""

from __future__ import annotations

import sys

# Prevent creation of __pycache__ and .pyc files
sys.dont_write_bytecode = True

"""`python -m tello_revived` (also the entry point the standalone builds use)."""

import sys

from tello_revived.cli import main

sys.exit(main())

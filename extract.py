#!/usr/bin/env python3
"""EOD engine: build one day's receipt from files already on your Mac.

The implementation lives in the eod/ package, one module per concern. This file
stays the entry point because eod.lua invokes it by path and every existing
install has it sitting in ~/.hammerspoon, so moving it would break them silently.

    python3 extract.py --date 2026-08-06
    python3 extract.py --weekly
    python3 extract.py --show-polish-payload     # prints the payload, sends nothing

The star imports are deliberate. They preserve the flat namespace this module
used to have, so anything that reached into it keeps working.
"""

import os
import sys

# realpath, not abspath: ~/.hammerspoon/extract.py is commonly a symlink into a
# checkout, and abspath would resolve to the symlink's directory, where the eod
# package is not. This currently works only because Python resolves sys.path[0]
# for a symlinked script; relying on that is luck, not design.
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from eod.util import *              # noqa: F401,F403  text, dates, paths, noise filter
from eod.config import *            # noqa: F401,F403  paths, user config, display limits
from eod.sources.claude import *    # noqa: F401,F403
from eod.sources.codex import *     # noqa: F401,F403
from eod.sources.git import *       # noqa: F401,F403
from eod.sources.web import *       # noqa: F401,F403
from eod.sources.apps import *      # noqa: F401,F403
from eod.sources.docs import *      # noqa: F401,F403
from eod.sources.meetings import *  # noqa: F401,F403
from eod.pipeline import *          # noqa: F401,F403  build()
from eod.polish import *            # noqa: F401,F403
from eod.render.text import *       # noqa: F401,F403
from eod.render.html import *       # noqa: F401,F403
from eod.weekly import *            # noqa: F401,F403
from eod.cli import main            # noqa: F401

if __name__ == "__main__":
    main()

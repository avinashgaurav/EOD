# Adding a source

Sources are discovered, not hardcoded, so adding Linear, Jira, Toggl or anything
else means writing one file. Drop it in `~/.eod/sources/` and it is picked up:
no fork, no edit to this repo.

```python
# ~/.eod/sources/linear.py
import os
from eod.sources.base import Source, register

class LinearSource(Source):
    name    = "linear"
    section = "SHIPPED"          # where it shows: WORK, SHIPPED, WEB, SCREEN, DOCS, MEETINGS
    key     = "linear_issues"    # which field of the day it fills
    summary = "Issues you moved today"
    requires = "a LINEAR_API_KEY"

    def available(self):
        """Is this set up? Must never raise. False means stay quiet."""
        return bool(os.environ.get("LINEAR_API_KEY"))

    def read(self, date):
        """Items for the local day. Raise on real failure; the caller reports it."""
        return [{"id": "ENG-1", "title": "closed the flaky test"}]

register(LinearSource())
```

The split between `available()` and `read()` is the whole point. A source that
is not configured says nothing. A source that **is** configured and then fails is <!--claim:source-absent-silent-->
reported on the receipt, because those two used to look identical from the <!--claim:source-failure-visible-->
outside, and that is how a broken section can sit there for days looking like a
quiet one.

Items under a `key` the renderers do not know are kept in `data["extra"]` rather <!--claim:plugin-extra-kept-->
than dropped. A plugin that blows up on import is reported and skipped: a <!--claim:broken-plugin-skipped-->
third-party file cannot stop your receipt building.

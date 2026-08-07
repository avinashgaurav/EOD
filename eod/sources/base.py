"""The source contract, and the registry that finds them.

A source is somewhere your work leaves a trace. Adding one should mean writing one
file, not editing the pipeline, so the pipeline asks the registry rather than
importing readers by name.

The contract deliberately separates two things that used to look identical from
the outside:

    available() is False   this source is not set up. Silence is correct.
    read() raises          this source IS set up and broke. Say so, loudly.

That distinction is the whole reason a missing icalBuddy and a corrupt calendar
database used to produce the same empty section with no way to tell them apart.
"""

import os
import traceback


class SourceError(Exception):
    """A configured source failed. The receipt should say so, not hide it."""


class Source:
    """Subclass, set the class attributes, implement available() and read()."""

    #: short machine name, e.g. "git". Must be unique.
    name = None
    #: which part of the receipt this feeds, for display: WORK, SHIPPED, WEB, ...
    #: Several sources may share a section.
    section = None
    #: which field of the day dict the items land in. Must be unique per source
    #: unless two sources genuinely produce interchangeable items.
    key = None
    #: one line, shown by `eod sources`
    summary = ""
    #: what has to exist for this to work, shown when it is unavailable
    requires = ""

    def available(self):
        """True if this source is set up and can be read.

        Must never raise: a source that cannot even answer this is unavailable.
        Return False for "not installed", "not configured", "no such directory".
        """
        return True

    def read(self, date):
        """Return this source's items for the local day `date` (YYYY-MM-DD).

        Raise on real failure. The caller catches, records, and surfaces it; that
        is a signal, not something to swallow.
        """
        raise NotImplementedError

    # -- plumbing -------------------------------------------------------------

    def safe_available(self):
        try:
            return bool(self.available())
        except Exception:
            return False

    def collect(self, date):
        """(items, error). Never raises, so one broken source cannot lose the day."""
        if not self.safe_available():
            return [], None
        try:
            return self.read(date) or [], None
        except Exception as e:
            return [], "%s: %s" % (type(e).__name__, e)

    def __repr__(self):
        return "<Source %s>" % (self.name or self.__class__.__name__)


_REGISTRY = {}


def register(source):
    """Add a source. Later registration of the same name wins, so a user plugin
    can deliberately replace a built-in."""
    if not isinstance(source, Source):
        source = source()
    if not source.name:
        raise ValueError("source %r has no name" % source)
    _REGISTRY[source.name] = source
    return source


def registry():
    """All registered sources, in a stable order so output does not shuffle."""
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def get(name):
    return _REGISTRY.get(name)


def load_plugins(directory):
    """Import every .py in `directory` so it can register sources.

    Used for ~/.eod/sources, which lets someone add Linear or Jira without
    touching this repository. A plugin that blows up on import is reported and
    skipped: a third-party file must not be able to stop the receipt building.
    """
    errors = []
    if not directory or not os.path.isdir(directory):
        return errors
    import importlib.util
    for fn in sorted(os.listdir(directory)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        path = os.path.join(directory, fn)
        try:
            spec = importlib.util.spec_from_file_location("eod_plugin_" + fn[:-3], path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception:
            errors.append("%s: %s" % (fn, traceback.format_exc(limit=1).strip().split("\n")[-1]))
    return errors

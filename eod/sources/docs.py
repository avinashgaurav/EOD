"""DOCUMENTS: decks, docs, sheets and PDFs you touched."""

import os
from datetime import datetime

from ..config import DOC_EXTS, DOC_ROOTS, _DOC_SKIP_DIRS


def read_docs(date):
    """Documents you created/edited on `date` (decks, docs, sheets, PDFs) in your work folders."""
    out, seen = [], set()
    for root in DOC_ROOTS:
        base = os.path.expanduser(root)
        if not os.path.isdir(base):
            continue
        base_depth = base.rstrip("/").count("/")
        for dirpath, dirs, files in os.walk(base):
            if dirpath.rstrip("/").count("/") - base_depth >= 4:
                dirs[:] = []
            dirs[:] = [d for d in dirs if d not in _DOC_SKIP_DIRS and not d.startswith(".")]
            for f in files:
                ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
                if ext not in DOC_EXTS or f.startswith("~$") or f.startswith(".") or f in seen:
                    continue
                p = os.path.join(dirpath, f)
                try:
                    if datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d") != date:
                        continue
                except Exception:
                    continue
                seen.add(f)
                out.append({"name": f, "ext": ext, "folder": os.path.basename(dirpath)})
    return out[:40]

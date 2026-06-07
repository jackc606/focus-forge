"""Honor HOI4 `replace_path` so we don't mix vanilla content into a mod that
replaces a directory (e.g. Millennium Dawn replaces `common/technologies`)."""
from __future__ import annotations

import os
import re

_REPLACE = re.compile(r'replace_path\s*=\s*"([^"]+)"')


def read_replace_paths(root: str) -> set:
    """The set of paths a mod root declares it replaces (forward-slash, no trailing /)."""
    out = set()
    desc = os.path.join(root, "descriptor.mod")
    if not os.path.isfile(desc):
        return out
    try:
        text = open(desc, "r", encoding="utf-8-sig", errors="replace").read()
    except OSError:
        return out
    for m in _REPLACE.finditer(text):
        out.add(m.group(1).replace("\\", "/").strip("/"))
    return out


def effective_roots_for_path(roots, subpath: str) -> list:
    """Roots whose content for ``subpath`` should be loaded, honoring replace_path.
    If a root replaces the path, earlier roots' content for it is dropped."""
    sub = subpath.replace("\\", "/").strip("/")
    last_replacer = -1
    for i, root in enumerate(roots):
        if sub in read_replace_paths(root):
            last_replacer = i
    return list(roots[last_replacer:]) if last_replacer >= 0 else list(roots)

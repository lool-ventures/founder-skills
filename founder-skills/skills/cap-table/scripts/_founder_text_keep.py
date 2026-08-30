"""The keep set every cap-table founder-text call site must use.

ONE construction, deliberately. `compose_report` built this inline and the three siblings --
`quick_assess`, `counsel_packet`, `_rules.founder_text` -- passed nothing, so the vocabulary this
skill deliberately glosses was preserved on one route and destroyed on the other three. The
asymmetry is invisible by inspection: each site reads as "we apply the founder-text policy here".

Measured symptom: `structural_only` survives in `report.md` (a `_labels.MAPS` key, kept by contract)
and arrives as `structural only` in the fast-assess report, the counsel packet, and -- via
`_rules.founder_text` -- in the text nodes of `report.html` and `explorer.html`. A founder reading
`structural only` has a term that matches no field, no enum, and nothing they can look up.

`compose_report` additionally unions `identifier_values(artifacts)`, which is data-dependent (it
reads a loaded artifact tree for scenario and instrument ids). That cannot be static, so it stays at
that call site; this module is the STATIC floor every site shares.
"""

from __future__ import annotations

import os
import sys


def _labels_maps() -> dict:
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _labels

    return dict(_labels.MAPS)


def cap_table_keep() -> frozenset[str]:
    """Every term `_labels.py` glosses, as a keep set for `substitute` / `scan`.

    Read from `_labels.MAPS` live, never copied: a copy stays clean while the glossary drifts, which
    is exactly the failure this exists to prevent.
    """
    return frozenset(k for m in _labels_maps().values() for k in m)

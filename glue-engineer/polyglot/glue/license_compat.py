"""
polyglot/glue/license_compat.py — SPDX license compatibility matrix.

Maps license compatibility scores between SPDX identifiers.
0.0 = incompatible, 0.5 = conditional, 1.0 = fully compatible.
"""

LICENSE_COMPAT = {
    "MIT": {"MIT": 1.0, "Apache-2.0": 1.0, "BSD-2-Clause": 1.0, "BSD-3-Clause": 1.0,
            "LGPL-3.0": 1.0, "GPL-2.0": 1.0, "GPL-3.0": 1.0, "CC0-1.0": 1.0, "Unlicense": 1.0, "": 1.0},
    "Apache-2.0": {"Apache-2.0": 1.0, "MIT": 1.0, "BSD-2-Clause": 1.0, "BSD-3-Clause": 1.0,
                   "LGPL-3.0": 1.0, "GPL-2.0": 1.0, "GPL-3.0": 1.0, "CC0-1.0": 1.0, "Unlicense": 1.0, "": 1.0},
    "GPL-3.0": {"GPL-3.0": 1.0, "GPL-2.0": 1.0, "MIT": 0.5, "Apache-2.0": 0.5, "BSD-2-Clause": 0.5, "BSD-3-Clause": 0.5,
                "LGPL-3.0": 1.0, "CC0-1.0": 1.0, "Unlicense": 1.0, "": 0.5},
    "GPL-2.0": {"GPL-2.0": 1.0, "GPL-3.0": 1.0, "MIT": 0.5, "Apache-2.0": 0.5, "BSD-2-Clause": 0.5, "BSD-3-Clause": 0.5,
                "LGPL-3.0": 1.0, "CC0-1.0": 1.0, "Unlicense": 1.0, "": 0.5},
    "LGPL-3.0": {"LGPL-3.0": 1.0, "GPL-2.0": 1.0, "GPL-3.0": 1.0, "MIT": 1.0, "Apache-2.0": 1.0,
                 "BSD-2-Clause": 1.0, "BSD-3-Clause": 1.0, "CC0-1.0": 1.0, "Unlicense": 1.0, "": 1.0},
    "BSD-3-Clause": {"BSD-3-Clause": 1.0, "BSD-2-Clause": 1.0, "MIT": 1.0, "Apache-2.0": 1.0,
                     "LGPL-3.0": 1.0, "GPL-2.0": 1.0, "GPL-3.0": 1.0, "CC0-1.0": 1.0, "Unlicense": 1.0, "": 1.0},
    "BSD-2-Clause": {"BSD-2-Clause": 1.0, "BSD-3-Clause": 1.0, "MIT": 1.0, "Apache-2.0": 1.0,
                     "LGPL-3.0": 1.0, "GPL-2.0": 1.0, "GPL-3.0": 1.0, "CC0-1.0": 1.0, "Unlicense": 1.0, "": 1.0},
    "CC0-1.0": {"CC0-1.0": 1.0, "MIT": 1.0, "Apache-2.0": 1.0, "BSD-2-Clause": 1.0, "BSD-3-Clause": 1.0,
               "LGPL-3.0": 1.0, "GPL-2.0": 1.0, "GPL-3.0": 1.0, "Unlicense": 1.0, "": 1.0},
    "Unlicense": {"Unlicense": 1.0, "MIT": 1.0, "Apache-2.0": 1.0, "BSD-2-Clause": 1.0, "BSD-3-Clause": 1.0,
                  "LGPL-3.0": 1.0, "GPL-2.0": 1.0, "GPL-3.0": 1.0, "CC0-1.0": 1.0, "": 1.0},
    "": {"": 1.0, "MIT": 0.5, "Apache-2.0": 0.5, "BSD-2-Clause": 0.5, "BSD-3-Clause": 0.5,
         "LGPL-3.0": 0.5, "GPL-2.0": 0.5, "GPL-3.0": 0.5, "CC0-1.0": 0.5, "Unlicense": 0.5},
}
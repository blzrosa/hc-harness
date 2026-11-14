"""Atalho: a auditoria vive em hc_harness.audit (comando `clara`)."""

import sys

from hc_harness.audit import main

sys.exit(main(sys.argv[1:]))

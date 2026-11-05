"""One stand-in for Airflow and pendulum, for every test here.

The DAG files import them at the top, and the tests reach none of it: they
test the helpers beside the DAGs. Installed before any test file is imported,
so the files' own stand-ins - each written for one DAG - never meet; the
first of them used to win for all the others.
"""

import sys
from unittest.mock import MagicMock

for name in ("airflow", "airflow.sdk", "pendulum"):
    sys.modules.setdefault(name, MagicMock())

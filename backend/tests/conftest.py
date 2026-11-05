"""Shared test setup.

MedLink refuses to start without JWT_SECRET (see load_jwt_secret() in
permissions.py). The suite runs in development mode so the modules import
with the known development key, which is what the token-minting helpers in
test_rbac.py and test_audit.py expect. test_jwt_secret.py covers the other
two cases in subprocesses, where the environment can be controlled properly.
"""

import os

os.environ.setdefault("MEDLINK_DEV", "1")

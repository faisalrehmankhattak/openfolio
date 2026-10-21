import os

# Tests must not call real providers.
os.environ["OPENFOLIO_SKIP_CHECKS"] = "1"

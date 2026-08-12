import os
import sys

# Make the shared-types package importable as `models` for every src.* module.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'packages', 'shared-types', 'src'))

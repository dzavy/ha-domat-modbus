"""Make the repo's custom_components visible next to the test harness's own."""
from pathlib import Path

import custom_components

_ours = str(Path(__file__).parents[1] / "custom_components")
if isinstance(custom_components.__path__, list) and _ours not in custom_components.__path__:
    custom_components.__path__.insert(0, _ours)

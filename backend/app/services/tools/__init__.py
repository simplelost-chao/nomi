"""Import this package to trigger tool registration side-effects."""

from app.services.tools import amap, news  # noqa: F401
from app.services.tools.registry import all_tools, gate_match, get_tool, register  # noqa: F401

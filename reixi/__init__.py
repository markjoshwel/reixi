"""
reixi: utiity-first general-purpose d*scord bot
-----------------------------------------------
copyright (c) 2023, mark joshwel <mark@joshwel.co>
SPDX-License-Identifier: AGPL-3.0-or-later
"""

from . import common, db
from .common import VERSION, VERSION_SUFFIX, Result
from .internals import Bot, Context, is_user_privileged
from .reixi import ReiXI

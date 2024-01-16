"""
reixi: utiity-first general-purpose d*scord bot
-----------------------------------------------
copyright (c) 2023, mark joshwel <mark@joshwel.co>
SPDX-License-Identifier: AGPL-3.0-or-later
"""

import inspect
import logging
from dataclasses import dataclass
from datetime import datetime
from hashlib import blake2s
from os import getenv
from pathlib import Path
from traceback import format_tb

import discord
from discord.ext import commands
from loguru import logger

from . import common
from .common import VERSION, VERSION_SUFFIX, Result
from .db import AbstractBackend


class InterceptHandler(logging.Handler):
    """logging handler taken from https://github.com/Delgan/loguru#entirely-compatible-with-standard-logging"""

    def emit(self, record: logging.LogRecord) -> None:
        # get corresponding loguru level if it exists
        level: str | int
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # find caller
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


async def hash_file(path: Path) -> str:
    """returns the blake2s hash of a file"""
    hasher = blake2s()
    with path.open("rb") as file:
        hasher.update(file.read())
    return hasher.hexdigest()


async def get_prefix(bot: "Bot", message: discord.Message) -> list[str] | str:
    """returns the prefix for the bot"""
    assert isinstance(bot, Bot), "unreachable: bot is not a Bot"
    return (
        [common.PREFIX, ""]
        if not isinstance(message.guild, discord.Guild)
        else await bot.db.get_server_specific_prefix(message.guild.id)
    )


@dataclass
class Module:
    name: str
    path: str
    loaded: bool
    hash: str


class Context(commands.Context):
    """extended context to house some reixi variables"""

    def __init__(self, bot: "Bot", *args, **kwargs):
        super().__init__(bot=bot, *args, **kwargs)


class Bot(commands.Bot):
    """extended bot to house some reixi variables"""

    db: AbstractBackend
    init_time: datetime
    modules: list[Module] = []

    def __init__(
        self,
        db: AbstractBackend,
        init_time: datetime,
        modules: list[Module],
        *args,
        **kwargs,
    ):
        self.db = db
        self.init_time = init_time
        self.modules = modules
        super().__init__(*args, **kwargs)

    async def get_context(self, message, *, cls=Context):
        """overrides the default get_context to use the extended context"""
        return await super().get_context(message, cls=cls)

    async def refresh_module_info(self) -> None:
        """regnenerate module info and hashes"""
        seen_cog_paths: list[str] = []

        for name, cog in self.cogs.items():
            # NOTE: if you needlessly toyed with a toy projects structure name even
            #       though you could change the name in reixi.commons.NAME,
            #       you can change the name of the module here if you really want
            #       to keep hashing working (which you should, it's good + the AGPL)

            cog_hash: str = "unknown"
            core_path: str = "reixi.reixi"
            builtin_path: str = "reixi.builtins"

            seen_cog_paths.append(cog.__module__)

            # hash if built-in
            if cog.__module__ == core_path or cog.__module__.startswith(
                f"{builtin_path}."
            ):
                # fiddle around to get the path of the cog
                _cog_path = cog.__module__

                if cog.__module__ == core_path:
                    _cog_path = (
                        _cog_path[
                            len(str(core_path.split(".", maxsplit=1)[0])) + 1 :
                        ].replace(".", "/")
                        + ".py"
                    )
                else:
                    _cog_path = (
                        _cog_path[
                            len(str(builtin_path.split(".", maxsplit=1)[0])) + 1 :
                        ].replace(".", "/")
                        + ".py"
                    )

                cog_path = Path(__file__).parent.joinpath(_cog_path)

            # core module
            if cog_path == ".py":
                cog_path = Path(__file__).parent.joinpath("reixi.py")

            if not cog_path.exists() and not cog_path.is_file():
                logger.error(
                    f"unable to hash built-in module '{name}' assumed at '{cog_path}' "
                    "(path does not exist)"
                )
                continue

            try:
                cog_hash = await hash_file(cog_path)

            except Exception as err:
                logger.error(
                    f"unable to hash built-in module '{name}' assumed at '{cog_path}'"
                    + "\n"
                    + "\n".join(format_tb(err.__traceback__))
                )

            module = Module(
                name=name, path=cog.__module__, loaded=True, hash=cog_hash[:10]
            )

            already_registered: bool = False
            for reg_module in self.modules:
                if reg_module.path == cog.__module__:
                    reg_module.name = name
                    reg_module.loaded = True
                    reg_module.hash = cog_hash[:10]
                    already_registered = True

            if not already_registered:
                self.modules.append(module)
                logger.debug(
                    f"registered module '{module.name}' ({module.path}) @ {module.hash}"
                )

        for module in self.modules:
            if module.path not in seen_cog_paths:
                module.loaded = False

        logger.info("refreshed module info")


async def is_user_privileged(ctx: Context, module: str = "") -> bool:
    """checks if user has privileges to access a module command"""
    if not ctx.guild:
        return False

    if (
        isinstance(ctx.author, discord.Member)
        and ctx.author.guild_permissions.administrator
    ):
        return True

    elif module == "":
        return False

    assert isinstance(ctx.bot, Bot), "unreachable: ctx.bot is not a Bot"
    assert isinstance(
        ctx.author, discord.Member
    ), "unreachable: ctx.author is not a Member when ctx.guild is None"

    role_privileges = []

    for role in ctx.author.roles:
        privileges = await ctx.bot.db.get_module_privileges(
            guild_id=ctx.guild.id, module=module.lower()
        )
        role_privileges.append(True if role.id in privileges.allow else False)

    return any(role_privileges)


def version_string() -> str:
    """returns a nicer version string"""
    return f"{VERSION[0]}.{VERSION[1]}.{VERSION[2]}".rstrip(".0") + VERSION_SUFFIX


def figure_log_dir() -> Result[Path]:
    """
    tries the following in order:
    - $REIXI_LOG_DIR
    - $XDG_RUNTIME_DIR/reixi
    - <cwd>/logs
    """

    log_dir: str | None = None
    verify_res: Result[bool]

    if (log_dir := getenv(common.ENV_LOG_DIR)) is not None:
        target_path = Path(log_dir)
        verify_res = verify_dir(target_path)
        if verify_res:
            return Result[Path](target_path)
        else:
            logger.warning(
                f"unable to write to ${common.ENV_LOG_DIR}, falling back to $XDG_RUNTIME_DIR/reixi"
            )

    if (log_dir := getenv("XDG_RUNTIME_DIR")) is not None:
        target_path = Path(log_dir).joinpath("reixi")
        verify_res = verify_dir(target_path)
        if verify_res:
            return Result[Path](target_path)
        else:
            logger.warning(
                "unable to write to $XDG_RUNTIME_DIR/reixi, falling back to ./logs"
            )

    target_path = Path.cwd().joinpath("logs")
    verify_res = verify_dir(target_path)
    if verify_res:
        return Result[Path](target_path)
    else:
        logger.error("unable to write to any log directory, not saving logs")
        return Result(Path(), error=verify_res.error)


def figure_db_dir() -> Result[Path]:
    """
    tries the following in order:
    - $REIXI_DB_DIR
    - $XDG_DATA_HOME/reixi
    - ~/.local/share/reixi
    - <cwd>/db
    """

    db_dir: str | None = None
    verify_res: Result[bool]

    if (db_dir := getenv(common.ENV_DB_DIR)) is not None:
        target_path = Path(db_dir)
        verify_res = verify_dir(target_path, read=True)
        if verify_res:
            return Result[Path](target_path)
        else:
            logger.warning(
                f"unable to write and read to ${common.ENV_DB_DIR}, falling back to $XDG_DATA_HOME/reixi"
            )

    if (db_dir := getenv("XDG_DATA_HOME")) is not None:
        target_path = Path(db_dir).joinpath("reixi")
        verify_res = verify_dir(target_path, read=True)
        if verify_res:
            return Result[Path](target_path)
        else:
            logger.warning(
                "unable to write and read to $XDG_DATA_HOME/reixi, falling back to ~/.local/share/reixi"
            )

    target_path = Path.home().joinpath(".local", "share", "reixi")
    verify_res = verify_dir(target_path, read=True)
    if verify_res:
        return Result[Path](target_path)
    else:
        logger.warning(
            "unable to write and read to ~/.local/share/reixi, falling back to ./db"
        )

    target_path = Path.cwd().joinpath("db")
    verify_res = verify_dir(target_path, read=True)
    if verify_res:
        return Result[Path](target_path)
    else:
        logger.critical("unable to write and read to any db directory")
        return Result(Path(), error=verify_res.error)


def verify_dir(target: Path, read: bool = False) -> Result[bool]:
    """
    writes a test file and ensures the target path is a dir, exists, and is writable.
    optionally checks if it is readable too

    arguments
        `target: Path`
            the directory to verify
        `read: bool = False`
            whether to check if the directory is readable
    """

    if not target.is_dir():
        try:
            target.mkdir(parents=True, exist_ok=True)

        except Exception as err:
            return Result[bool](False, error=err)

        return Result[bool](False, NotADirectoryError(f"'{target}' is not a directory"))

    if not target.exists():
        return Result[bool](False, NotADirectoryError(f"'{target}' does not exist"))

    try:
        target.joinpath("prod").write_text(
            "reixi directory verification test file\n", encoding="utf-8"
        )

    except Exception as err:
        return Result[bool](False, error=err)

    if read:
        try:
            if (
                target.joinpath("prod").read_text(encoding="utf-8")
                != "reixi directory verification test file\n"
            ):
                return Result[bool](False, ValueError("test file contents mismatch"))

        except Exception as err:
            return Result[bool](False, error=err)

    return Result[bool](True)

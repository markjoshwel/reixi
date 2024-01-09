"""
reixi: utiity-first general-purpose d*scord bot
-----------------------------------------------
copyright (c) 2023, mark joshwel <mark@joshwel.co>
SPDX-License-Identifier: AGPL-3.0-or-later
"""


import logging
from datetime import datetime
from enum import Enum
from os import getenv
from pathlib import Path
from traceback import format_tb

import discord
import uvloop
from discord.ext import commands
from loguru import logger
from thefuzz import process  # type: ignore

from . import common, db, internals
from .common import SOURCE_CODE, Result
from .internals import Bot, Context

intents = discord.Intents.default()
intents.message_content = True


# loguru and logging wrangling
_default_level = logging.INFO
_logger = logging.getLogger("discord")
_logger.setLevel(_default_level)
_logger.addHandler(internals.InterceptHandler())
_logger.propagate = False
_logger = logging.getLogger("discord.client")
_logger.setLevel(_default_level)
_logger.addHandler(internals.InterceptHandler())
_logger.propagate = False
_logger = logging.getLogger("discord.gateway")
_logger.setLevel(_default_level)
_logger.addHandler(internals.InterceptHandler())
_logger.propagate = False
_logger = logging.getLogger("discord.ext")
_logger.setLevel(_default_level)
_logger.addHandler(internals.InterceptHandler())
_logger.propagate = False


class ModuleAcessSetFlag(Enum):
    ALLOW = "allow"
    DENY = "deny"
    REMOVE = "remove"


class Core(commands.Cog):
    bot: Bot
    reixi_god_commands: list[str] = ["gmod", "gstate"]
    reixi_privileged_commands: list[str] = ["modules", "moduleaccess"]

    def __init__(self, bot: Bot):
        self.bot: Bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        assert isinstance(
            self.bot.user, discord.ClientUser
        ), "unreachable: bot.user is not a ClientUser"

        logger.success(
            f"ready as {self.bot.user.name}#{self.bot.user.discriminator} ({self.bot.user.id})"
        )

    @commands.Cog.listener()
    async def on_command_error(self, ctx: Context, err: commands.CommandError):
        if isinstance(err, commands.CommandNotFound):
            assert isinstance(ctx.bot, Bot), "unreachable: ctx.bot is not a reixi.Bot"

            all_commands: list[str] = []
            for module in ctx.bot.cogs.values():
                for command in module.get_commands():
                    all_commands.append(command.name)
                    for alias in command.aliases:
                        all_commands.append(alias)

            closest: tuple[str, int] = process.extractOne(
                ctx.invoked_with, all_commands
            )
            if closest[1] > 70:
                await ctx.reply(f"did you mean `{closest[0]}`?")

            return

        await self.bot.on_command_error(ctx, err)

    @commands.command(name="help")
    async def help(self, ctx: Context, *_args: tuple[str]) -> None:
        """shows help information"""
        assert isinstance(ctx.bot, Bot), "unreachable: ctx.bot is not a reixi.Bot"

        args: list[str] = common.fix_args(_args)

        # form help text
        if isinstance(ctx.guild, discord.Guild):
            prefix = (
                "this server's prefix is \""
                + await ctx.bot.db.get_server_specific_prefix(ctx.guild.id)
                + '"'
            )
        else:
            prefix = 'prefixes are not needed in dms, but you can use `"rx "`'

        help_text: list[str] = [
            f"{common.NAME} version {internals.version_string()}",
            f"{ctx.bot.description}",
            f"",
            prefix,
            "",
        ]

        caller_is_god = True if (ctx.author.id in ctx.bot.db.config.gods) else False

        loaded_modules: list[str] = [m.name.lower() for m in ctx.bot.modules]
        if ctx.guild:
            loaded_modules = await ctx.bot.db.get_server_specific_modules(ctx.guild.id)

        for module_name, module in ctx.bot.cogs.items():
            if (module_name.lower() not in loaded_modules) and (module_name != "core"):
                continue

            if (len(args) > 0) and (module_name.lower() not in args):
                continue

            module_god_commands = getattr(module, "reixi_god_commands", [])
            module_privileged_commands = getattr(
                module, "reixi_privileged_commands", []
            )
            caller_is_privileged = await internals.is_user_privileged(
                ctx=ctx, module=module_name.lower()
            )

            help_text.append(f"module {module_name.lower()}")

            for command in module.get_commands():
                if not caller_is_god and (command.name in module_god_commands):
                    continue

                if not caller_is_privileged and (
                    command.name in module_privileged_commands
                ):
                    continue

                help_text.append(f"   {command.name}")
                for alias in command.aliases:
                    help_text.append(f"   {alias}")
                if command.help is not None:
                    help_text[-1] += f"\n      {command.help}"

            help_text.append("")

        help_text.pop()

        # chunk into 2000 character messages
        chunk: list[str] = []

        while len(help_text) > 0:
            chunk.append(help_text.pop(0))

            if (
                len("\n".join(chunk)) > 2000 - 6 - 2
            ):  # 6 for the code block, 2 for the newlines
                await ctx.reply("```\n" + "\n".join(chunk) + "\n```")
                chunk = []

        await ctx.reply("```\n" + "\n".join(chunk) + "\n```")

    @commands.command(name="stat", aliases=["status"])
    async def status(self, ctx: Context) -> None:
        """displays reixi status and some server information"""
        assert isinstance(ctx.bot, Bot), "unreachable: ctx.bot is not a reixi.Bot"

        if len(list(ctx.bot.cogs.items())) != len(ctx.bot.modules):
            await ctx.bot.refresh_module_info()

        longest_module_name_length = len(
            max(ctx.bot.modules, key=lambda x: len(x.name)).name
        )

        modulelist: list[str] = []
        for module in ctx.bot.modules:
            global_status: str = "loaded" if module.loaded else "      "
            local_status: str = "         "
            if isinstance(ctx.guild, discord.Guild) and (
                module.name.lower()
                in await ctx.bot.db.get_server_specific_modules(ctx.guild.id)
            ):
                local_status = "  enabled"

            modulelist.append(
                f"{module.name.ljust(longest_module_name_length)}  "
                f"{global_status}{local_status}  "
                f"{module.hash}"
            )

        guild_info: str
        if isinstance(ctx.guild, discord.Guild):
            guild_info = (
                f"'{ctx.guild.name}' (prefix: "
                f"'{await ctx.bot.db.get_server_specific_prefix(ctx.guild.id)}')"
            )
        else:
            guild_info = "not calling from a guild"

        caller_is_god = (
            f"\n          is god" if (ctx.author.id in ctx.bot.db.config.gods) else ""
        )

        _caller_privileges: list[str] = []
        for module in ctx.bot.modules:
            _caller_privileges.append(
                f"\n          is privileged for module {module.name}"
                if await internals.is_user_privileged(ctx=ctx, module=module.name)
                else ""
            )
        caller_privileges = "".join(_caller_privileges)

        await ctx.reply(
            "\n".join(
                [
                    "```",
                    f"{common.NAME} version {internals.version_string()}",
                    f"has been up for {datetime.now() - ctx.bot.init_time}",
                    "",
                    *modulelist,
                    "",
                    "caller information",
                    f"   guild  {guild_info}",
                    f"   user   '{ctx.author.display_name}'"
                    + caller_is_god
                    + caller_privileges,
                    "",
                    f"source code is available at {SOURCE_CODE}",
                    "```",
                ]
            )
        )

    @commands.command(name="gstate", aliases=["gst"])
    async def reload(self, ctx: Context, *_args: tuple[str]) -> None:
        """(god) manage db state"""
        assert isinstance(ctx.bot, Bot), "unreachable: ctx.bot is not a reixi.Bot"
        if ctx.author.id not in ctx.bot.db.config.gods:
            return

        args = common.fix_args(_args)
        errors: list[tuple[str, Exception]] = []

        match args:
            case ["dump"]:
                errors.extend(await ctx.bot.db.reload(dump=True, load=False))

            case ["load"]:
                errors.extend(await ctx.bot.db.reload(dump=False, load=True))

            case ["reload"]:
                errors.extend(await ctx.bot.db.reload())

            case _:
                await ctx.reply(
                    "\n".join(
                        [
                            "```",
                            "reixi db state management",
                            "",
                            "usage:",
                            "   gstate dump",
                            "      sinks the database",
                            "   gstate load",
                            "      overwrite content",
                            "   gstate reload",
                            "      dumps and loads",
                            "```",
                        ]
                    )
                )
                return

        if len(errors) == 0:
            await ctx.message.add_reaction(common.COMMAND_SUCCESS_EMOJI)
            return

        # chunk into 2000 character messages
        chunk: list[str] = []

        while len(errors) > 0:
            message, error = errors.pop(0)
            errortext = (
                message + "\n" + "\n".join(format_tb(error.__traceback__)) + "\n"
            )

            # 6 for the code block, 2 for the newlines
            if (len(("\n".join(chunk))) + len(errortext)) > (2000 - 6 - 2):
                await ctx.reply("```\n" + "\n".join(chunk) + "\n```")
                chunk = [errortext]
            else:
                chunk.append(errortext)

        if len(chunk) == 1:
            await ctx.reply("```\n" + "\n".join(chunk) + "\n```")

    @commands.command(name="gmod")
    async def manage_global_modules(self, ctx: Context, *_args: tuple[str]) -> None:
        """(god) manages reixi modules"""
        assert isinstance(ctx.bot, Bot), "unreachable: ctx.bot is not a reixi.Bot"

        if ctx.author.id not in ctx.bot.db.config.gods:
            return

        # NOTE: if you needlessly toyed with a toy projects structure name even
        #       though you could change the name in reixi.commons.NAME,
        #       you can change the name of the module here if you really want
        #       to keep hashing working (which you should, it's good + the AGPL)

        core_path: str = "reixi.reixi"

        match common.fix_args(_args):
            case ["list"]:
                longest_module_name_length = len(
                    max(ctx.bot.modules, key=lambda x: len(x.name)).name
                )
                longest_module_path_length = len(
                    max(ctx.bot.modules, key=lambda x: len(x.path)).path
                )

                modulelist: list[str] = []
                for module in ctx.bot.modules:
                    modulelist.append(
                        f"{module.name.ljust(longest_module_name_length)}  "
                        f"{module.path.ljust(longest_module_path_length)}  "
                        f"{'  loaded' if module.loaded else 'unloaded'}  "
                        f"{module.hash}"
                    )

                await ctx.reply("\n".join(["```\n", *modulelist, "\n```"]))

            case ["load", module]:
                if module == core_path:
                    await ctx.reply("core module will forever be loaded")
                    return

                try:
                    await ctx.bot.load_extension(module)
                    await ctx.bot.refresh_module_info()

                except Exception as err:
                    logger.error(f"unable to load module '{module}'")
                    await ctx.reply(
                        f"```unable to load module '{module}'\n"
                        f"{'\n'.join(format_tb(err.__traceback__))}"
                        "\n```"
                    )

                else:
                    logger.success(f"loaded module '{module}'")
                    await ctx.message.add_reaction(common.COMMAND_SUCCESS_EMOJI)

            case ["unload", module]:
                if module == core_path:
                    await ctx.reply("core module will forever be loaded")
                    return

                try:
                    await ctx.bot.unload_extension(module)
                    await ctx.bot.refresh_module_info()

                except Exception as err:
                    logger.error(f"unable to unload module '{module}'")
                    await ctx.reply(
                        f"```unable to unload module '{module}'\n"
                        f"{'\n'.join(format_tb(err.__traceback__))}"
                        "\n```"
                    )

                else:
                    logger.success(f"unloaded module '{module}'")
                    await ctx.message.add_reaction(common.COMMAND_SUCCESS_EMOJI)

            case ["reload", module]:
                if module == core_path:
                    await ctx.reply("core module will forever be loaded, once loaded")
                    return

                try:
                    await ctx.bot.reload_extension(module)
                    await ctx.bot.refresh_module_info()

                except Exception as err:
                    logger.error(f"unable to reload module '{module}'")
                    await ctx.reply(
                        f"```unable to reload module '{module}'\n"
                        f"{'\n'.join(format_tb(err.__traceback__))}"
                        "\n```"
                    )

                else:
                    logger.success(f"reloaded module '{module}'")
                    await ctx.message.add_reaction(common.COMMAND_SUCCESS_EMOJI)

            case _:
                await ctx.reply(
                    "\n".join(
                        [
                            "```",
                            "global module management",
                            "",
                            "usage:",
                            "   gmod list",
                            "      lists all modules",
                            "   gmod load MODULE",
                            "      loads `MODULE`",
                            "   gmod unload MODULE",
                            "      unloads `MODULE`",
                            "   gmod reload MODULE",
                            "      reloads `MODULE`",
                            "```",
                        ]
                    )
                )
                return

    @commands.command(name="modules")
    async def manage_local_modules(self, ctx: Context, *_args: tuple[str]) -> None:
        """turn on or off modules for a server"""
        assert isinstance(ctx.bot, Bot), "unreachable: ctx.Bot is not a reixi.Bot"
        if not ctx.guild:
            return

        if not await internals.is_user_privileged(ctx=ctx, module="Core"):
            return

        match common.fix_args(_args):
            case ["enable", target]:
                if target == "Core":
                    await ctx.reply("core module will forever be loaded")
                    return

                server_modules = await ctx.bot.db.get_server_specific_modules(
                    ctx.guild.id
                )

                if target in server_modules:
                    await ctx.reply(f"module '{target}' is already enabled")
                    return

                for module in ctx.bot.modules:
                    if module.name == target:
                        break

                else:
                    await ctx.reply(f"module '{target}' does not exist")
                    return

                await ctx.bot.db.set_server_specific_modules(
                    ctx.guild.id, server_modules + [target]
                )
                await ctx.message.add_reaction(common.COMMAND_SUCCESS_EMOJI)

            case ["disable", target]:
                if target == "Core":
                    await ctx.reply("core module will forever be loaded")
                    return

                server_modules = await ctx.bot.db.get_server_specific_modules(
                    ctx.guild.id
                )

                if target.lower() not in server_modules:
                    await ctx.reply(f"module '{target}' is already disabled")
                    return

                for module in ctx.bot.modules:
                    if module.name == target:
                        break

                else:
                    await ctx.reply(f"module '{target}' does not exist")
                    return

                server_modules.remove(target.lower())
                await ctx.bot.db.set_server_specific_modules(
                    ctx.guild.id, server_modules
                )
                await ctx.message.add_reaction(common.COMMAND_SUCCESS_EMOJI)

            case _:
                await ctx.reply(
                    "\n".join(
                        [
                            "```",
                            "local module management, all modules are disabled by default",
                            ""
                            f"use 'status' to see what modules are included with {common.NAME}",
                            "",
                            "usage:",
                            "   modules enable MODULE",
                            "      loads `MODULE`",
                            "   modules disable MODULE",
                            "      unloads `MODULE`",
                            "```",
                        ]
                    )
                )
                return

    @staticmethod
    async def _validate_id(_role_id: str) -> Result[int]:
        role_id: int
        negated: bool = False

        if _role_id.startswith("-"):
            _role_id = _role_id[1:]

        if not _role_id.isdigit():
            return Result[int](0, error=ValueError("id is not a valid integer"))

        else:
            role_id = int(_role_id)
            return Result[int](1 - role_id if negated else role_id)

    @staticmethod
    async def _modacs_list(
        bot: Bot,
        ctx: Context,
        guild: discord.Guild,
        module: str = "*",
        role_id: int = -1,
        only_roles: bool = False,
    ) -> None:
        if only_roles:
            await ctx.reply(
                "```\n"
                + "\n".join([f"{role.id}  {role.name}" for role in guild.roles])
                + "\n```"
            )
            return

        current_module_names: list[str] = [n.name.lower() for n in bot.modules]
        permlist: list[str] = []

        for rmod, rprivs in (
            await bot.db.get_all_privileged_roles(guild_id=guild.id)
        ).items():
            # if module is set, filter for it else wildcard for everything
            if not ((module == "*") or (module.lower() == rmod.lower())):
                continue

            # if role_id is set, then we filter to find the role_id
            if (role_id != -1) and not (
                (role_id in rprivs.allow) or (role_id in rprivs.deny)
            ):
                continue

            permlist.append(
                rmod + (" ⚠️" if (rmod not in current_module_names) else "")
            )
            if (len(rprivs.allow) == 0) and (len(rprivs.deny) == 0):
                permlist.append("   no module privileges have yet been set")

            if len(rprivs.allow) > 0:
                permlist.append("   allow")

                for role_id in rprivs.allow:
                    role_name = "⚠️"
                    if isinstance(_role_name := guild.get_role(role_id), discord.Role):
                        role_name = _role_name.name
                    permlist.append(f"      {role_id}  {role_name}")

            if len(rprivs.deny) > 0:
                permlist.append("   deny")

                for role_id in rprivs.deny:
                    role_name = "⚠️"
                    if isinstance(_role_name := guild.get_role(role_id), discord.Role):
                        role_name = _role_name.name
                    permlist.append(f"      {role_id}  {role_name}")

            permlist.append("")

        if (len(permlist) > 0) and (permlist[-1] == ""):
            permlist.pop()

        if permlist == []:
            permlist = ["no module privileges have yet been set"]

        await ctx.reply("```\n" + "\n".join(permlist) + "\n```")

    @staticmethod
    async def _modacs_set(
        bot: Bot,
        ctx: Context,
        guild: discord.Guild,
        role_id: int,
        module: str,
        setting: ModuleAcessSetFlag,
    ) -> bool:
        current_privileges = await bot.db.get_module_privileges(
            guild_id=guild.id,
            module=module.lower(),
        )

        match setting:
            case ModuleAcessSetFlag.ALLOW:
                role = guild.get_role(role_id)
                if role is None:
                    await ctx.reply(f"role `{role_id}` does not exist")
                    return False

                if role.id in current_privileges.allow:
                    await ctx.reply(
                        f"role `{role_id}` is already allowed, no chages made"
                    )
                    return False

                if role.id in current_privileges.deny:
                    current_privileges.deny.remove(role.id)

                current_privileges.allow.append(role_id)
                logger.debug(
                    f"allowing role `{role_id}` to access module '{module}' in server '{guild.id}'"
                )

            case ModuleAcessSetFlag.DENY:
                role = guild.get_role(role_id)
                if role is None:
                    await ctx.reply(f"role `{role_id}` does not exist")
                    return False

                if role.id in current_privileges.deny:
                    await ctx.reply(
                        f"role `{role_id}` is already denied, no chages made"
                    )
                    return False

                if role.id in current_privileges.allow:
                    current_privileges.allow.remove(role.id)

                current_privileges.deny.append(role_id)
                logger.debug(
                    f"denying role `{role_id}` to access module '{module}' in server '{guild.id}'"
                )

            case ModuleAcessSetFlag.REMOVE:
                if not (
                    (role_id in current_privileges.allow)
                    or (role_id in current_privileges.deny)
                ):
                    await ctx.reply(
                        f"role `{role_id}` is not allowed or denied, no changes made"
                    )
                    return False

                if role_id in current_privileges.allow:
                    current_privileges.allow.remove(role_id)
                    logger.debug(
                        f"removing role `{role_id}` from allowed roles to access module '{module}' in server '{guild.id}'"
                    )

                if role_id in current_privileges.deny:
                    current_privileges.deny.remove(role_id)
                    logger.debug(
                        f"removing role `{role_id}` from denied roles to access module '{module}' in server '{guild.id}'"
                    )

        await bot.db.set_module_privileges(
            guild_id=guild.id,
            module=module,
            privileges=current_privileges,
        )

        return True

    @staticmethod
    async def _modacs_clean(
        bot: Bot,
        guild: discord.Guild,
        clear_roles: bool = False,
        module: str = "*",
        yes: bool = False,
    ) -> None:
        current_module_names: list[str] = [n.name.lower() for n in bot.modules]
        current_role_ids: list[int] = [r.id for r in guild.roles] + [
            guild.default_role.id
        ]

        old_privileged_dict: dict[
            str, common.ModulePrivileges
        ] = await bot.db.get_all_privileged_roles(guild_id=guild.id)
        new_privileged_dict: dict[str, common.ModulePrivileges] = {}

        for rmod, rprivs in old_privileged_dict.items():
            match [module.lower(), clear_roles]:
                # remove all obsolete modules or remove module if obsolete
                case ["*" | module.lower(), False]:
                    if rmod in current_module_names:
                        new_privileged_dict[rmod] = rprivs

                # remove obsolete roles from all modules or from specific module
                case ["*" | module.lower(), True]:
                    new_privs: common.ModulePrivileges = common.ModulePrivileges()

                    for role in rprivs.allow:
                        if role in current_role_ids:
                            new_privs.allow.append(role)

                    for role in rprivs.deny:
                        if role in current_role_ids:
                            new_privs.deny.append(role)

                    new_privileged_dict[rmod] = new_privs

        await bot.db.set_all_privileged_roles(
            guild_id=guild.id,
            privilege_dict=new_privileged_dict,
        )

    @commands.command(name="moduleaccess", aliases=["modacs"])
    async def manage_local_module_access(
        self, ctx: Context, *_args: tuple[str]
    ) -> None:
        """set which roles can access a module's more sensitive commands"""
        assert isinstance(ctx.bot, Bot), "unreachable: ctx.Bot is not a reixi.Bot"
        if not ctx.guild:
            return

        if not await internals.is_user_privileged(ctx=ctx, module="Core"):
            return

        match common.fix_args(_args):
            case ["list", "roles"]:
                await self._modacs_list(
                    bot=ctx.bot,
                    ctx=ctx,
                    guild=ctx.guild,
                    only_roles=True,
                )

            case ["list"]:
                await self._modacs_list(
                    bot=ctx.bot,
                    ctx=ctx,
                    guild=ctx.guild,
                )

            case ["list", module_or_id]:
                id_res = await self._validate_id(module_or_id)
                if (err := id_res.cry(string=True)) == "":
                    # empty error string means it is an id
                    await self._modacs_list(
                        bot=ctx.bot,
                        ctx=ctx,
                        guild=ctx.guild,
                        role_id=id_res.value,
                    )

                else:
                    # it's a module name
                    await self._modacs_list(
                        bot=ctx.bot,
                        ctx=ctx,
                        guild=ctx.guild,
                        module=module_or_id,
                    )

            case ["set", _role_id, module, setting]:
                id_res = await self._validate_id(_role_id)
                if (err := id_res.cry(string=True)) != "":
                    await ctx.reply(err)
                    return
                role_id = id_res.value

                if module.lower() not in [m.name.lower() for m in ctx.bot.modules]:
                    await ctx.reply(
                        f"module `{module}` does not exist or has not been loaded yet"
                    )
                    return

                module = module.lower()

                if setting not in (flags := [f.value for f in ModuleAcessSetFlag]):
                    await ctx.reply(
                        f"SETTING should be a choice from "
                        + ", ".join([f"`{f}`" for f in flags])
                    )
                    return

                if await self._modacs_set(
                    bot=ctx.bot,
                    ctx=ctx,
                    guild=ctx.guild,
                    role_id=role_id,
                    module=module,
                    setting=ModuleAcessSetFlag(setting),
                ):
                    await ctx.message.add_reaction(common.COMMAND_SUCCESS_EMOJI)
                    await self._modacs_list(
                        bot=ctx.bot,
                        ctx=ctx,
                        guild=ctx.guild,
                        module=module,
                    )

            case ["clean", module, *arg_flags]:
                await self._modacs_clean(
                    bot=ctx.bot,
                    guild=ctx.guild,
                    module=module,
                    clear_roles=True if ("-r" in arg_flags) else False,
                    yes=True if ("-y" in arg_flags) else False,
                )
                await self._modacs_list(
                    bot=ctx.bot,
                    ctx=ctx,
                    guild=ctx.guild,
                    module=module,
                )

            case _:
                await ctx.reply(
                    "\n".join(
                        [
                            "```",
                            "set which roles can access a module's more sensitive commands",
                            "",
                            "usage:",
                            "   moduleaccess list [ROLE_ID_OR_MODULE]",
                            "      lists all modules and their access,",
                            "      pass a role id or module to filter",
                            "",
                            "   moduleaccess list roles",
                            "      lists all roles ids",
                            "",
                            f"   moduleaccess set ROLE_ID MODULE <{'|'.join([f.value for f in ModuleAcessSetFlag])}>",
                            "      removes `ROLE_ID`'s access to `MODULE`",
                            "",
                            "   moduleaccess clean MODULE [-r] [-y]",
                            "      remove obsolete role ids or modules",
                            "      if `MODULE` is set to '*', all obsolete modules are removed",
                            "      pass '-r' at the end to only remove obsolete modules from `MODULE`",
                            "      pass '-y' at the end to forcefully perform command (here be dragons, duh)",
                            "",
                            "commands which are safe for every role will still be useable even if a role is denied access",
                            "example: denying everybody but specific roles to use the ServerPrefixes module will deny them",
                            "         from managing the server prefix, but the pure `pre` command will still be accessible",
                            "",
                            "this command exclusively uses role ids to mitigate any accidental pushes of notifications",
                            "",
                            "notes:",
                            " - administrators will always be considered privileged by default",
                            " - only administrators can use non-Core modules by default until setup up otherwise",
                            " - running the same command twice will revoke the allow/deny setting",
                            "```",
                        ]
                    )
                )


class ReiXI:
    bot: Bot
    db: db.AbstractBackend
    init_time: datetime
    context: commands.Context

    def __init__(
        self,
        log_dir: Path | None = None,
        db_dir: Path | None = None,
    ) -> None:
        """
        adds logging sink, sets up database

        arguments:
            `log_dir: Path | None = None`
                the path to log output to, defaults to $XDG_RUNTIME_DIR/reixi
            `db_dir: Path | None = None`
                the path to the database, defaults to $XDG_DATA_HOME/reixi
        """

        # setup logging
        figure_res: Result[Path]
        verify_res: Result[bool] = Result[bool](False)

        if isinstance(log_dir, Path):
            if not (verify_res := internals.verify_dir(log_dir)):
                logger.error(f"unable to write to '{log_dir}', not saving logs")

        else:
            if figure_res := internals.figure_log_dir():
                log_dir = figure_res.get()
                verify_res = Result[bool](
                    True
                )  # internals.figure_log_dir() already verfies it anyways

        if verify_res.value is True:
            assert isinstance(log_dir, Path), "unreachable: log_dir is not a Path"
            logger.add(
                log_dir.joinpath("{time}.log"),
                rotation="1 day",
                retention="7 days",
                compression="zip",
                enqueue=True,
                catch=False,
            )

        # setup database
        if db_dir is None:
            if figure_res := internals.figure_db_dir():
                db_dir = figure_res.get()

        elif not (verify_res := internals.verify_dir(db_dir)):
            raise NotADirectoryError(f"unable to write and read to '{db_dir}'")

        assert isinstance(db_dir, Path), "unreachable: db_dir is not a Path"

        # NOTE: change this if you are going to use a different database backend
        self.db: db.AbstractBackend = db.TOMLBackend(db_dir)

        # setup bot
        self.bot: Bot = Bot(
            db=self.db,
            init_time=datetime.now(),
            intents=intents,
            modules=[],
            command_prefix=internals.get_prefix,
            description=common.DESCRIPTION,
            help_command=None,
        )
        # load modules
        uvloop.run(self.bot.add_cog(Core(self.bot)))

        load_success: int = 0
        load_failure: int = 0
        for module in self.db.config.modules:
            try:
                uvloop.run(self.bot.load_extension(module))
                logger.debug(f"loaded module '{module}'")
                load_success += 1

            except Exception as err:
                logger.error(
                    f"unable to load module '{module}'"
                    + "\n"
                    + "\n".join(format_tb(err.__traceback__))
                )
                load_failure += 1

        logger.info(f"loaded {load_success} module(s), {load_failure} failed")
        uvloop.run(self.bot.refresh_module_info())

        logger.info(
            f"reixi {internals.version_string()} initialised"
            + (f", logging output to '{log_dir}'," if verify_res.value is True else "")
            + f" database located at '{self.db.root}'"
        )

    def start(
        self,
        token: str = getenv(common.ENV_TOKEN, ""),
    ):
        """
        starts reixi

        arguments:
            `token: str = getenv(reixi.common.ENV_TOKEN, "")`
                the d*scord bot token to use
        """
        if not isinstance(token, str):
            raise ValueError("token is not a string")
        if len(token) == 0:
            raise ValueError("token cannot be empty")

        self.bot.run(token)


@logger.catch
def main() -> None:
    uvloop.install()

    reixi: ReiXI = ReiXI()
    reixi.start()

"""
reixi.modules.serverprefixes: per-server prefixes
-------------------------------------------------
copyright (c) 2023, mark joshwel <mark@joshwel.co>
SPDX-License-Identifier: AGPL-3.0-or-later
"""

from typing import Final

from discord.ext import commands

from .. import common
from ..internals import Bot, Context, is_user_privileged

NAME: Final[str] = "serverprefixes"


class ServerPrefixes(commands.Cog):
    reixi_god_commands: list[str] = []
    reixi_privileged_commands: list[str] = []

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    @commands.command(name="pre", alias=["prefix"])
    async def prefix(self, ctx: Context, *_args: tuple[str]):
        """displays, sets or resets the server prefix"""
        assert isinstance(ctx.bot, Bot), "unreachable: ctx.Bot is not a reixi.Bot"

        if not ctx.guild:
            return

        if NAME not in await ctx.bot.db.get_server_specific_modules(ctx.guild.id):
            return

        privileged = await is_user_privileged(ctx=ctx, module=NAME)

        match common.fix_args(_args):
            case []:
                await ctx.reply(
                    f'the current prefix is `"{await ctx.bot.db.get_server_specific_prefix(ctx.guild.id)}"`'
                )

            case ["reset"]:
                if not privileged:
                    return
                await ctx.bot.db.set_server_specific_prefix(ctx.guild.id, common.PREFIX)
                await ctx.message.add_reaction(common.COMMAND_SUCCESS_EMOJI)

            case ["set", prefix]:
                if not privileged:
                    return
                await ctx.bot.db.set_server_specific_prefix(ctx.guild.id, prefix)
                await ctx.message.add_reaction(common.COMMAND_SUCCESS_EMOJI)

            case _:
                await ctx.reply(
                    "```\n"
                    + "\n".join(
                        [
                            "displays or manages the server prefix",
                            "",
                            "usage:",
                            "   pre",
                            "      displays the current prefix",
                        ]
                    )
                    + "\n".join(
                        [
                            "\n   pre reset",
                            "      resets the prefix to the default",
                            "   pre set PREFIX",
                            "      sets the prefix to PREFIX",
                        ]
                        if privileged
                        else []
                    )
                    + "\n```"
                )


async def setup(bot: Bot) -> None:
    await bot.add_cog(ServerPrefixes(bot))

"""
reixi.modules.reactionroles: reaction role messages
---------------------------------------------------
copyright (c) 2023, mark joshwel <mark@joshwel.co>
SPDX-License-Identifier: AGPL-3.0-or-later
"""

import asyncio
from datetime import datetime
from traceback import format_tb
from typing import Final

import discord
from discord.ext import commands
from emoji import is_emoji
from loguru import logger

from .. import common
from ..internals import Bot, Context, is_user_privileged

NAME: Final[str] = "reactionroles"


class ReactionRoles(commands.Cog):
    reixi_god_commands: list[str] = []
    reixi_privileged_commands: list[str] = ["rr"]
    background_tasks: list[asyncio.Task] = []

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        super().__init__()

    # FIXME: handle payload to get a member object concretely
    async def reaction_handler(self, remove: bool = False) -> None:
        wait_for = "raw_reaction_remove" if remove else "raw_reaction_add"

        while True:
            payload: discord.RawReactionActionEvent = await self.bot.wait_for(wait_for)

            if payload.guild_id is None:
                continue

            # check if corresponding reaction role message available
            rrs = await self.bot.db.get_reaction_role_messages(
                guild_id=payload.guild_id,
                message_id=payload.message_id,
            )

            # checks
            if len(rrs) == 0:
                continue

            if str(payload.emoji) not in rrs[0].roles:
                continue

            # get role object
            if payload.guild_id is None:
                logger.debug("payload.guild_id is None")
                continue

            guild = self.bot.get_guild(payload.guild_id)
            if guild is None:
                logger.debug(f"could not get payload guild {payload.guild_id}")
                continue

            role = guild.get_role(rrs[0].roles[str(payload.emoji)])
            if role is None:
                logger.debug(
                    f"could not get role {rrs[0].roles[str(payload.emoji)]} from rrs"
                )
                continue

            # get member object
            member: discord.Member
            try:
                member = await guild.fetch_member(payload.user_id)
            except Exception as err:
                logger.error(
                    "could not get member"
                    + "\n"
                    + "\n".join(format_tb(err.__traceback__))
                )
                continue

            # set role
            try:
                if remove:
                    await member.remove_roles(role)
                    logger.debug(f"removed role {role.name} from {member.name}")

                else:
                    await member.add_roles(role)
                    logger.debug(f"added role {role.name} to {member.name}")

            except discord.Forbidden:
                # oh well
                continue

            except Exception as err:
                logger.error(
                    "could not set role"
                    + "\n"
                    + "\n".join(format_tb(err.__traceback__))
                )
                continue

    async def cleanup(self) -> None:
        logger.debug("cleaning up dead reaction role messages")

        # cleanup dead reaction role messages
        dead: int = 0
        alive: int = 0

        for gid, ss in self.bot.db.server_settings.items():
            alive_rrs: list[common.ReactionRoleMessage] = []

            for rr in ss.reactionroles:
                # check if message still exists
                try:
                    guild = await self.bot.fetch_guild(rr.guild_id)  # type: ignore
                    channel = await guild.fetch_channel(rr.channel_id)  # type: ignore
                    message = await channel.fetch_message(rr.message_id)  # type: ignore

                except Exception as err:
                    logger.debug(
                        f"reaction role message {rr.message_id} is dead"
                        # + "\n" + "\n".join(format_tb(err.__traceback__))
                    )
                    dead += 1

                else:
                    alive_rrs.append(rr)
                    alive += 1

            await self.bot.db.set_reaction_role_messages(
                guild_id=gid, reactionroles=alive_rrs
            )

        logger.debug(f"finished cleaning reaction roles, {dead} dead, {alive} alive")

    async def cleanup_handler(self) -> None:
        await self.cleanup()

        while True:
            last_cleanup: datetime = datetime.now()

            while datetime.now() < (
                last_cleanup + common.REACTIONROLE_CLEANING_INTERVAL
            ):
                await asyncio.sleep(1)

            await self.cleanup()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        logger.debug("creating reaction handler tasks")
        self.background_tasks.append(asyncio.create_task(self.reaction_handler()))
        self.background_tasks.append(
            asyncio.create_task(self.reaction_handler(remove=True))
        )
        # TODO: fix this; messages are found dead when they are not
        # logger.debug("creating cleanup handler task")
        # self.background_tasks.append(asyncio.create_task(self.cleanup_handler()))

    async def cog_load(self) -> None:
        if self.bot.is_ready():
            # this will only be called if the cog is loaded after the bot is ready
            # (so usually reloading)
            await self.on_ready()

    async def cog_unload(self) -> None:
        for task in self.background_tasks:
            task.cancel()
        logger.debug(
            f"unloading, cancelled {len(self.background_tasks)} background tasks"
        )
        return await super().cog_unload()

    @commands.command(name="rr", alias=["reactionroles"])
    async def reactionroles(self, ctx: Context, *_args: tuple[str]):
        """create messages that assign roles based on reactions"""
        assert isinstance(ctx.bot, Bot), "unreachable: ctx.Bot is not a reixi.Bot"

        if not ctx.guild:
            return

        if NAME not in await ctx.bot.db.get_server_specific_modules(ctx.guild.id):
            return

        if not await is_user_privileged(ctx=ctx, module=NAME):
            return

        match common.fix_args(_args):
            case ["new", channel, message, *pairing]:
                # handle channel id
                channel_id: int
                if channel == "here":
                    channel_id = ctx.channel.id

                else:
                    if channel.startswith("<#") and channel.endswith(">"):
                        channel = channel.lstrip("<#").rstrip(">")

                    if channel.isdigit():
                        channel_id = int(channel)

                    else:
                        await ctx.reply("invalid channel id")
                        return

                # handle pairings
                pairings: dict[str, int] = {}
                for pair in pairing:
                    match pair.split("="):
                        case [emoji, role_id]:
                            if not is_emoji(emoji):
                                await ctx.reply(f"invalid emoji `{emoji}`")
                                return

                            if not role_id.isdigit():
                                await ctx.reply(f"invalid role id `{role_id}`")
                                return

                            pairings[emoji] = int(role_id)

                        case _:
                            await ctx.reply(f"invalid pairing `{pair}`")
                            return

                # create message in targeted channel id
                target_channel = ctx.bot.get_channel(channel_id)
                if not isinstance(target_channel, discord.TextChannel):
                    await ctx.reply("channel is not a text channel")
                    return

                rr_msg = await target_channel.send(message)
                for emoji in pairings:
                    await rr_msg.add_reaction(emoji)

                # get current list, add and set (update db)
                current_rrs = await ctx.bot.db.get_reaction_role_messages(
                    guild_id=ctx.guild.id
                )
                current_rrs.append(
                    common.ReactionRoleMessage(
                        guild_id=ctx.guild.id,
                        channel_id=rr_msg.channel.id,
                        message_id=rr_msg.id,
                        roles=pairings,
                    )
                )
                await ctx.bot.db.set_reaction_role_messages(
                    guild_id=ctx.guild.id, reactionroles=current_rrs
                )

                await ctx.message.add_reaction(common.COMMAND_SUCCESS_EMOJI)

            case _:
                await ctx.reply(
                    "\n".join(
                        [
                            "```",
                            "create messages that assign roles based on reactions",
                            "",
                            "usage:",
                            "   rr new CHANNEL MESSAGE [PAIRING ...]",
                            "      'here' can be used for `CHANNEL_ID`, you can also use `#<channel>`",
                            '      `MESSAGE` can be any string, but it must be "-quoted if it contains spaces or newlines',
                            "      `PAIRING` must be in the format `<emoji>=ROLE_ID`, multiple can be given",
                            "```",
                        ]
                    )
                )


async def setup(bot: Bot) -> None:
    await bot.add_cog(ReactionRoles(bot))

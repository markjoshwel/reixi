"""
reixi.tomldb: toml db database backend for reixi
------------------------------------------------
copyright (c) 2023, mark joshwel <mark@joshwel.co>
SPDX-License-Identifier: AGPL-3.0-or-later
"""

from abc import ABC, abstractmethod
from pathlib import Path
from traceback import format_tb
from typing import Final

import discord
import tomlkit
from loguru import logger
from tomlkit import items as tomlitems

from . import common


class AbstractBackend(ABC):
    """
    abstract bass class for reixi database backends

    `__init__()` should:
    - take in a db_dir argument of type Path and store it in `self.root`
    - immediately read config stored in db and store it in `self.config` as a `reixi.common.Config` namedtuple
    """

    root: Path
    config: common.Config
    server_settings: dict[int, common.ServerSettings]

    @abstractmethod
    async def reload(
        self,
        dump: bool = True,
        load: bool = True,
    ) -> list[tuple[str, Exception]]:
        """
        reloads the database
        returns a list of error message and exception tuples
        """
        ...

    @abstractmethod
    async def get_server_specific_prefix(
        self,
        guild_id: int,
    ) -> str:
        """returns the server-specific prefix for the bot"""
        ...

    @abstractmethod
    async def set_server_specific_prefix(
        self,
        guild_id: int,
        prefix: str,
    ) -> None:
        """sets the server-specific prefix for the bot"""
        ...

    @abstractmethod
    async def get_server_specific_modules(
        self,
        guild_id: int,
    ) -> list[str]:
        """returns the server-specific modules for the bot"""
        ...

    @abstractmethod
    async def set_server_specific_modules(
        self,
        guild_id: int,
        modules: list[str],
    ) -> None:
        """sets the server-specific modules for the bot"""
        ...

    @abstractmethod
    async def get_module_privileges(
        self,
        guild_id: int,
        module: str,
    ) -> common.ModulePrivileges:
        """
        returns a `reixi.common.ModulePrivileges` object detailing what roles are allowed
        and denied access to a module's commands
        """
        ...

    @abstractmethod
    async def set_module_privileges(
        self,
        guild_id: int,
        module: str,
        privileges: common.ModulePrivileges,
    ) -> None:
        """
        sets a `reixi.common.ModulePrivileges` object to a module
        """
        ...

    @abstractmethod
    async def get_all_privileged_roles(
        self,
        guild_id: int,
    ) -> dict[str, common.ModulePrivileges]:
        """
        returns whether what roles are privileged for a module

        returns a dict of module names to a list of reixi.common.ModulePrivileges
        """
        ...

    @abstractmethod
    async def set_all_privileged_roles(
        self,
        guild_id: int,
        privilege_dict: dict[str, common.ModulePrivileges],
    ) -> None:
        """
        sets a privilege dictionary to a server
        """
        ...

    @abstractmethod
    async def get_reaction_role_messages(
        self,
        guild_id: int,
        message_id: int | None = None,
    ) -> list[common.ReactionRoleMessage]:
        """
        returns a list of reaction role messages pairs for a server
        filterable with message_id
        """
        ...

    @abstractmethod
    async def set_reaction_role_messages(
        self,
        guild_id: int,
        reactionroles: list[common.ReactionRoleMessage],
    ) -> None:
        """
        sets a list of reaction role messages pairs for a server
        """
        ...


class TOMLBackend(AbstractBackend):
    """toml database backend for reixi"""

    def __init__(
        self,
        db_dir: Path,
    ) -> None:
        """initializes the database"""
        self.root = db_dir
        self.server_settings = {}

        # read config
        config_path = self.root.joinpath(".config.toml")
        if config_path.exists() and config_path.is_file():
            logger.debug(f"loading config file at '{config_path}'")

            config_path.read_text(encoding="utf-8")
            config_toml = tomlkit.parse(config_path.read_text(encoding="utf-8"))
            self.config = common.Config(**config_toml)

            # write out
            logger.debug("dumping config file")
            config_path.write_text(
                tomlkit.dumps(tomlkit.item(self.config.model_dump())),
                encoding="utf-8",
            )

        else:
            logger.warning(
                f"config file at '{config_path}' either is missing or not a file"
            )
            if not config_path.exists():
                logger.warning(f"creating a default config file at '{config_path}'")
                config_path.write_text(
                    tomlkit.dumps(tomlkit.item(common.Config().model_dump())),
                    encoding="utf-8",
                )

            self.config = common.Config()

        # load all server settings
        load_success: int = 0
        load_failure: int = 0

        for server_settings_path in self.root.glob("*.toml"):
            if not server_settings_path.is_file():
                continue

            if not server_settings_path.stem.isnumeric():
                continue

            try:
                ss_toml = tomlkit.parse(
                    server_settings_path.read_text(encoding="utf-8")
                )
                ss_guild_id = int(server_settings_path.stem)
                server_settings = common.ServerSettings(**ss_toml)
                self.server_settings[server_settings.guild_id] = server_settings

            except Exception as err:
                logger.error(
                    f"could not load server settings in '{server_settings_path}'"
                    + "\n"
                    + "\n".join(format_tb(err.__traceback__))
                )
                load_failure += 1

            else:
                load_success += 1

        logger.info(
            f"loaded {load_success} server preference(s), {load_failure} failed"
        )

    async def reload(
        self,
        dump: bool = True,
        load: bool = True,
    ) -> list[tuple[str, Exception]]:
        """
        reloads the database
        returns a list of error message and exception tuples
        """

        errors: list[tuple[str, Exception]] = []

        # config
        try:
            if dump:
                config_path = self.root.joinpath(".config.toml")
                config_path.write_text(
                    tomlkit.dumps(tomlkit.item(self.config.model_dump())),
                    encoding="utf-8",
                )
                logger.debug(f"dumped config @ '{config_path}'")

        except Exception as err:
            logger.error(
                f"could not save config file at '{config_path}'"
                + "\n"
                + "\n".join(format_tb(err.__traceback__))
            )
            errors.append((f"could not save config file at '{config_path}'", err))

        else:
            if load:
                try:
                    config_path = self.root.joinpath(".config.toml")
                    config_toml = tomlkit.parse(config_path.read_text(encoding="utf-8"))
                    self.config = common.Config(**config_toml)
                    logger.debug(f"loaded config @ '{config_path}'")

                except Exception as err:
                    logger.error(
                        f"could not load config file at '{config_path}'"
                        + "\n"
                        + "\n".join(format_tb(err.__traceback__))
                    )
                    errors.append(
                        (f"could not load config file at '{config_path}'", err)
                    )

        # server settings
        for guild_id, server_settings in self.server_settings.items():
            try:
                if dump:
                    ss_path = self.root.joinpath(f"{guild_id}.toml")
                    ss_path.write_text(
                        tomlkit.dumps(tomlkit.item(server_settings.model_dump())),
                        encoding="utf-8",
                    )
                    logger.debug(f"dumped server settings for server {guild_id}")

            except Exception as err:
                logger.error(
                    f"could not save server settings for server {guild_id}"
                    + "\n"
                    + "\n".join(format_tb(err.__traceback__))
                )
                errors.append(
                    (f"could not save server settings for server {guild_id}", err)
                )

            else:
                if load:
                    try:
                        ss_path = self.root.joinpath(f"{guild_id}.toml")
                        ss_toml = tomlkit.parse(ss_path.read_text(encoding="utf-8"))
                        self.server_settings[guild_id] = common.ServerSettings(
                            **ss_toml
                        )
                        logger.debug(f"loaded server settings for server {guild_id}")

                    except Exception as err:
                        logger.error(
                            f"could not load server settings for server {guild_id}"
                            + "\n"
                            + "\n".join(format_tb(err.__traceback__))
                        )
                        errors.append(
                            (
                                f"could not load server settings for server {guild_id}",
                                err,
                            )
                        )

        return errors

    async def _save_server_settings(
        self,
        guild_id: int,
    ) -> None:
        """saves the server settings for a guild"""
        try:
            ss_path = self.root.joinpath(f"{guild_id}.toml")
            ss_model = self.server_settings[guild_id]
            ss_path.write_text(
                tomlkit.dumps(tomlkit.item(ss_model.model_dump())), encoding="utf-8"
            )

        except Exception as err:
            logger.error(
                f"could not save server settings for guild {guild_id}\n"
                + "\n".join(format_tb(err.__traceback__))
            )

        else:
            logger.debug(f"saved server settings for guild {guild_id}")

    async def get_server_specific_prefix(
        self,
        guild_id: int,
    ) -> str:
        """returns the server-specific prefix for the bot"""
        ss = self.server_settings.get(guild_id, common.default_server_settings)
        return common.PREFIX if ss.prefix == "" else ss.prefix

    async def set_server_specific_prefix(
        self,
        guild_id: int,
        prefix: str,
    ) -> None:
        """sets the server-specific prefix for the bot"""
        if guild_id not in self.server_settings:
            self.server_settings[guild_id] = common.ServerSettings(guild_id=guild_id)
        self.server_settings[guild_id].prefix = prefix
        await self._save_server_settings(guild_id)

    async def get_server_specific_modules(
        self,
        guild_id: int,
    ) -> list[str]:
        """returns the server-specific modules for the bot"""
        ss = self.server_settings.get(guild_id, common.default_server_settings)
        return ss.modules

    async def set_server_specific_modules(
        self,
        guild_id: int,
        modules: list[str],
    ) -> None:
        """sets the server-specific modules for the bot"""
        modules = [module.lower() for module in modules]
        if guild_id not in self.server_settings:
            self.server_settings[guild_id] = common.ServerSettings(guild_id=guild_id)
        self.server_settings[guild_id].modules = modules
        await self._save_server_settings(guild_id)

    async def get_module_privileges(
        self,
        guild_id: int,
        module: str,
    ) -> common.ModulePrivileges:
        """
        returns a `reixi.common.ModulePrivileges` object detailing what roles are allowed
        and denied access to a module's commands
        """
        return self.server_settings.get(
            guild_id, common.default_server_settings
        ).privileged.get(module, common.ModulePrivileges())

    async def set_module_privileges(
        self,
        guild_id: int,
        module: str,
        privileges: common.ModulePrivileges,
    ) -> None:
        """
        sets a `reixi.common.ModulePrivileges` object to a module
        """
        if guild_id not in self.server_settings:
            self.server_settings[guild_id] = common.ServerSettings(guild_id=guild_id)
        self.server_settings[guild_id].privileged[module] = privileges
        await self._save_server_settings(guild_id)

    async def get_all_privileged_roles(
        self,
        guild_id: int,
    ) -> dict[str, common.ModulePrivileges]:
        """
        returns whether what roles are privileged for a module

        returns a dict of module names to a list of reixi.common.ModulePrivileges
        """
        return self.server_settings.get(
            guild_id, common.default_server_settings
        ).privileged

    async def set_all_privileged_roles(
        self,
        guild_id: int,
        privilege_dict: dict[str, common.ModulePrivileges],
    ) -> None:
        """
        sets a privilege dictionary to a server
        """
        if guild_id not in self.server_settings:
            self.server_settings[guild_id] = common.ServerSettings(guild_id=guild_id)
        self.server_settings[guild_id].privileged = privilege_dict
        await self._save_server_settings(guild_id)

    async def get_reaction_role_messages(
        self,
        guild_id: int,
        message_id: int | None = None,
    ) -> list[common.ReactionRoleMessage]:
        """
        returns a list of reaction role messages pairs for a server
        filterable with message_id
        """
        rrs = self.server_settings.get(
            guild_id, common.default_server_settings
        ).reactionroles

        if isinstance(message_id, int):
            for rr in rrs:
                if rr.message_id == message_id:
                    return [rr]
        return rrs

    async def set_reaction_role_messages(
        self,
        guild_id: int,
        reactionroles: list[common.ReactionRoleMessage],
    ) -> None:
        """
        sets a list of reaction role messages pairs for a server
        """
        if guild_id not in self.server_settings:
            self.server_settings[guild_id] = common.ServerSettings(guild_id=guild_id)
        self.server_settings[guild_id].reactionroles = reactionroles
        logger.debug(f"saving reaction role messages")
        await self._save_server_settings(guild_id)

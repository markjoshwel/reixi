"""
reixi.common: common data structures, constants and functions for reixi
-----------------------------------------------------------------------
copyright (c) 2023, mark joshwel <mark@joshwel.co>
SPDX-License-Identifier: AGPL-3.0-or-later
"""

from datetime import timedelta
from typing import Final, Generic, NamedTuple, TypeVar

from pydantic import BaseModel

ResultType = TypeVar("ResultType")


VERSION: Final[tuple[int, int, int]] = (6, 0, 0)
VERSION_SUFFIX: Final[str] = ""

NAME: str = "reixi"
PREFIX: str = "rx "
DESCRIPTION: str = "utility-first general-purpose d*scord bot"
SOURCE_CODE: str = "https://github.com/markjoshwel/reixi"

ENV_TOKEN: str = "REIXI_TOKEN"
ENV_LOG_DIR: str = "REIXI_LOG_DIR"
ENV_DB_DIR: str = "REIXI_DB_DIR"

# no one will use reixi anyways, let me enjoy my inside joke
# COMMAND_SUCCESS_EMOJI: str = "👍"
COMMAND_SUCCESS_EMOJI: str = "🍞"

REACTIONROLE_CLEANING_INTERVAL: timedelta = timedelta(minutes=30)


class Config(BaseModel):
    gods: list[int] = []
    modules: list[str] = [
        "reixi.builtins.serverprefixes",
        "reixi.builtins.reactionroles",
    ]


class ModulePrivileges(BaseModel):
    allow: list[int] = []
    deny: list[int] = []


class ReactionRoleMessage(BaseModel):
    guild_id: int
    channel_id: int
    message_id: int
    roles: dict[str, int] = {
        # emoji: role_id
    }


class ServerSettings(BaseModel):
    guild_id: int
    prefix: str = ""
    reactionroles: list[ReactionRoleMessage] = []
    modules: list[str] = ["Core"]
    privileged: dict[str, ModulePrivileges] = {
        # module_name: ModulePrivileges
    }


default_server_settings = ServerSettings(guild_id=0)


def fix_args(args: tuple[tuple[str], ...]) -> list[str]:
    """fixes the args tuple that discord.py passes to commands"""
    return ["".join(arg) for arg in args]


class Result(NamedTuple, Generic[ResultType]):
    """
    typing.NamedTuple representing a result for safe value retrieval

    arguments
        `value: ResultType`
            value to return or fallback value if erroneous
        `error: BaseException | None = None`
            exception if any

    methods:
        `def __bool__(self) -> bool: ...`
        `def get(self) -> ResultType: ...`
        `def cry(self, string: bool = False) -> str: ...`

    example:
        ```
        def some_operation(path) -> Result[str]:
            try:
                file = open(path)
                contents = file.read()

            except Exception as err:
                # must pass a default value
                return Result[str]("", error=err)

            else:
                return Result[str](contents)

        # call function and handle result
        result = some_operation("some_file.txt")

        if not result:  # check if the result is erroneous
            # .cry() raises the exception
            # (or returns it as a string error message using string=True)
            result.cry()
            ...

        else:
            # .get() raises exception or returns value,
            # but since we checked for errors this is safe
            print(result.get())
        ```
    """

    value: ResultType
    error: BaseException | None = None

    def __bool__(self) -> bool:
        """method that returns True if self.error is not None"""
        return self.error is None

    def cry(self, string: bool = False) -> str:
        """
        method that raises self.error if is an instance of BaseException,
        returns self.error if is an instance of str, or returns an empty string if
        self.error is None

        arguments
            string: bool = False
                if self.error is an Exception, returns it as a string error message
        """

        if isinstance(self.error, BaseException):
            if string:
                message = f"{self.error}"
                name = self.error.__class__.__name__
                return f"{message} ({name})" if (message != "") else name

            raise self.error

        if isinstance(self.error, str):
            return self.error

        return ""

    def get(self) -> ResultType:
        """method that returns self.value if Result is non-erroneous else raises error"""
        if isinstance(self.error, BaseException):
            raise self.error
        return self.value

# reixi

utilitarian-first general-purpose d*scord bot that doesn't stand in your way

- [running reixi](#running-reixi)
- [using reixi](#using-reixi)
  - [environment variables](#environment-variables)
  - [configuration file](#configuration-file)
- [developing for reixi](#developing-for-reixi)
  - [modules](#modules)
  - [database backends](#database-backends)
- [licence](#licence)

## running reixi

prerequisites:

- python 3.11+
- [poetry](https://python-poetry.org/)

clone the repository before anything else, and enter it:

```text
git clone https://github.com/markjoshwel/reixi
cd reixi
```

then install dependencies and run reixi:

```text
poetry install
REIXI_TOKEN="" poetry run reixi
```

devbox user? do the following instead:

```text
git clone https://github.com/markjoshwel/reixi
cd reixi
REIXI_TOKEN="" devbox run reixi
```

to see what other environment variables you can set, see [environment variables](#environment-variables).

## using reixi

- when generating an invite link, ensure the `bot` scope is selected, and that the `Administrator` permission is selected.
- ensure reixi's role is above the roles you want it to manage.
- the default prefix is `rx `, but this can be changed per-server with `rx pre`, or globally by editing [`reixi/common.py`](reixi/common.py).
- all modules are disabled per-server by default. enable them with `rx module`

### environment variables

- `REIXI_TOKEN`  
  the discord bot token, required

- `REIXI_LOG_DIR`  
  where to store logs in

  if not specified, the following directories are tried in order:
  1. `XDG_RUNTIME_DIR/reixi`
  2. `PWD/logs`

- `REIXI_DB_PATH`  
  where to store database files and the config file

  if not specified, the following directories are tried in order:
  1. `XDG_DATA_HOME/reixi`
  2. `~/.local/share/reixi`
  3. `PWD/db`

### configuration file

the configuration file is a TOML file located at `$REIXI_DB_PATH/.config.toml`.

```toml
# user ids of who can use reixi god commands
# usually justthe bot owner
gods = []

# list of modules to load
# append to this list to third-party modules
# the strings should follow python module import syntax
modules = [
    "reixi.builtins.serverprefixes",
    "reixi.builtins.reactionroles",
]
```

## developing for reixi

reixi is fully type-annotated, so use mypy to check for type errors.

### modules

reixi modules are [`discord.ext.commands.Cog`](https://discordpy.readthedocs.io/en/stable/ext/commands/cogs.html).

```py
from discord.ext import commands

# this should be a lowercase version of the module class name
NAME = "testmodule"  


class TestModule(commands.Cog):
    # these two lists aren't required
    # unless you want to hide them from the help command
    reixi_god_commands: list[str] = []         # commands that only bot owners/gods can use
    reixi_privileged_commands: list[str] = []  # commands that only server owners/admins can use

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command()
    async def test(self, ctx: commands.Context) -> None:
        # check if module is server-disabled
        if not await self.bot.db.get_module_enabled(ctx.guild.id, NAME):
            return

        await ctx.send("test!")


async def setup(bot: Bot) -> None:
    await bot.add_cog(ReactionRoles(bot))
```

you can access the database backend via `bot.db`.

- config is stored in `bot.db.config` and is of type `reixi.common.Config`.

- server settings are stored in `bot.db.server_settings` and is of type `dict[int, reixi.common.ServerSettings]`.

  access a guild's settings by using its id as a key when indexing the dictionary.

- see available db methods by looking at `reixi.db.AbstractBackend`.

place the module somewhere `reixi/reixi.py` can find them, or install them as a package.  
then, add them into the modules list in your reixi config.

### database backends

reixi saves data as TOML files, but under an abstraction layer.

write your own database backend by implementing and extending the abstract base class
`reixi.db.AbstractBackend`, and then swap it out with the TOML backend by modifying
`reixi/reixi.py`. (ctrl+f and `NOTE` should help you find the line!)

## licence

reixi is licenced under the GNU Affero General Public Licence v3.0 or later.  
for more information, please refer to [LICENCE.md](LICENCE.md), or the [GNU website](https://www.gnu.org/licenses/agpl.html).

if you run reixi or a modified version of it, you **must** provide the source code to the users of the bot.  
this is a requirement of the Affero General Public Licence licence.

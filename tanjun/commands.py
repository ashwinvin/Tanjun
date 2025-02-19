# -*- coding: utf-8 -*-
# cython: language_level=3
# BSD 3-Clause License
#
# Copyright (c) 2020-2021, Faster Speeding
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from __future__ import annotations

__all__: list[str] = [
    "AnyMessageCommandT",
    "CommandCallbackSigT",
    "ConverterSig",
    "as_message_command",
    "as_message_command_group",
    "as_slash_command",
    "slash_command_group",
    "MessageCommand",
    "MessageCommandGroup",
    "PartialCommand",
    "BaseSlashCommand",
    "SlashCommand",
    "SlashCommandGroup",
    "with_str_slash_option",
    "with_int_slash_option",
    "with_bool_slash_option",
    "with_role_slash_option",
    "with_user_slash_option",
    "with_member_slash_option",
    "with_channel_slash_option",
    "with_mentionable_slash_option",
]

import copy
import logging
import re
import types
import typing
from collections import abc as collections

import hikari

from . import _backoff as backoff
from . import abc
from . import components
from . import conversion
from . import errors
from . import hooks as hooks_
from . import injecting
from . import utilities

if typing.TYPE_CHECKING:

    from hikari.api import special_endpoints as special_endpoints_api

    from . import parsing

    _MessageCommandT = typing.TypeVar("_MessageCommandT", bound="MessageCommand[typing.Any]")
    _MessageCommandGroupT = typing.TypeVar("_MessageCommandGroupT", bound="MessageCommandGroup[typing.Any]")
    _PartialCommandT = typing.TypeVar("_PartialCommandT", bound="PartialCommand[typing.Any]")
    _BaseSlashCommandT = typing.TypeVar("_BaseSlashCommandT", bound="BaseSlashCommand")
    _SlashCommandT = typing.TypeVar("_SlashCommandT", bound="SlashCommand[typing.Any]")
    _SlashCommandGroupT = typing.TypeVar("_SlashCommandGroupT", bound="SlashCommandGroup")


AnyMessageCommandT = typing.TypeVar("AnyMessageCommandT", bound=abc.MessageCommand)
CommandCallbackSigT = typing.TypeVar("CommandCallbackSigT", bound=abc.CommandCallbackSig)
ConverterSig = collections.Callable[..., abc.MaybeAwaitableT[typing.Any]]
"""Type hint of a converter used within a parser instance."""
_EMPTY_DICT: typing.Final[dict[typing.Any, typing.Any]] = {}
_EMPTY_HOOKS: typing.Final[hooks_.Hooks[typing.Any]] = hooks_.Hooks()
_EMPTY_LIST: typing.Final[list[typing.Any]] = []
_EMPTY_RESOLVED: typing.Final[hikari.ResolvedOptionData] = hikari.ResolvedOptionData(
    users=_EMPTY_DICT, members=_EMPTY_DICT, roles=_EMPTY_DICT, channels=_EMPTY_DICT
)
_LOGGER: typing.Final[logging.Logger] = logging.getLogger("hikari.tanjun.commands")


class _LoadableInjector(injecting.InjectableCheck):
    __slots__ = ()

    def make_method_type(self, component: abc.Component, /) -> None:
        if isinstance(self.callback, types.MethodType):
            raise ValueError("Callback is already a method type")

        self.callback = types.MethodType(self.callback, component)  # type: ignore[assignment]
        self.is_async = None
        self._needs_injector = injecting.check_injecting(self.callback)


class PartialCommand(
    injecting.Injectable,
    abc.ExecutableCommand[abc.ContextT],
):
    """Base class for the standard ExecutableCommand implementations."""

    __slots__ = ("_checks", "_component", "_hooks", "_injector", "_metadata")

    def __init__(
        self,
        *,
        checks: typing.Optional[collections.Iterable[abc.CheckSig]] = None,
        hooks: typing.Optional[abc.Hooks[abc.ContextT]] = None,
        metadata: typing.Optional[collections.MutableMapping[typing.Any, typing.Any]] = None,
    ) -> None:
        self._checks: set[injecting.InjectableCheck] = (
            {injecting.InjectableCheck(check) for check in checks} if checks else set()
        )
        self._component: typing.Optional[abc.Component] = None
        self._hooks = hooks
        self._injector: typing.Optional[injecting.InjectorClient] = None
        self._metadata = dict(metadata) if metadata else {}

    @property
    def checks(self) -> collections.Set[abc.CheckSig]:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        return {check.callback for check in self._checks}

    @property
    def component(self) -> typing.Optional[abc.Component]:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        return self._component

    @property
    def hooks(self) -> typing.Optional[abc.Hooks[abc.ContextT]]:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        return self._hooks

    @property
    def metadata(self) -> collections.MutableMapping[typing.Any, typing.Any]:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        return self._metadata

    @property
    def needs_injector(self) -> bool:
        # <<inherited docstring from tanjun.injecting.Injectable>>.
        return any(check.needs_injector for check in self._checks)

    def copy(self: _PartialCommandT, *, _new: bool = True) -> _PartialCommandT:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        if not _new:
            self._checks = {check.copy() for check in self._checks}
            self._hooks = self._hooks.copy() if self._hooks else None
            self._metadata = self._metadata.copy()
            return self

        return copy.copy(self).copy(_new=False)

    def set_hooks(self: _PartialCommandT, hooks: typing.Optional[abc.Hooks[abc.ContextT]], /) -> _PartialCommandT:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        self._hooks = hooks
        return self

    def add_check(self: _PartialCommandT, check: abc.CheckSig, /) -> _PartialCommandT:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        self._checks.add(injecting.InjectableCheck(check, injector=self._injector))
        return self

    def remove_check(self, check: abc.CheckSig, /) -> None:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        self._checks.remove(check)  # type: ignore[arg-type]

    def with_check(self, check: abc.CheckSigT, /) -> abc.CheckSigT:
        self._checks.add(_LoadableInjector(check, injector=self._injector))
        return check

    def set_injector(self, client: injecting.InjectorClient, /) -> None:
        # <<inherited docstring from tanjun.injecting.Injectable>>.
        if self._injector:
            raise RuntimeError("Injector already set")

        self._injector = client

        for check in self._checks:
            check.set_injector(client)

    def bind_client(self, client: abc.Client, /) -> None:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        pass

    def bind_component(self, component: abc.Component, /) -> None:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        self._component = component

    def load_into_component(self: _PartialCommandT, component: abc.Component, /) -> typing.Optional[_PartialCommandT]:
        for check in self._checks:
            if isinstance(check, _LoadableInjector):
                check.make_method_type(component)

        return None


_MEMBER_OPTION_TYPES: typing.Final[frozenset[hikari.OptionType]] = frozenset(
    (hikari.OptionType.USER, hikari.OptionType.MENTIONABLE)
)
_OBJECT_OPTION_TYPES: typing.Final[frozenset[hikari.OptionType]] = frozenset(
    (
        hikari.OptionType.USER,
        hikari.OptionType.CHANNEL,
        hikari.OptionType.MENTIONABLE,
    )
)
_SUB_COMMAND_OPTIONS_TYPES: typing.Final[frozenset[hikari.OptionType]] = frozenset(
    (
        hikari.OptionType.SUB_COMMAND,
        hikari.OptionType.SUB_COMMAND_GROUP,
    )
)
_SCOMMAND_NAME_REG: typing.Final[re.Pattern[str]] = re.compile(r"^[a-z0-9_-]{1,32}$")


def slash_command_group(
    name: str,
    description: str,
    /,
    *,
    command_id: typing.Optional[hikari.SnowflakeishOr[hikari.Command]] = None,
    default_permission: bool = True,
    default_to_ephemeral: bool = False,
    is_global: bool = True,
) -> SlashCommandGroup:
    """Create a slash command group.

    Examples
    --------
    Sub-commands can be added to the created slash command object through
    the following decorator based approach:
    ```python
    help_group = tanjun.slash_command_group("help", "get help")

    @help_group.with_command
    @tanjun.with_str_slash_option("commad_name", "command name")
    @tanjun.as_slash_command("command", "Get help with a command")
    async def help_command_command(ctx: tanjun.abc.SlashContext, command_name: str) -> None:
        ...

    @help_group.with_command
    @tanjun.as_slash_command("me", "help me")
    async def help_me_command(ctx: tanjun.abc.SlashContext) -> None:
        ...

    component = tanjun.Component().add_slash_command_command(help_group)
    ```

    Notes
    -----
    * Unlike message command grups, slash command groups cannot
      be callable functions themselves.
    * Under the standard implementation, `is_global` is used to determine whether
      the command should be bulk set by `tanjun.Client.set_global_commands`
      or when `set_global_commands` is True

    Parameters
    ----------
    name : str
        The name of the command group.
    description : str
        The description of the command group.

    Other Parameters
    ----------------
    command_id : typing.Optional[hikari.snowflakes.SnowflakeishOr[hikari.Command]]
        Object or ID of the command the group tracks.

        This is useful when bulk updating the commands as if the ID isn't
        specified then any previously set permissions may be lost (i.e. if the
        command's name is changed).
    default_permission : bool
        Whether this command can be accessed without set permissions.

        Defaults to `True`, meaning that users can access the command by default.
    default_to_ephemeral : bool
        Whether this command's responses should default to ephemeral unless flags
        are set to override this. This defaults to `False`.
    is_global : bool
        Whether this command is a global command. Defaults to `True`.

    Returns
    -------
    SlashCommandGroup
        The command group.
    """
    return SlashCommandGroup(
        name,
        description,
        command_id=command_id,
        default_permission=default_permission,
        default_to_ephemeral=default_to_ephemeral,
        is_global=is_global,
    )


def as_slash_command(
    name: str,
    description: str,
    /,
    *,
    command_id: typing.Optional[hikari.SnowflakeishOr[hikari.Command]] = None,
    default_permission: bool = True,
    default_to_ephemeral: bool = False,
    is_global: bool = True,
    sort_options: bool = True,
) -> collections.Callable[[CommandCallbackSigT], SlashCommand[CommandCallbackSigT]]:
    r"""Build a `SlashCommand` by decorating a function.

    .. note::
        Under the standard implementation, `is_global` is used to determine whether
        the command should be bulk set by `tanjun.Client.set_global_commands`
        or when `set_global_commands` is True

    .. warning::
        `command_id` and `default_permission` are ignored for commands within
        slash command groups.

    Examples
    --------
    ```py
    @as_slash_command("ping", "Get the bot's latency")
    async def ping_command(self, ctx: tanjun.abc.SlashContext) -> None:
        start_time = time.perf_counter()
        await ctx.rest.fetch_my_user()
        time_taken = (time.perf_counter() - start_time) * 1_000
        await ctx.respond(f"PONG\n - REST: {time_taken:.0f}mss")
    ```

    Parameters
    ----------
    name : str
        The command's name. This should match the regex `^[a-z0-9_-]{1,32}$`.
    description : str
        The command's description.
        This should be inclusively between 1-100 characters in length.

    Other Parameters
    ----------------
    command_id : typing.Optional[hikari.snowflakes.SnowflakeishOr[hikari.interactions.commands.Command]]
        ID of the global command this should be tracking.

        This is useful when bulk updating the commands as if the ID isn't
        specified then any previously set permissions may be lost (i.e. if the
        command's name is changed).
    default_permission : bool
        Whether this command can be accessed without set permissions.

        Defaults to `True`, meaning that users can access the command by default.
    default_to_ephemeral : bool
        Whether this command's responses should default to ephemeral unless flags
        are set to override this. This defaults to `False`.
    is_global : bool
        Whether this command is a global command. Defaults to `True`.
    sort_options : bool
        Whether this command should sort its set options based on whether
        they're required.

        If this is `True` then the options are re-sorted to meet the requirement
        from Discord that required command options be listed before optional
        ones.

    Returns
    -------
    collections.abc.Callable[[CommandCallbackSigT], SlashCommand[CommandCallbackSigT]]
        The decorator callback used to build the command to a `SlashCommand`.
    """
    return lambda c: SlashCommand(
        c,
        name,
        description,
        command_id=command_id,
        default_to_ephemeral=default_to_ephemeral,
        is_global=is_global,
        sort_options=sort_options,
    )


_UNDEFINED_DEFAULT = object()


def with_str_slash_option(
    name: str,
    description: str,
    /,
    *,
    choices: typing.Optional[collections.Iterable[typing.Union[tuple[str, str], str]]] = None,
    converters: typing.Union[collections.Sequence[ConverterSig], ConverterSig] = (),
    default: typing.Any = _UNDEFINED_DEFAULT,
) -> collections.Callable[[_SlashCommandT], _SlashCommandT]:
    """Add a string option to a slash command.

    .. note::
        As a shorthand, `choices` also supports passing strings in place of
        tuples each string will be used as both the choice's name and value
        (with the name being capitalised).

    Examples
    --------
    ```py
    @with_str_slash_option("name", "A name.")
    @as_slash_command("command", "A command")
    async def command(self, ctx: tanjun.abc.SlashContext, name: str) -> None:
        ...
    ```

    Parameters
    ----------
    name : str
        The option's name. This should match the regex `^[a-z0-9_-]{1,32}$`.
    description : str
        The option's description.
        This should be inclusively between 1-100 characters in length.

    Other Parameters
    ----------------
    choices : typing.Optional[collections.Iterable[typing.Union[tuple[str, str], str]]]
        The option's choices.

        This may be either one or multiple `tuple[opton_name, option_value]`
        Where both option_name and option_value should be strings of up to 100
        characters.
    converters : typing.Union[collections.Sequence[ConverterSig], ConverterSig]
        The option's converters.

        This may be either one or multiple `ConverterSig` callbacks used to
        convert the option's value to the final form.
        If no converters are provided then the raw value will be passed.

        Only the first converter to pass will be used.
    default : typing.Any
        The option's default value.
        If this is left as undefined then this option will be required.

    Returns
    -------
    collections.abc.Callable[[_SlashCommandT], _SlashCommandT]
        Decorator callback which adds the option to the command.
    """
    new_choices: collections.Iterable[tuple[str, str]] = ()
    if choices is not None:
        new_choices = [choice if isinstance(choice, tuple) else (choice.capitalize(), choice) for choice in choices]

    return lambda c: c.add_option(
        name, description, hikari.OptionType.STRING, default=default, choices=new_choices, converters=converters
    )


def with_int_slash_option(
    name: str,
    description: str,
    /,
    *,
    choices: typing.Optional[collections.Iterable[tuple[str, int]]] = None,
    converters: typing.Union[collections.Collection[ConverterSig], ConverterSig] = (),
    default: typing.Any = _UNDEFINED_DEFAULT,
) -> collections.Callable[[_SlashCommandT], _SlashCommandT]:
    """Add an integer option to a slash command.

    Examples
    --------
    ```py
    @with_int_slash_option("int_value", "Int value.")
    @as_slash_command("command", "A command")
    async def command(self, ctx: tanjun.abc.SlashContext, int_value: int) -> None:
        ...
    ```

    Parameters
    ----------
    name : str
        The option's name. This should match the regex `^[a-z0-9_-]{1,32}$`.
    description : str
        The option's description.
        This should be inclusively between 1-100 characters in length.

    Other Parameters
    ----------------
    choices : typing.Optional[collections.Iterable[typing.Union[tuple[str, int]]]]
        The option's choices.

        This may be either one or multiple `tuple[opton_name, option_value]`
        where option_name should be a string of up to 100 characters and
        option_value should be an integer.
    converters : typing.Union[collections.Sequence[ConverterSig], ConverterSig, None]
        The option's converters.

        This may be either one or multiple `ConverterSig` callbacks used to
        convert the option's value to the final form.
        If no converters are provided then the raw value will be passed.

        Only the first converter to pass will be used.
    default : typing.Any
        The option's default value.
        If this is left as undefined then this option will be required.

    Returns
    -------
    collections.abc.Callable[[_SlashCommandT], _SlashCommandT]
        Decorator callback which adds the option to the command.
    """
    return lambda c: c.add_option(
        name, description, hikari.OptionType.INTEGER, default=default, choices=choices, converters=converters
    )


def with_bool_slash_option(
    name: str,
    description: str,
    /,
    *,
    default: typing.Any = _UNDEFINED_DEFAULT,
) -> collections.Callable[[_SlashCommandT], _SlashCommandT]:
    """Add a boolean option to a slash command.

    Examples
    --------
    ```py
    @with_bool_slash_option("flag", "Whether this flag should be enabled.", default=False)
    @as_slash_command("command", "A command")
    async def command(self, ctx: tanjun.abc.SlashContext, flag: bool) -> None:
        ...
    ```

    Parameters
    ----------
    name : str
        The option's name. This should match the regex `^[a-z0-9_-]{1,32}$`.
    description : str
        The option's description.
        This should be inclusively between 1-100 characters in length.

    Other Parameters
    ----------------
    default : typing.Any
        The option's default value.
        If this is left as undefined then this option will be required.

    Returns
    -------
    collections.abc.Callable[[_SlashCommandT], _SlashCommandT]
        Decorator callback which adds the option to the command.
    """
    return lambda c: c.add_option(name, description, hikari.OptionType.BOOLEAN, default=default)


def with_user_slash_option(
    name: str,
    description: str,
    /,
    *,
    default: typing.Any = _UNDEFINED_DEFAULT,
) -> collections.Callable[[_SlashCommandT], _SlashCommandT]:
    """Add a user option to a slash command.

    .. note::
        This may result in `hikari.interactions.commands.InteractionMember` or
        `hikari.users.User` if the user isn't in the current guild or if this
        command was executed in a DM channel.

    Examples
    --------
    ```py
    @with_channel_slash_option("user", "user to target.")
    @as_slash_command("command", "A command")
    async def command(self, ctx: tanjun.abc.SlashContext, user: Union[InteractionMember, User]) -> None:
        ...
    ```

    Parameters
    ----------
    name : str
        The option's name. This should match the regex `^[a-z0-9_-]{1,32}$`.
    description : str
        The option's description.
        This should be inclusively between 1-100 characters in length.

    Other Parameters
    ----------------
    default : typing.Any
        The option's default value.
        If this is left as undefined then this option will be required.

    Returns
    -------
    collections.abc.Callable[[_SlashCommandT], _SlashCommandT]
        Decorator callback which adds the option to the command.
    """
    return lambda c: c.add_option(name, description, hikari.OptionType.USER, default=default)


def with_member_slash_option(
    name: str,
    description: str,
    /,
    *,
    default: typing.Any = _UNDEFINED_DEFAULT,
) -> collections.Callable[[_SlashCommandT], _SlashCommandT]:
    """Add a member option to a slash command.

    .. note::
        This will always result in `hikari.interactions.commands.InteractionMember`.

    Examples
    --------
    ```py
    @with_channel_slash_option("member", "member to target.")
    @as_slash_command("command", "A command")
    async def command(self, ctx: tanjun.abc.SlashContext, member: hikari.InteractionMember) -> None:
        ...
    ```

    Parameters
    ----------
    name : str
        The option's name. This should match the regex `^[a-z0-9_-]{1,32}$`.
    description : str
        The option's description.
        This should be inclusively between 1-100 characters in length.

    Other Parameters
    ----------------
    default : typing.Any
        The option's default value.
        If this is left as undefined then this option will be required.

    Returns
    -------
    collections.abc.Callable[[_SlashCommandT], _SlashCommandT]
        Decorator callback which adds the option to the command.
    """
    return lambda c: c.add_option(name, description, hikari.OptionType.USER, default=default, only_member=True)


def with_channel_slash_option(
    name: str,
    description: str,
    /,
    *,
    default: typing.Any = _UNDEFINED_DEFAULT,
) -> collections.Callable[[_SlashCommandT], _SlashCommandT]:
    """Add a channel option to a slash command.

    .. note::
        This will always result in `hikari.interactions.commands.InteractionChannel`.

    Examples
    --------
    ```py
    @with_channel_slash_option("channel", "channel to target.")
    @as_slash_command("command", "A command")
    async def command(self, ctx: tanjun.abc.SlashContext, channel: hikari.InteractionChannel) -> None:
        ...
    ```

    Parameters
    ----------
    name : str
        The option's name. This should match the regex `^[a-z0-9_-]{1,32}$`.
    description : str
        The option's description.
        This should be inclusively between 1-100 characters in length.

    Parameters
    ----------
    default : typing.Any
        The option's default value.
        If this is left as undefined then this option will be required.

    Returns
    -------
    collections.abc.Callable[[_SlashCommandT], _SlashCommandT]
        Decorator callback which adds the option to the command.
    """
    return lambda c: c.add_option(name, description, hikari.OptionType.CHANNEL, default=default)


def with_role_slash_option(
    name: str,
    description: str,
    /,
    *,
    default: typing.Any = _UNDEFINED_DEFAULT,
) -> collections.Callable[[_SlashCommandT], _SlashCommandT]:
    """Add a role option to a slash command.

    Examples
    --------
    ```py
    @with_role_slash_option("role", "Role to target.")
    @as_slash_command("command", "A command")
    async def command(self, ctx: tanjun.abc.SlashContext, role: hikari.Role) -> None:
        ...
    ```

    Parameters
    ----------
    name : str
        The option's name. This should match the regex `^[a-z0-9_-]{1,32}$`.
    description : str
        The option's description.
        This should be inclusively between 1-100 characters in length.

    Other Parameters
    ----------------
    default : typing.Any
        The option's default value.
        If this is left as undefined then this option will be required.

    Returns
    -------
    collections.abc.Callable[[_SlashCommandT], _SlashCommandT]
        Decorator callback which adds the option to the command.
    """
    return lambda c: c.add_option(name, description, hikari.OptionType.ROLE, default=default)


def with_mentionable_slash_option(
    name: str,
    description: str,
    /,
    *,
    default: typing.Any = _UNDEFINED_DEFAULT,
) -> collections.Callable[[_SlashCommandT], _SlashCommandT]:
    """Add a mentionable option to a slash command.

    .. note::
        This may target roles, guild members or users and results in
        `Union[hikari.User, hikari.InteractionMember, hikari.Role]`.

    Examples
    --------
    ```py
    @with_mentionable_slash_option("mentionable", "Mentionable entity to target.")
    @as_slash_command("command", "A command")
    async def command(self, ctx: tanjun.abc.SlashContext, mentionable: [Role, InteractionMember, User]) -> None:
        ...
    ```

    Parameters
    ----------
    name : str
        The option's name. This should match the regex `^[a-z0-9_-]{1,32}$`.
    description : str
        The option's description.
        This should be inclusively between 1-100 characters in length.

    Other Parameters
    ----------------
    default : typing.Any
        The option's default value.
        If this is left as undefined then this option will be required.

    Returns
    -------
    collections.abc.Callable[[_SlashCommandT], _SlashCommandT]
        Decorator callback which adds the option to the command.
    """
    return lambda c: c.add_option(name, description, hikari.OptionType.MENTIONABLE, default=default)


def _convert_to_injectable(converter: ConverterSig) -> injecting.InjectableConverter[typing.Any]:
    if isinstance(converter, injecting.InjectableConverter):
        return typing.cast("injecting.InjectableConverter[typing.Any]", converter)

    return injecting.InjectableConverter(conversion.override_type(converter))


class _TrackedOption(injecting.Injectable):
    __slots__ = ("converters", "default", "is_only_member", "name", "type")

    def __init__(
        self,
        name: str,
        option_type: int,
        converters: list[injecting.InjectableConverter[typing.Any]],
        only_member: bool,
        default: typing.Any = _UNDEFINED_DEFAULT,
    ) -> None:
        self.converters = converters
        self.default = default
        self.is_only_member = only_member
        self.name = name
        self.type = option_type

    @property
    def needs_injector(self) -> bool:
        return any(converter.needs_injector for converter in self.converters)

    async def convert(self, ctx: abc.SlashContext, value: typing.Any, /) -> typing.Any:
        if not self.converters:
            return value

        exceptions: list[ValueError] = []
        for converter in self.converters:
            try:
                return await converter(value, ctx)

            except ValueError as exc:
                exceptions.append(exc)

        raise errors.ConversionError(self.name, f"Couldn't convert {self.type} '{self.name}'", errors=exceptions)

    def set_injector(self, client: injecting.InjectorClient, /) -> None:
        super().set_injector(client)
        for converter in self.converters:
            converter.set_injector(client)


_CommandBuilderT = typing.TypeVar("_CommandBuilderT", bound="_CommandBuilder")


class _CommandBuilder(hikari.impl.CommandBuilder):
    __slots__ = ("_has_been_sorted", "_sort_options")

    def __init__(
        self,
        name: str,
        description: str,
        sort_options: bool,
        *,
        id: hikari.UndefinedOr[hikari.Snowflake] = hikari.UNDEFINED,  # noqa: A002
    ) -> None:
        super().__init__(name, description, id=id)  # type: ignore
        self._has_been_sorted = True
        self._sort_options = sort_options

    def add_option(self: _CommandBuilderT, option: hikari.CommandOption) -> _CommandBuilderT:
        if self._options:
            self._has_been_sorted = False

        super().add_option(option)
        return self

    def build(self, entity_factory: hikari.api.EntityFactory, /) -> dict[str, typing.Any]:
        if self._sort_options and not self._has_been_sorted:
            required: list[hikari.CommandOption] = []
            not_required: list[hikari.CommandOption] = []
            for option in self._options:
                if option.is_required:
                    required.append(option)
                else:
                    not_required.append(option)

            self._options = [*required, *not_required]
            self._has_been_sorted = True

        return super().build(entity_factory)

    def copy(self) -> _CommandBuilder:  # TODO: can we just del _CommandBuilder.__copy__ to go back to the default?
        builder = _CommandBuilder(self.name, self.description, self._sort_options, id=self.id)

        for option in self._options:
            builder.add_option(option)

        return builder


class BaseSlashCommand(PartialCommand[abc.SlashContext], abc.BaseSlashCommand):
    __slots__ = ("_command_id", "_defaults_to_ephemeral", "_description", "_is_global", "_name", "_parent")

    def __init__(
        self,
        name: str,
        description: str,
        /,
        *,
        command_id: typing.Optional[hikari.SnowflakeishOr[hikari.Command]] = None,
        default_to_ephemeral: bool = False,
        is_global: bool = True,
        checks: typing.Optional[collections.Iterable[abc.CheckSig]] = None,
        hooks: typing.Optional[abc.SlashHooks] = None,
        metadata: typing.Optional[collections.MutableMapping[typing.Any, typing.Any]] = None,
    ) -> None:
        super().__init__(checks=checks, hooks=hooks, metadata=metadata)
        if not _SCOMMAND_NAME_REG.fullmatch(name):
            raise ValueError("Invalid command name provided, must match the regex `^[a-z0-9_-]{1,32}$`")

        self._command_id = hikari.Snowflake(command_id) if command_id else None
        self._defaults_to_ephemeral = default_to_ephemeral
        self._description = description
        self._is_global = is_global
        self._name = name
        self._parent: typing.Optional[abc.SlashCommandGroup] = None

    @property
    def defaults_to_ephemeral(self) -> bool:
        # <<inherited docstring from tanjun.abc.BaseSlashCommand>>.
        return self._defaults_to_ephemeral

    @property
    def description(self) -> str:
        # <<inherited docstring from tanjun.abc.BaseSlashCommand>>.
        return self._description

    @property
    def is_global(self) -> bool:
        # <<inherited docstring from tanjun.abc.BaseSlashCommand>>.
        return self._is_global

    @property
    def name(self) -> str:
        # <<inherited docstring from tanjun.abc.BaseSlashCommand>>.
        return self._name

    @property
    def parent(self) -> typing.Optional[abc.SlashCommandGroup]:
        # <<inherited docstring from tanjun.abc.BaseSlashCommand>>.
        return self._parent

    @property
    def tracked_command_id(self) -> typing.Optional[hikari.Snowflake]:
        return self._command_id

    def set_tracked_command(
        self: _BaseSlashCommandT, command_id: hikari.SnowflakeishOr[hikari.Command], /
    ) -> _BaseSlashCommandT:
        """Set the ID of the global command this should be tracking.

        .. warning::
            This is useful when bulk updating the commands as if the ID isn't
            specified then any previously set permissions may be lost (i.e. if the
            command's name is changed).

        Parameters
        ----------
        command_id : hikari.snowflakes.SnowflakeishOr[hikari.interactions.commands.Command]
            object or ID of the global command this should be tracking.
        """
        self._command_id = hikari.Snowflake(command_id)
        return self

    def set_ephemeral_default(self: _BaseSlashCommandT, state: bool, /) -> _BaseSlashCommandT:
        """Set whether this command's responses should default to ephemeral.

        Parameters
        ----------
        bool
            Whether this command's responses should default to ephemeral.
            This will be overridden by any response calls which specify flags.
        """
        self._defaults_to_ephemeral = state
        return self

    def set_parent(self: _BaseSlashCommandT, parent: typing.Optional[abc.SlashCommandGroup], /) -> _BaseSlashCommandT:
        # <<inherited docstring from tanjun.abc.BaseSlashCommand>>.
        self._parent = parent
        return self

    async def check_context(self, ctx: abc.SlashContext, /) -> bool:
        # <<inherited docstring from tanjun.abc.SlashCommand>>.
        ctx = ctx.set_command(self)
        result = await utilities.gather_checks(ctx, self._checks)
        ctx.set_command(None)
        return result

    def copy(
        self: _BaseSlashCommandT, *, _new: bool = True, parent: typing.Optional[abc.SlashCommandGroup] = None
    ) -> _BaseSlashCommandT:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        if not _new:
            self._parent = parent
            return super().copy(_new=_new)  # type: ignore  # Pyright seems to mis-handle the typevars here

        return super().copy(_new=_new)  # type: ignore  # Pyright seems to mis-handle the typevars here

    def load_into_component(
        self: _BaseSlashCommandT, component: abc.Component, /
    ) -> typing.Optional[_BaseSlashCommandT]:
        super().load_into_component(component)
        if not self._parent:
            component.add_slash_command(self)
            return self


class SlashCommandGroup(BaseSlashCommand, abc.SlashCommandGroup):
    __slots__ = ("_commands", "_default_permission")

    def __init__(
        self,
        name: str,
        description: str,
        /,
        *,
        command_id: typing.Optional[hikari.SnowflakeishOr[hikari.Command]] = None,
        default_to_ephemeral: bool = False,
        default_permission: bool = True,
        is_global: bool = True,
        checks: typing.Optional[collections.Iterable[abc.CheckSig]] = None,
        hooks: typing.Optional[abc.SlashHooks] = None,
        metadata: typing.Optional[collections.MutableMapping[typing.Any, typing.Any]] = None,
    ) -> None:
        super().__init__(
            name,
            description,
            command_id=command_id,
            default_to_ephemeral=default_to_ephemeral,
            is_global=is_global,
            checks=checks,
            hooks=hooks,
            metadata=metadata,
        )
        self._commands: dict[str, abc.BaseSlashCommand] = {}
        self._default_permission = default_permission

    @property
    def commands(self) -> collections.ValuesView[abc.BaseSlashCommand]:
        # <<inherited docstring from tanjun.abc.SlashCommandGroup>>.
        return self._commands.copy().values()

    def build(self) -> special_endpoints_api.CommandBuilder:
        # <<inherited docstring from tanjun.abc.BaseSlashCommand>>.
        builder = _CommandBuilder(self._name, self._description, False).set_default_permission(self._default_permission)
        if self._command_id:
            builder.set_id(self._command_id)

        for command in self._commands.values():
            option_type = (
                hikari.OptionType.SUB_COMMAND_GROUP
                if isinstance(command, abc.SlashCommandGroup)
                else hikari.OptionType.SUB_COMMAND
            )
            command_builder = command.build()
            builder.add_option(
                hikari.CommandOption(
                    type=option_type,
                    name=command.name,
                    description=command_builder.description,
                    is_required=False,
                    options=command_builder.options,
                )
            )

        return builder

    def copy(
        self: _SlashCommandGroupT, *, _new: bool = True, parent: typing.Optional[abc.SlashCommandGroup] = None
    ) -> _SlashCommandGroupT:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        if not _new:
            self._commands = {name: command.copy() for name, command in self._commands.items()}
            return super().copy(_new=_new, parent=parent)  # type: ignore  # Pyright seems to mis-handle the typevars

        return super().copy(_new=_new, parent=parent)  # type: ignore  # Pyright seems to mis-handle the typevars

    def add_command(self: _SlashCommandGroupT, command: abc.BaseSlashCommand, /) -> _SlashCommandGroupT:
        """Add a slash command to this group.

        .. warning::
            Command groups are only supported within top-level groups.

        Parameters
        ----------
        command : tanjun.abc.BaseSlashCommand
            Command to add to this group.

        Returns
        -------
        Self
            Object of this group to enable chained calls.
        """
        if self._parent and isinstance(command, abc.SlashCommandGroup):
            raise ValueError("Cannot add a slash command group to a nested slash command group")

        self._commands[command.name] = command
        return self

    def remove_command(self, command: abc.BaseSlashCommand, /) -> None:
        """Remove a command from this group.

        Parameters
        ----------
        command : tanjun.abc.BaseSlashCommand
            Command to remove from this group.
        """
        del self._commands[command.name]

    def with_command(self, command: abc.BaseSlashCommandT, /) -> abc.BaseSlashCommandT:
        """Add a slash command to this group through a decorator call.

        Parameters
        ----------
        command : tanjun.abc.BaseSlashCommand
            Command to add to this group.

        Returns
        -------
        tanjun.abc.BaseSlashCommand
            Command which was added to this group.
        """
        self.add_command(command)
        return command

    async def execute(
        self,
        ctx: abc.SlashContext,
        /,
        option: typing.Optional[hikari.CommandInteractionOption] = None,
        *,
        hooks: typing.Optional[collections.MutableSet[abc.SlashHooks]] = None,
    ) -> None:
        # <<inherited docstring from tanjun.abc.BaseSlashCommand>>.
        if not await self.check_context(ctx):
            return

        if not option and ctx.interaction.options:
            option = ctx.interaction.options[0]

        elif option and option.options:
            option = option.options[0]

        else:
            raise RuntimeError("Missing sub-command option")

        if command := self._commands.get(option.name):
            await command.execute(ctx, option=option, hooks=hooks)
            return

        await ctx.mark_not_found()

    def set_injector(self, client: injecting.InjectorClient, /) -> None:
        # <<inherited docstring from tanjun.injecting.Injectable>>.
        super().set_injector(client)
        for command in self._commands.values():
            if isinstance(command, injecting.Injectable):
                command.set_injector(client)


class SlashCommand(BaseSlashCommand, abc.SlashCommand, typing.Generic[CommandCallbackSigT]):
    __slots__ = ("_builder", "_callback", "_cached_getters", "_needs_injector", "_tracked_options")

    def __init__(
        self,
        callback: CommandCallbackSigT,
        name: str,
        description: str,
        /,
        *,
        checks: typing.Optional[collections.Iterable[abc.CheckSig]] = None,
        command_id: typing.Optional[hikari.SnowflakeishOr[hikari.Command]] = None,
        default_permission: bool = True,
        default_to_ephemeral: bool = False,
        is_global: bool = True,
        hooks: typing.Optional[abc.SlashHooks] = None,
        metadata: typing.Optional[collections.MutableMapping[typing.Any, typing.Any]] = None,
        sort_options: bool = True,
    ) -> None:
        super().__init__(
            name,
            description,
            checks=checks,
            command_id=command_id,
            default_to_ephemeral=default_to_ephemeral,
            hooks=hooks,
            is_global=is_global,
            metadata=metadata,
        )

        self._builder = _CommandBuilder(name, description, sort_options).set_default_permission(default_permission)
        if self._command_id:
            self._builder = self._builder.set_id(self._command_id)

        self._callback: CommandCallbackSigT = callback
        self._cached_getters: typing.Optional[list[injecting.Getter[typing.Any]]] = None
        self._needs_injector: typing.Optional[bool] = None
        self._tracked_options: dict[str, _TrackedOption] = {}
        if not _SCOMMAND_NAME_REG.fullmatch(name):
            raise ValueError("Invalid command name provided, must match the regex `^[a-z0-9_-]{1,32}$`")

    if typing.TYPE_CHECKING:
        __call__: CommandCallbackSigT

    else:

        async def __call__(self, *args, **kwargs) -> None:
            await self._callback(*args, **kwargs)

    @property
    def callback(self) -> CommandCallbackSigT:
        # <<inherited docstring from tanjun.abc.SlashCommand>>.
        return self._callback

    @property
    def needs_injector(self) -> bool:
        # <<inherited docstring from tanjun.injecting.Injectable>>.
        return (
            injecting.check_injecting(self._callback)
            or any(option.needs_injector for option in self._tracked_options.values())
            or super().needs_injector
        )

    def build(self) -> special_endpoints_api.CommandBuilder:
        # <<inherited docstring from tanjun.abc.BaseSlashCommand>>.
        return self._builder.copy()

    def add_option(
        self: _SlashCommandT,
        name: str,
        description: str,
        type_: typing.Union[hikari.OptionType, int] = hikari.OptionType.STRING,
        /,
        *,
        choices: typing.Optional[collections.Iterable[tuple[str, typing.Union[str, int, float]]]] = None,
        converters: typing.Union[collections.Iterable[ConverterSig], ConverterSig] = (),
        default: typing.Any = _UNDEFINED_DEFAULT,
        only_member: bool = False,
        pass_as_kwarg: bool = True,
    ) -> _SlashCommandT:
        # TODO: validate name
        type_ = hikari.OptionType(type_)
        if type in _SUB_COMMAND_OPTIONS_TYPES:
            raise NotImplementedError

        if only_member and type_ not in _MEMBER_OPTION_TYPES:
            raise ValueError("Specifically member may only be set for a USER or MENTIONABLE option")

        if isinstance(converters, collections.Iterable):
            converters = list(map(_convert_to_injectable, converters))

        else:
            converters = [_convert_to_injectable(converters)]

        if converters and (type_ in _OBJECT_OPTION_TYPES or type_ == hikari.OptionType.BOOLEAN):
            raise ValueError("Converters cannot be provided for bool or object options")

        choices_ = [hikari.CommandChoice(name=name, value=value) for name, value in choices] if choices else None
        required = default is _UNDEFINED_DEFAULT
        self._builder.add_option(
            hikari.CommandOption(type=type_, name=name, description=description, is_required=required, choices=choices_)
        )
        if pass_as_kwarg:
            self._tracked_options[name] = _TrackedOption(
                name=name,
                option_type=type_,
                converters=converters,
                default=default,
                only_member=only_member,
            )
        return self

    def set_injector(self, client: injecting.InjectorClient, /) -> None:
        # <<inherited docstring from tanjun.injecting.Injectable>>.
        super().set_injector(client)
        for option in self._tracked_options.values():
            option.set_injector(client)

    async def _process_args(
        self,
        ctx: abc.SlashContext,
        options: collections.Iterable[hikari.CommandInteractionOption],
        option_data: hikari.ResolvedOptionData,
        /,
    ) -> dict[str, typing.Any]:
        keyword_args: dict[str, typing.Any] = {}
        options_dict = {option.name: option for option in options}
        for tracked_option in self._tracked_options.values():
            option = options_dict.get(tracked_option.name)
            if not option or not option.value:
                if tracked_option.default is _UNDEFINED_DEFAULT:
                    # raise errors.ConversionError(
                    #     tracked_option.name,
                    #     "Found value-less or missing option for a option for tracked option with no default"
                    # )
                    raise RuntimeError("Found value-less or missing option for a tracked option with no default")

                keyword_args[tracked_option.name] = tracked_option.default

            elif option.type is hikari.OptionType.USER:
                user_id = hikari.Snowflake(option.value)
                member = option_data.members.get(user_id)
                if not member and tracked_option.is_only_member:
                    raise errors.ConversionError(
                        tracked_option.name, f"Couldn't find member for provided user: {user_id}"
                    )

                keyword_args[option.name] = member or option_data.users[user_id]

            elif option.type is hikari.OptionType.CHANNEL:
                keyword_args[option.name] = option_data.channels[hikari.Snowflake(option.value)]

            elif option.type is hikari.OptionType.ROLE:
                keyword_args[option.name] = option_data.roles[hikari.Snowflake(option.value)]

            elif option.type is hikari.OptionType.MENTIONABLE:
                id_ = hikari.Snowflake(option.value)
                if role := option_data.roles.get(id_):
                    keyword_args[option.name] = role

                else:
                    member = option_data.members.get(id_)
                    if not member and tracked_option.is_only_member:
                        raise errors.ConversionError(
                            tracked_option.name, f"Couldn't find member for provided user: {id_}"
                        )

                    keyword_args[option.name] = member or option_data.users[id_]

            elif tracked_option.converters:
                keyword_args[option.name] = await tracked_option.convert(ctx, option.value)

            else:
                keyword_args[option.name] = option.value

        return keyword_args

    def _get_injection_getters(self) -> collections.Iterable[injecting.Getter[typing.Any]]:
        if not self._injector:
            raise ValueError("Cannot execute command without injector client")

        if self._cached_getters is None:
            self._cached_getters = list(self._injector.resolve_callback_to_getters(self._callback))

            if self._needs_injector is None:
                self._needs_injector = bool(self._cached_getters)

        return self._cached_getters

    async def execute(
        self,
        ctx: abc.SlashContext,
        /,
        option: typing.Optional[hikari.CommandInteractionOption] = None,
        *,
        hooks: typing.Optional[collections.MutableSet[abc.SlashHooks]] = None,
    ) -> None:
        # <<inherited docstring from tanjun.abc.BaseSlashCommand>>.
        ctx = ctx.set_command(self)
        own_hooks = self._hooks or _EMPTY_HOOKS
        try:
            await own_hooks.trigger_pre_execution(ctx, hooks=hooks)

            if self._tracked_options:
                options = option.options if option else None
                kwargs = await self._process_args(
                    ctx, options or ctx.interaction.options or _EMPTY_LIST, ctx.interaction.resolved or _EMPTY_RESOLVED
                )

            else:
                kwargs = _EMPTY_DICT

            if self.needs_injector:
                injected_values = await injecting.resolve_getters(ctx, self._get_injection_getters())
                if kwargs is _EMPTY_DICT:
                    kwargs = injected_values

                else:
                    kwargs.update(injected_values)

            await self._callback(ctx, **kwargs)

        except errors.CommandError as exc:
            await ctx.respond(exc.message)

        except errors.HaltExecution:
            # Unlike a message command, this won't necessarily reach the client level try except
            # block so we have to handle this here.
            await ctx.mark_not_found()

        except Exception as exc:
            if await own_hooks.trigger_error(ctx, exc, hooks=hooks) <= 0:
                raise

        else:
            await own_hooks.trigger_success(ctx, hooks=hooks)

        finally:
            await own_hooks.trigger_post_execution(ctx, hooks=hooks)

    def copy(
        self: _SlashCommandT, *, _new: bool = True, parent: typing.Optional[abc.SlashCommandGroup] = None
    ) -> _SlashCommandT:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        if not _new:
            self._cached_getters = None
            self._callback = copy.copy(self._callback)
            self._needs_injector = None
            return super().copy(_new=_new, parent=parent)  # type: ignore  # Pyright seems to mis-handle the typevars

        return super().copy(_new=_new, parent=parent)  # type: ignore  # Pyright seems to mis-handle the typevars here

    def load_into_component(self: _SlashCommandT, component: abc.Component, /) -> typing.Optional[_SlashCommandT]:
        if isinstance(self._callback, types.MethodType):
            raise ValueError("Callback is already a method type")

        super().load_into_component(component)
        self._cached_getters = None
        self._callback = types.MethodType(self._callback, component)  # type: ignore[assignment]
        self._needs_injector = None

        if not self._parent:
            component.add_slash_command(self)
            return self


def as_message_command(
    name: str, /, *names: str
) -> collections.Callable[[CommandCallbackSigT], MessageCommand[CommandCallbackSigT]]:
    """Build a message command from a decorated callback.

    Parameters
    ----------
    name : str
        The command name.

    Other Parameters
    ----------------
    names : str
        Variable positional arguments of other names for the command.

    Returns
    -------
    collections.abc.Callable[[CommandCallbackSigT], MessageCommand[CommandCallbackSigT]]
        Decorator callback used to build a MessageCommand` from the decorated callback.
    """
    return lambda callback: MessageCommand(callback, name, *names)


def as_message_command_group(
    name: str, /, *names: str, strict: bool = False
) -> collections.Callable[[CommandCallbackSigT], MessageCommandGroup[CommandCallbackSigT]]:
    """Build a message command group from a decorated callback.

    Parameters
    ----------
    name : str
        The command name.

    Other Parameters
    ----------------
    names : str
        Variable positional arguments of other names for the command.
    strict : bool
        Whether this command group should only allow commands without spaces in their names.

        This allows for a more optimised command search pattern to be used and
        enforces that command names are unique to a single command within the group.

    Returns
    -------
    collections.abc.Callable[[CommandCallbackSigT], MessageCommandGroup[CommandCallbackSigT]]
        Decorator callback used to build a `MessageCommandGroup` from the decorated callback.
    """
    return lambda callback: MessageCommandGroup(callback, name, *names, strict=strict)


class MessageCommand(PartialCommand[abc.MessageContext], abc.MessageCommand, typing.Generic[CommandCallbackSigT]):
    __slots__ = ("_cached_getters", "_callback", "_names", "_needs_injector", "_parent", "_parser")

    def __init__(
        self,
        callback: CommandCallbackSigT,
        name: str,
        /,
        *names: str,
        checks: typing.Optional[collections.Iterable[abc.CheckSig]] = None,
        hooks: typing.Optional[abc.MessageHooks] = None,
        metadata: typing.Optional[collections.MutableMapping[typing.Any, typing.Any]] = None,
        parser: typing.Optional[parsing.AbstractParser] = None,
    ) -> None:
        super().__init__(checks=checks, hooks=hooks, metadata=metadata)
        self._callback: CommandCallbackSigT = callback
        self._cached_getters: typing.Optional[list[injecting.Getter[typing.Any]]] = None
        self._needs_injector: typing.Optional[bool] = None
        self._names = {name, *names}
        self._parent: typing.Optional[abc.MessageCommandGroup] = None
        self._parser = parser

    def __repr__(self) -> str:
        return f"Command <{self._names}>"

    @property
    def callback(self) -> CommandCallbackSigT:
        # <<inherited docstring from tanjun.abc.MessageCommand>>.
        return self._callback

    @property
    # <<inherited docstring from tanjun.abc.MessageCommand>>.
    def names(self) -> collections.Set[str]:
        return self._names.copy()

    @property
    def needs_injector(self) -> bool:
        # <<inherited docstring from tanjun.injecting.Injectable>>.
        return injecting.check_injecting(self._callback) or super().needs_injector

    @property
    def parent(self) -> typing.Optional[abc.MessageCommandGroup]:
        # <<inherited docstring from tanjun.abc.MessageCommand>>.
        return self._parent

    @property
    def parser(self) -> typing.Optional[parsing.AbstractParser]:
        return self._parser

    def bind_client(self, client: abc.Client, /) -> None:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        super().bind_client(client)
        if self._parser:
            self._parser.bind_client(client)

    def bind_component(self, component: abc.Component, /) -> None:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        super().bind_component(component)
        if self._parser:
            self._parser.bind_component(component)

    def copy(
        self: _MessageCommandT, *, _new: bool = True, parent: typing.Optional[abc.MessageCommandGroup] = None
    ) -> _MessageCommandT:
        # <<inherited docstring from tanjun.abc.MessageCommand>>.
        if not _new:
            self._cached_getters = None
            self._callback = copy.copy(self._callback)
            self._names = self._names.copy()
            self._needs_injector = None
            self._parent = parent
            self._parser = self._parser.copy() if self._parser else None
            return super().copy(_new=_new)  # type: ignore  # Pyright seems to mis-handle the typevars here

        return super().copy(_new=_new)  # type: ignore  # Pyright seems to mis-handle the typevars here

    def set_parent(self: _MessageCommandT, parent: typing.Optional[abc.MessageCommandGroup], /) -> _MessageCommandT:
        # <<inherited docstring from tanjun.abc.MessageCommand>>.
        self._parent = parent
        return self

    def set_parser(self: _MessageCommandT, parser: typing.Optional[parsing.AbstractParser], /) -> _MessageCommandT:
        self._parser = parser
        return self

    async def check_context(self, ctx: abc.MessageContext, /) -> bool:
        # <<inherited docstring from tanjun.abc.MessageCommand>>.
        ctx = ctx.set_command(self)
        result = await utilities.gather_checks(ctx, self._checks)
        ctx.set_command(None)
        return result

    async def execute(
        self,
        ctx: abc.MessageContext,
        /,
        *,
        hooks: typing.Optional[collections.MutableSet[abc.MessageHooks]] = None,
    ) -> None:
        # <<inherited docstring from tanjun.abc.MessageCommand>>.
        ctx = ctx.set_command(self)
        own_hooks = self._hooks or _EMPTY_HOOKS
        try:
            await own_hooks.trigger_pre_execution(ctx, hooks=hooks)

            if self._parser is not None:
                args, kwargs = await self._parser.parse(ctx)

            else:
                args = _EMPTY_LIST
                kwargs = _EMPTY_DICT

            if self.needs_injector:
                injected_values = await injecting.resolve_getters(ctx, self._get_injection_getters())
                if kwargs is _EMPTY_DICT:
                    kwargs = injected_values

                else:
                    kwargs.update(injected_values)

            await self._callback(ctx, *args, **kwargs)

        except errors.CommandError as exc:
            response = exc.message if len(exc.message) <= 2000 else exc.message[:1997] + "..."
            retry = backoff.Backoff(max_retries=5, maximum=2)
            # TODO: preemptive cache based permission checks before throwing to the REST gods.
            async for _ in retry:
                try:
                    await ctx.respond(content=response)

                except (hikari.RateLimitedError, hikari.RateLimitTooLongError) as retry_error:
                    if retry_error.retry_after > 4:
                        raise

                    retry.set_next_backoff(retry_error.retry_after)  # TODO: check if this is too large.

                except hikari.InternalServerError:
                    continue

                except (hikari.ForbiddenError, hikari.NotFoundError):
                    break

                else:
                    break

        except errors.HaltExecution:
            raise

        except Exception as exc:
            if await own_hooks.trigger_error(ctx, exc, hooks=hooks) <= 0:
                raise

        else:
            # TODO: how should this be handled around CommandError?
            await own_hooks.trigger_success(ctx, hooks=hooks)

        finally:
            await own_hooks.trigger_post_execution(ctx, hooks=hooks)

    def _get_injection_getters(self) -> collections.Iterable[injecting.Getter[typing.Any]]:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        if not self._injector:
            raise ValueError("Cannot execute command without injector client")

        if self._cached_getters is None:
            self._cached_getters = list(self._injector.resolve_callback_to_getters(self._callback))

            if self._needs_injector is None:
                self._needs_injector = bool(self._cached_getters)

        return self._cached_getters

    def load_into_component(self: _MessageCommandT, component: abc.Component, /) -> typing.Optional[_MessageCommandT]:
        if isinstance(self._callback, types.MethodType):
            raise ValueError("Callback is already a method type")

        super().load_into_component(component)
        self._cached_getters = None
        self._callback = types.MethodType(self._callback, component)  # type: ignore[assignment]
        self._needs_injector = None

        if not self._parent:
            component.add_message_command(self)
            return self


class MessageCommandGroup(MessageCommand[CommandCallbackSigT], abc.MessageCommandGroup):
    __slots__ = ("_commands", "_is_strict", "_names_to_commands")

    def __init__(
        self,
        callback: CommandCallbackSigT,
        name: str,
        /,
        *names: str,
        checks: typing.Optional[collections.Iterable[abc.CheckSig]] = None,
        hooks: typing.Optional[abc.MessageHooks] = None,
        metadata: typing.Optional[collections.MutableMapping[typing.Any, typing.Any]] = None,
        strict: bool = False,
        parser: typing.Optional[parsing.AbstractParser] = None,
    ) -> None:
        super().__init__(callback, name, *names, checks=checks, hooks=hooks, metadata=metadata, parser=parser)
        self._commands: set[abc.MessageCommand] = set()
        self._is_strict = strict
        self._names_to_commands: dict[str, abc.MessageCommand] = {}

    def __repr__(self) -> str:
        return f"CommandGroup <{len(self._commands)}: {self._names}>"

    @property
    def commands(self) -> collections.Set[abc.MessageCommand]:
        # <<inherited docstring from tanjun.abc.MessageCommandGroup>>.
        return self._commands.copy()

    @property
    def is_strict(self) -> bool:
        return self._is_strict

    def copy(
        self: _MessageCommandGroupT, *, _new: bool = True, parent: typing.Optional[abc.MessageCommandGroup] = None
    ) -> _MessageCommandGroupT:
        # <<inherited docstring from tanjun.abc.MessageCommand>>.
        if not _new:
            commands = {command: command.copy(parent=self) for command in self._commands}
            self._commands = set(commands.values())
            self._names_to_commands = {name: commands[command] for name, command in self._names_to_commands.items()}
            return super().copy(parent=parent, _new=_new)  # type: ignore  # Pyright seems to mis-handle the typevars

        return super().copy(parent=parent, _new=_new)  # type: ignore  # Pyright seems to mis-handle the typevars here

    def add_command(self: _MessageCommandGroupT, command: abc.MessageCommand, /) -> _MessageCommandGroupT:
        """Add a command to this group.

        Parameters
        ----------
        command : MessageCommand
            The command to add.

        Returns
        -------
        Self
            The group instance to enable chained calls.

        Raises
        ------
        ValueError
            If one of the command's names is already registered in a strict
            command group.
        """
        if self._is_strict:
            if any(" " in name for name in command.names):
                raise ValueError("Sub-command names may not contain spaces in a strict message command group")

            if name_conflicts := self._names_to_commands.keys() & command.names:
                raise ValueError(
                    "Sub-command names must be unique in a strict message command group. "
                    "The following conflicts were found " + ", ".join(name_conflicts)
                )

            self._names_to_commands.update((name, command) for name in command.names)

        command.set_parent(self)
        self._commands.add(command)
        return self

    def remove_command(self, command: abc.MessageCommand, /) -> None:
        # <<inherited docstring from tanjun.abc.MessageCommandGroup>>.
        self._commands.remove(command)
        if self._is_strict:
            for name in command.names:
                if self._names_to_commands.get(name) == command:
                    del self._names_to_commands[name]

        command.set_parent(None)

    def with_command(self, command: AnyMessageCommandT, /) -> AnyMessageCommandT:
        self.add_command(command)
        return command

    def bind_client(self, client: abc.Client, /) -> None:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        super().bind_client(client)
        for command in self._commands:
            command.bind_client(client)

    def bind_component(self, component: abc.Component, /) -> None:
        # <<inherited docstring from tanjun.abc.ExecutableCommand>>.
        super().bind_component(component)
        for command in self._commands:
            command.bind_component(component)

    def set_injector(self, client: injecting.InjectorClient, /) -> None:
        super().set_injector(client)

        if self._parser and isinstance(self._parser, injecting.Injectable):
            self._parser.set_injector(client)

        for command in self._commands:
            if isinstance(command, injecting.Injectable):
                command.set_injector(client)

    def find_command(self, content: str, /) -> collections.Iterable[tuple[str, abc.MessageCommand]]:
        if self._is_strict:
            name = content.split(" ")[0]
            if command := self._names_to_commands.get(name):
                yield name, command
                return

        for command in self._commands:
            if (name := utilities.match_prefix_names(content, command.names)) is not None:
                yield name, command

    # I sure hope this plays well with command group recursion cause I am waaaaaaaaaaaaaay too lazy to test that myself.
    async def execute(
        self,
        ctx: abc.MessageContext,
        /,
        *,
        hooks: typing.Optional[collections.MutableSet[abc.MessageHooks]] = None,
    ) -> None:
        # <<inherited docstring from tanjun.abc.MessageCommand>>.
        if ctx.message.content is None:
            raise ValueError("Cannot execute a command with a contentless message")

        if self._hooks:
            if hooks is None:
                hooks = set()

            hooks.add(self._hooks)

        for name, command in self.find_command(ctx.content):
            if await command.check_context(ctx):
                content = ctx.message.content.lstrip()[len(ctx.triggering_prefix) :].lstrip()[
                    len(ctx.triggering_name) :
                ]
                space_len = len(content) - len(content.lstrip())
                ctx.set_triggering_name(ctx.triggering_name + (" " * space_len) + name)
                ctx.set_content(ctx.content[space_len + len(name) :].lstrip())
                await command.execute(ctx, hooks=hooks)
                return

        await super().execute(ctx, hooks=hooks)

    def load_into_component(
        self: _MessageCommandGroupT, component: abc.Component, /
    ) -> typing.Optional[_MessageCommandGroupT]:
        super().load_into_component(component)
        for command in self._commands:
            if isinstance(command, components.LoadableProtocol):
                command.load_into_component(component)

        if not self._parent:
            return self

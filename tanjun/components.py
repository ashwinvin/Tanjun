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

__all__: typing.Sequence[str] = ["CommandT", "Component", "LoadableProtocol", "WithCommandReturnSig"]

import asyncio
import copy
import inspect
import typing

from hikari.events import base_events

from . import injector
from . import traits
from . import utilities

if typing.TYPE_CHECKING:
    from hikari.api import event_manager as event_manager_api

    _ComponentT = typing.TypeVar("_ComponentT", bound="Component")
    _T = typing.TypeVar("_T")


CommandT = typing.TypeVar("CommandT", bound="traits.ExecutableCommand[typing.Any]")


@typing.runtime_checkable
class LoadableProtocol(typing.Protocol):
    __slots__ = ()

    def copy(self: _T) -> _T:
        raise NotImplementedError

    def load_into_component(self, component: traits.Component, /) -> typing.Optional[typing.Any]:
        raise NotImplementedError


def _with_command(
    add_command: typing.Callable[[CommandT], typing.Any], command: typing.Optional[CommandT], /, *, copy: bool = False
) -> WithCommandReturnSig[CommandT]:
    if command:
        add_command(command.copy() if copy else command)
        return command

    def decorator(command_: CommandT, /) -> CommandT:
        add_command(command_.copy() if copy else command_)
        return command_

    return decorator


WithCommandReturnSig = typing.Union[CommandT, typing.Callable[[CommandT], CommandT]]


class Component(injector.Injectable, traits.Component):
    __slots__: typing.Sequence[str] = (
        "_checks",
        "_client",
        "_client_callbacks",
        "_hooks",
        "_injector",
        "_interaction_commands",
        "_interaction_hooks",
        "_listeners",
        "_message_commands",
        "_message_hooks",
        "_metadata",
    )

    def __init__(
        self,
        *,
        checks: typing.Optional[typing.Iterable[traits.CheckSig]] = None,
        hooks: typing.Optional[traits.AnyHooks] = None,
        interaction_hooks: typing.Optional[traits.InteractionHooks] = None,
        message_hooks: typing.Optional[traits.MessageHooks] = None,
    ) -> None:
        self._checks: typing.Set[injector.InjectableCheck] = (
            set(injector.InjectableCheck(check) for check in checks) if checks else set()
        )
        self._client: typing.Optional[traits.Client] = None
        self._client_callbacks: typing.Dict[str, typing.Set[traits.MetaEventSig]] = {}
        self._hooks = hooks
        self._injector: typing.Optional[injector.InjectorClient] = None
        self._interaction_commands: typing.Dict[str, traits.InteractionCommand] = {}
        self._interaction_hooks = interaction_hooks
        self._listeners: typing.Set[
            typing.Tuple[typing.Type[base_events.Event], event_manager_api.CallbackT[typing.Any]]
        ] = set()
        self._message_commands: typing.Set[traits.MessageCommand] = set()
        self._message_hooks = message_hooks
        self._metadata: typing.Dict[typing.Any, typing.Any] = {}
        self._load_from_properties()

    def __repr__(self) -> str:
        count_1 = len(self._message_commands)
        count_2 = len(self._interaction_commands)
        return f"Component <{type(self).__name__}, ({count_1}, {count_2})  commands>"

    @property
    def checks(self) -> typing.AbstractSet[traits.CheckSig]:
        return {check.callback for check in self._checks}

    @property
    def client(self) -> typing.Optional[traits.Client]:
        return self._client

    @property
    def hooks(self) -> typing.Optional[traits.AnyHooks]:
        return self._hooks

    @property
    def interaction_commands(self) -> typing.ValuesView[traits.InteractionCommand]:
        return self._interaction_commands.copy().values()

    @property
    def message_commands(self) -> typing.AbstractSet[traits.MessageCommand]:
        return self._message_commands.copy()

    @property
    def interaction_hooks(self) -> typing.Optional[traits.InteractionHooks]:
        return self._interaction_hooks

    @property
    def message_hooks(self) -> typing.Optional[traits.MessageHooks]:
        return self._message_hooks

    @property
    def needs_injector(self) -> bool:
        # TODO: cache this value maybe
        if any(check.needs_injector for check in self._checks):
            return True

        return any(
            isinstance(command, injector.Injectable) and command.needs_injector for command in self._message_commands
        )

    @property
    def listeners(
        self,
    ) -> typing.AbstractSet[typing.Tuple[typing.Type[base_events.Event], event_manager_api.CallbackT[typing.Any]]]:
        return self._listeners.copy()

    @property
    def metadata(self) -> typing.MutableMapping[typing.Any, typing.Any]:
        return self._metadata

    def copy(self: _ComponentT, *, _new: bool = True) -> _ComponentT:
        if not _new:
            self._checks = set(check.copy() for check in self._checks)
            self._interaction_commands = {name: command.copy() for name, command in self._interaction_commands.items()}
            self._message_commands = {command.copy() for command in self._message_commands}
            self._hooks = self._hooks.copy() if self._hooks else None
            self._listeners = {copy.copy(listener) for listener in self._listeners}
            self._metadata = self._metadata.copy()
            return self

        return copy.copy(self).copy(_new=False)

    def set_interaction_hooks(self: _ComponentT, hooks_: typing.Optional[traits.InteractionHooks], /) -> _ComponentT:
        self._interaction_hooks = hooks_
        return self

    def set_message_hooks(self: _ComponentT, hooks_: typing.Optional[traits.MessageHooks]) -> _ComponentT:
        self._message_hooks = hooks_
        return self

    def set_hooks(self: _ComponentT, hooks: typing.Optional[traits.AnyHooks], /) -> _ComponentT:
        self._hooks = hooks
        return self

    def add_check(self: _ComponentT, check: traits.CheckSig, /) -> _ComponentT:
        self._checks.add(injector.InjectableCheck(check, injector=self._injector))
        return self

    def remove_check(self, check: traits.CheckSig, /) -> None:
        self._checks.remove(check)  # type: ignore[arg-type]

    def with_check(self, check: traits.CheckSigT, /) -> traits.CheckSigT:
        self.add_check(check)
        return check

    def add_client_callback(self: _ComponentT, event_name: str, callback: traits.MetaEventSig, /) -> _ComponentT:
        event_name = event_name.lower()
        try:
            self._client_callbacks[event_name].add(callback)
        except KeyError:
            self._client_callbacks[event_name] = {callback}

        if self._client:
            self._client.add_client_callback(event_name, callback)

        return self

    def get_client_callbacks(self, event_name: str, /) -> typing.Collection[traits.MetaEventSig]:
        event_name = event_name.lower()
        return self._client_callbacks.get(event_name) or ()

    def remove_client_callback(self, event_name: str, callback: traits.MetaEventSig, /) -> None:
        event_name = event_name.lower()
        self._client_callbacks[event_name].remove(callback)
        if not self._client_callbacks[event_name]:
            del self._client_callbacks[event_name]

        if self._client:
            self._client.remove_client_callback(event_name, callback)

    def with_client_callback(self, event_name: str, /) -> typing.Callable[[traits.MetaEventSigT], traits.MetaEventSigT]:
        def decorator(callback: traits.MetaEventSigT, /) -> traits.MetaEventSigT:
            self.add_client_callback(event_name, callback)
            return callback

        return decorator

    def add_command(self: _ComponentT, command: traits.ExecutableCommand[typing.Any], /) -> _ComponentT:
        if isinstance(command, traits.MessageCommand):
            self.add_message_command(command)

        elif isinstance(command, traits.InteractionCommand):
            self.add_interaction_command(command)

        else:
            raise ValueError(
                f"Unexpected object passed, expected a MessageCommand or InteractionCommand but got {type(command)}"
            )

        return self

    def remove_command(self, command: traits.ExecutableCommand[typing.Any], /) -> None:
        if isinstance(command, traits.MessageCommand):
            self.remove_message_command(command)

        elif isinstance(command, traits.InteractionCommand):
            self.remove_interaction_command(command)

        else:
            raise ValueError(
                f"Unexpected object passed, expected a MessageCommand or InteractionCommand but got {type(command)}"
            )

    @typing.overload
    def with_command(self, command: CommandT, /) -> CommandT:
        ...

    @typing.overload
    def with_command(self, *, copy: bool = False) -> typing.Callable[[CommandT], CommandT]:
        ...

    def with_command(
        self, command: typing.Optional[CommandT] = None, /, *, copy: bool = False
    ) -> WithCommandReturnSig[CommandT]:
        return _with_command(self.add_command, command, copy=copy)

    def add_interaction_command(self: _ComponentT, command: traits.InteractionCommand, /) -> _ComponentT:
        if self._injector and isinstance(command, injector.Injectable):
            command.set_injector(self._injector)

        self._interaction_commands[command.name.casefold()] = command
        return self

    def remove_interaction_command(self, command: traits.InteractionCommand, /) -> None:
        del self._interaction_commands[command.name.casefold()]

    @typing.overload
    def with_interaction_command(self, command: traits.InteractionCommandT, /) -> traits.InteractionCommandT:
        ...

    @typing.overload
    def with_interaction_command(
        self, *, copy: bool = False
    ) -> typing.Callable[[traits.InteractionCommandT], traits.InteractionCommandT]:
        ...

    def with_interaction_command(
        self, command: typing.Optional[traits.InteractionCommandT] = None, /, *, copy: bool = False
    ) -> WithCommandReturnSig[traits.InteractionCommandT]:
        return _with_command(self.add_interaction_command, command, copy=copy)

    def add_message_command(self: _ComponentT, command: traits.MessageCommand, /) -> _ComponentT:
        if self._injector and isinstance(command, injector.Injectable):
            command.set_injector(self._injector)

        self._message_commands.add(command)
        return self

    def remove_message_command(self, command: traits.MessageCommand, /) -> None:
        self._message_commands.remove(command)

    @typing.overload
    def with_message_command(self, command: traits.MessageCommandT, /) -> traits.MessageCommandT:
        ...

    @typing.overload
    def with_message_command(
        self, *, copy: bool = False
    ) -> typing.Callable[[traits.MessageCommandT], traits.MessageCommandT]:
        ...

    def with_message_command(
        self, command: typing.Optional[traits.MessageCommandT] = None, /, *, copy: bool = False
    ) -> WithCommandReturnSig[traits.MessageCommandT]:
        return _with_command(self.add_message_command, command, copy=copy)

    def add_listener(
        self: _ComponentT,
        event: typing.Type[event_manager_api.EventT_inv],
        listener: event_manager_api.CallbackT[event_manager_api.EventT_inv],
        /,
    ) -> _ComponentT:
        self._listeners.add((event, listener))

        if self._client and self._client.events:
            self._client.events.subscribe(event, listener)

        return self

    def remove_listener(
        self,
        event: typing.Type[event_manager_api.EventT_inv],
        listener: event_manager_api.CallbackT[event_manager_api.EventT_inv],
        /,
    ) -> None:
        self._listeners.remove((event, listener))

        if self._client and self._client.events:
            self._client.events.unsubscribe(event, listener)

    # TODO: make event optional?
    def with_listener(
        self, event_type: typing.Type[event_manager_api.EventT_inv]
    ) -> typing.Callable[
        [event_manager_api.CallbackT[event_manager_api.EventT_inv]],
        event_manager_api.CallbackT[event_manager_api.EventT_inv],
    ]:
        def decorator(
            callback: event_manager_api.CallbackT[event_manager_api.EventT_inv],
        ) -> event_manager_api.CallbackT[event_manager_api.EventT_inv]:
            self.add_listener(event_type, callback)
            return callback

        return decorator

    def set_injector(self, client: injector.InjectorClient, /) -> None:
        if self._injector:
            raise RuntimeError("Injector already set")

        self._injector = client

        for check in self._checks:
            check.set_injector(client)

        for command in self._message_commands:
            if isinstance(command, injector.Injectable):
                command.set_injector(client)

    def bind_client(self, client: traits.Client, /) -> None:
        if self._client:
            raise RuntimeError("Client already set")

        self._client = client

        for command in self._message_commands:
            command.bind_client(client)

        # TODO: warn if listeners registered without any provided dispatch handler
        if self._client.events:
            for event_, listener in self._listeners:
                self._client.events.subscribe(event_, listener)

        for event_name, callbacks in self._client_callbacks.items():
            for callback in callbacks:
                self._client.add_client_callback(event_name, callback)

    def unbind_client(self, client: traits.Client, /) -> None:
        if not self._client or self._client != client:
            raise RuntimeError("Component isn't bound to this client")

        if self._client.events:
            for event_, listener in self._listeners:
                try:
                    self._client.events.unsubscribe(event_, listener)
                except (ValueError, LookupError):
                    # TODO: add logging here
                    pass

        for event_name, callbacks in self._client_callbacks.items():
            for callback in callbacks:
                try:
                    self._client.remove_client_callback(event_name, callback)
                except (LookupError, ValueError):
                    pass

    async def check_message_context(
        self, ctx: traits.MessageContext, /, *, name_prefix: str = ""
    ) -> typing.AsyncIterator[typing.Tuple[str, traits.MessageCommand]]:
        ctx.set_component(self)
        if await utilities.gather_checks(ctx, self._checks):
            for command in self._message_commands:
                if name := await command.check_context(ctx, name_prefix=name_prefix):
                    yield name, command

        ctx.set_component(None)

    def check_message_name(self, name: str, /) -> typing.Iterator[typing.Tuple[str, traits.MessageCommand]]:
        for command in self._message_commands:
            if found_name := command.check_name(name):
                yield found_name, command

    async def execute_interaction(
        self,
        ctx: traits.InteractionContext,
        /,
        *,
        hooks: typing.Optional[typing.MutableSet[traits.InteractionHooks]] = None,
    ) -> bool:
        command = self._interaction_commands.get(ctx.interaction.command_name)
        if not command:
            return False

        if self._interaction_hooks:
            if hooks is None:
                hooks = set()

            hooks.add(self._interaction_hooks)

        if self._hooks:
            if hooks is None:
                hooks = set()

            hooks.add(self._hooks)

        asyncio.create_task(command.execute(ctx, hooks=hooks))
        return True

    async def execute_message(
        self,
        ctx: traits.MessageContext,
        /,
        *,
        hooks: typing.Optional[typing.MutableSet[traits.MessageHooks]] = None,
    ) -> bool:
        async for name, command in self.check_message_context(ctx):
            ctx.set_triggering_name(name)
            ctx.set_content(ctx.content[len(name) :].lstrip())
            ctx.set_component(self)
            # Only add our hooks if we're sure we'll be executing the command here.

            if self._message_hooks:
                if hooks is None:
                    hooks = set()

                hooks.add(self._message_hooks)

            if self._hooks:
                if hooks is None:
                    hooks = set()

                hooks.add(self._hooks)

            await command.execute(ctx, hooks=hooks)
            return True

        return False

    def _load_from_properties(self) -> None:
        for name, member in inspect.getmembers(self):
            if isinstance(member, LoadableProtocol):
                if result := member.copy().load_into_component(self):
                    setattr(self, name, result)

# Copyright (c) 2016 Robbin Bonthond

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# ------------------------------------------------------------------------------------
# Jos Verlinde - 2024
# modified to avoid conflcts with rich_click

# sourcery skip: assign-if-exp, use-named-expression

import rich_click as click

_click7 = click.__version__[0] >= "7"


class ClickAliasedGroup(click.RichGroup):
    """
    A subclass of click.RichGroup that adds support for command aliases.

    This class allows defining aliases for commands and groups, enabling users
    to invoke commands using alternative names.
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize the ClickAliasedGroup instance.

        Args:
            *args: Positional arguments passed to the superclass.
            **kwargs: Keyword arguments passed to the superclass.
        """
        super().__init__(*args, **kwargs)
        self._commands = {}
        self._aliases = {}

    def add_command(self, *args, **kwargs):
        """
        Add a command to the group, optionally with aliases.

        Args:
            *args: Positional arguments, typically the command instance and optionally its name.
            **kwargs: Keyword arguments, may include 'aliases' as a list of alternative names.

        Raises:
            TypeError: If the command has no name.
        """
        aliases = kwargs.pop("aliases", [])
        super().add_command(*args, **kwargs)
        if aliases:
            cmd = args[0]
            name = args[1] if len(args) > 1 else None
            name = name or cmd.name
            if name is None:
                raise TypeError("Command has no name.")

            self._commands[name] = aliases
            for alias in aliases:
                self._aliases[alias] = cmd.name

    def command(self, *args, **kwargs):
        """
        Decorator to define a new command with optional aliases.

        Args:
            *args: Positional arguments passed to the superclass decorator.
            **kwargs: Keyword arguments, may include 'aliases' as a list of alternative names.

        Returns:
            Callable: A decorator function that registers the command and its aliases.
        """
        aliases = kwargs.pop("aliases", [])
        decorator = super().command(*args, **kwargs)
        if not aliases:
            return decorator

        def _decorator(f):
            cmd = decorator(f)
            if aliases:
                self._commands[cmd.name] = aliases
                for alias in aliases:
                    self._aliases[alias] = cmd.name
            return cmd

        return _decorator

    def group(self, *args, **kwargs):
        """
        Decorator to define a new command group with optional aliases.

        Args:
            *args: Positional arguments passed to the superclass decorator.
            **kwargs: Keyword arguments, may include 'aliases' as a list of alternative names.

        Returns:
            Callable: A decorator function that registers the group and its aliases.
        """
        aliases = kwargs.pop("aliases", [])
        decorator = super().group(*args, **kwargs)
        if not aliases:
            return decorator

        def _decorator(f):
            cmd = decorator(f)
            if aliases:
                self._commands[cmd.name] = aliases
                for alias in aliases:
                    self._aliases[alias] = cmd.name
            return cmd

        return _decorator

    def resolve_alias(self, cmd_name):
        """
        Resolve a command alias to its original command name.

        Args:
            cmd_name (str): The command name or alias to resolve.

        Returns:
            str: The original command name if an alias is provided; otherwise, the input name.
        """
        if cmd_name in self._aliases:
            return self._aliases[cmd_name]
        return cmd_name

    def get_command(self, ctx, cmd_name):
        """
        Retrieve a command by name or alias.

        Args:
            ctx (click.Context): The Click context object.
            cmd_name (str): The command name or alias to retrieve.

        Returns:
            click.Command or None: The command object if found; otherwise, None.
        """
        cmd_name = self.resolve_alias(cmd_name)
        command = super().get_command(ctx, cmd_name)
        if command:
            return command
        return None

    # def format_commands(self, ctx, formatter):
    # TODO: output alias with commands - but that is a significant re-write
    # for now add alias to help text


# ------------------------------------------------------------------------------------

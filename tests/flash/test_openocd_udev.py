"""Tests for the KitProg3 udev rule installer. Nothing here runs sudo."""

from __future__ import annotations

import subprocess

import pytest

from mpflash.flash.builtins.openocd import udev


@pytest.fixture
def interactive(mocker):
    mocker.patch.object(udev, "_can_prompt", return_value=True)
    mocker.patch.object(udev.os, "geteuid", return_value=1000)
    mocker.patch.object(udev.shutil, "which", return_value="/usr/bin/sudo")


@pytest.fixture
def run(mocker):
    return mocker.patch.object(udev.subprocess, "run")


@pytest.fixture
def confirm(mocker):
    return mocker.patch("click.confirm", return_value=True)


def test_bundled_rule_file_exists_and_matches_kitprog3():
    text = udev.RULES_FILE.read_text()
    assert udev.RULES_FILE.name.startswith("65-mpflash-")
    assert 'ATTRS{idVendor}=="04b4"' in text and 'ATTRS{idProduct}=="f155"' in text
    assert "0666" not in text


def test_install_commands_use_sudo_for_normal_user(mocker):
    mocker.patch.object(udev.os, "geteuid", return_value=1000)
    commands = udev.install_commands()
    assert all(c[0] == "sudo" for c in commands)
    assert commands[0] == ["sudo", "cp", "-f", str(udev.RULES_FILE), f"/etc/udev/rules.d/{udev.RULES_FILE.name}"]
    assert commands[1] == ["sudo", "udevadm", "control", "--reload-rules"]
    assert "--attr-match=idVendor=04b4" in commands[2]


def test_install_commands_skip_sudo_for_root(mocker):
    mocker.patch.object(udev.os, "geteuid", return_value=0)
    assert all(c[0] != "sudo" for c in udev.install_commands())


def test_offer_install_runs_commands_after_confirmation(interactive, confirm, run):
    assert udev.offer_install() is True
    confirm.assert_called_once()
    assert confirm.call_args.kwargs["default"] is False
    assert [c.args[0] for c in run.call_args_list] == udev.install_commands()


def test_offer_install_declined_runs_nothing(interactive, confirm, run):
    confirm.return_value = False
    assert udev.offer_install() is False
    run.assert_not_called()


def test_offer_install_never_prompts_when_not_interactive(mocker, confirm, run):
    mocker.patch.object(udev, "_can_prompt", return_value=False)
    assert udev.offer_install() is False
    confirm.assert_not_called()
    run.assert_not_called()


def test_offer_install_without_sudo(interactive, mocker, confirm, run):
    mocker.patch.object(udev.shutil, "which", return_value=None)
    assert udev.offer_install() is False
    confirm.assert_not_called()


def test_offer_install_as_root_does_not_need_sudo(interactive, mocker, confirm, run):
    mocker.patch.object(udev.os, "geteuid", return_value=0)
    mocker.patch.object(udev.shutil, "which", return_value=None)
    assert udev.offer_install() is True


def test_offer_install_stops_at_first_failing_command(interactive, confirm, run):
    run.side_effect = subprocess.CalledProcessError(1, "sudo")
    assert udev.offer_install() is False
    assert run.call_count == 1


def test_can_prompt_requires_a_tty(mocker):
    mocker.patch.object(udev.sys, "platform", "linux")
    mocker.patch("mpflash.config.config._interactive", True)
    mocker.patch.object(udev.sys.stdin, "isatty", return_value=False, create=True)
    assert udev._can_prompt() is False

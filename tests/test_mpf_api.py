# fmt: off

# import pytest

# mpflash APIs
# =================

def test_api_logging():
    ## logging
    # fmt: off
    from mpflash.logger import log
    assert isinstance(log, object)
    from mpflash.logger import set_loglevel
    # fmt: on

def test_api_versions():
    ## versions
    # fmt : off
    from mpflash.versions import OLDEST_VERSION
    from mpflash.versions import SET_PREVIEW
    from mpflash.versions import V_PREVIEW
    from mpflash.versions import micropython_versions
    from mpflash.versions import clean_version
    from mpflash.versions import checkedout_version
    from mpflash.versions import get_preview_mp_version
    from mpflash.versions import get_stable_mp_version
    # fmt : on

def test_api_mpflash():
    ## mpflash core
    # fmt : off
    from mpflash.connected import list_mcus
    from mpflash.list import show_mcus
    # fmt : on

def test_api_mpremoteboard():
    ## mpremoteboard
    # fmt : off
    from mpflash.mpremoteboard import ERROR
    from mpflash.mpremoteboard import OK
    from mpflash.mpremoteboard import MPRemoteBoard
    # fmt : on

def test_api_click():
    ## click extentsions
    # fmt : off
    from mpflash.vendor.click_aliases import ClickAliasedGroup
    # fmt : on

def test_api_basicgit():
    ## git
    # fmt : off
    import mpflash.basicgit as git
    from mpflash.basicgit import clone
    from mpflash.basicgit import fetch
    from mpflash.basicgit import pull
    from mpflash.basicgit import get_local_tag
    from mpflash.basicgit import get_git_describe
    from mpflash.basicgit import sync_submodules
    from mpflash.basicgit import switch_branch
    from mpflash.basicgit import switch_tag
    from mpflash.basicgit import checkout_tag
    from mpflash.basicgit import checkout_commit
    # fmt : on

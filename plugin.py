from LSP.plugin import AbstractPlugin, register_plugin, unregister_plugin, WorkspaceFolder, ClientConfig
from LSP.plugin.core.typing import Any, Optional, Dict, List

import os
import shutil

import sublime


SESSION_NAME = "clangd"
STORAGE_DIR = "LSP-clangd"
GITHUB_DL_URL = 'https://github.com/clangd/clangd/releases/download/'\
                + '{release_tag}/clangd-{platform}-{release_tag}.zip'
GITHUB_RELEASE = '15.0.1'

CLANGD_SETTING_PREFIX = "clangd."
CLANGD_SETTING_TO_ARGUMENT = {
    "number-workers": "-j"
}


def get_argument_for_setting(settings_key: str) -> str:
    """
    Returns the command argument for a `clangd.*` key.
    """
    key = settings_key[len(CLANGD_SETTING_PREFIX):]
    return CLANGD_SETTING_TO_ARGUMENT.get(key, "--" + key)


def get_settings() -> sublime.Settings:
    return sublime.load_settings("LSP-clangd.sublime-settings")


def get_clangd_settings() -> Dict[str, Any]:
    # Workaround: The 3.3 host does not provide an API to iterate over all keys.
    defaults = sublime.decode_value(sublime.load_resource("Packages/LSP-clangd/LSP-clangd.sublime-settings"))
    settings = get_settings()
    return {k: settings.get(k) for k in defaults.keys() if k.startswith(CLANGD_SETTING_PREFIX)}


class Clangd(AbstractPlugin):
    @classmethod
    def name(cls) -> str:
        return SESSION_NAME

    @classmethod
    def storage_subpath(cls) -> str:
        return os.path.join(cls.storage_path(), STORAGE_DIR)

    @classmethod
    def needs_update_or_installation(cls) -> bool:
        return shutil.which(cls.clangd_path()) is not None

    @classmethod
    def clangd_path(cls) -> str:
        # TODO: Auto-installed version
        return "clangd"

    @classmethod
    def install_or_update(cls) -> None:
        # TODO: Optionally install clangd from Github Releases
        pass

    @classmethod
    def additional_variables(cls) -> Optional[Dict[str, str]]:
        return {
            "clangd_path": cls.clangd_path()
        }

    @classmethod
    def on_pre_start(
        cls,
        window: sublime.Window,
        initiating_view: sublime.View,
        workspace_folders: List[WorkspaceFolder],
        configuration: ClientConfig,
    ) -> Optional[str]:

        # The configuration is persisted
        # reset the command to prevent adding a arguments multiple times
        configuration.command = [cls.clangd_path()]

        for settings_key, value in get_clangd_settings().items():
            if not value:
                # False or None
                continue
            elif value is True:
                configuration.command.append(get_argument_for_setting(settings_key))
            elif isinstance(value, str):
                configuration.command.append("{key}={value}".format(key=get_argument_for_setting(settings_key), value=value))
            else:
                raise TypeError("Type {} not supported for setting {}.".format(str(type(value)), settings_key))
        return None


def plugin_loaded() -> None:
    register_plugin(Clangd)


def plugin_unloaded() -> None:
    unregister_plugin(Clangd)

from LSP.plugin import AbstractPlugin, register_plugin, unregister_plugin, WorkspaceFolder, ClientConfig
from LSP.plugin.core.typing import Any, Optional, Dict, List

import os
from urllib.request import urlopen
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


def save_settings() -> None:
    return sublime.save_settings("LSP-clangd.sublime-settings")


def get_clangd_settings() -> Dict[str, Any]:
    # Workaround: The 3.3 host does not provide an API to iterate over all keys.
    defaults = sublime.decode_value(sublime.load_resource("Packages/LSP-clangd/LSP-clangd.sublime-settings"))
    settings = get_settings()
    return {k: settings.get(k) for k in defaults.keys() if k.startswith(CLANGD_SETTING_PREFIX)}


def download_file(url: str, file: str) -> None:
    with urlopen(url) as response, open(file, "wb") as out_file:
        shutil.copyfileobj(response, out_file)


def download_server(version: str, path: str):
    sublime.status_message("{}: Downloading server...".format(SESSION_NAME))
    sublime.status_message("{}: Extracting server...".format(SESSION_NAME))


class Clangd(AbstractPlugin):
    @classmethod
    def name(cls) -> str:
        return SESSION_NAME

    @classmethod
    def storage_subpath(cls) -> str:
        return os.path.join(cls.storage_path(), STORAGE_DIR)

    @classmethod
    def managed_server_binary_path(cls) -> str:
        binary_name = "clangd.exe" if sublime.platform() == "windows" else "clangd"
        return os.path.join(cls.storage_subpath(), "clangd_{version}/bin/{binary_name}".format(version=GITHUB_RELEASE, binary_name=binary_name))

    @classmethod
    def clangd_path(cls) -> Optional[str]:
        binary_setting = get_settings().get("binary")
        if binary_setting == "system":
            return shutil.which("clangd")
        elif binary_setting == "github":
            return shutil.which(cls.managed_server_binary_path())
        else:
            # binary_setting == "auto":
            return shutil.which("clangd") or shutil.which(cls.managed_server_binary_path())

    @classmethod
    def needs_update_or_installation(cls) -> bool:
        return cls.clangd_path() is not None

    @classmethod
    def install_or_update(cls) -> None:
        if get_settings().get("binary") == "system":
            ans = sublime.yes_no_cancel_dialog("clangd was not found in your path. Would you like to auto-install clangd from GitHub?")
            if ans == sublime.DIALOG_YES:
                get_settings().set("binary", "auto")
                save_settings()
            else:  # sublime.DIALOG_NO or sublime.DIALOG_CANCEL
                # fail in on_pre_start
                return

        # At this point clangd is not installed and
        # binary setting is "github" or "auto" -> perform installation

        if os.path.isdir(cls.storage_subpath()):
            shutil.rmtree(cls.storage_subpath())
        os.makedirs(cls.storage_subpath())
        download_server(GITHUB_RELEASE, cls.storage_subpath())

    @classmethod
    def on_pre_start(
        cls,
        window: sublime.Window,
        initiating_view: sublime.View,
        workspace_folders: List[WorkspaceFolder],
        configuration: ClientConfig,
    ) -> Optional[str]:

        clangd_path = cls.clangd_path()
        if not clangd_path:
            return "clangd is currently not installed."

        # The configuration is persisted
        # reset the command to prevent adding an argument multiple times
        configuration.command = [clangd_path]

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

import os
import shutil
import stat
import sys
import tempfile
import zipfile
from urllib.request import urlopen

import sublime
from LSP.plugin import (
    AbstractPlugin,
    ClientConfig,
    LspTextCommand,
    Request,
    WorkspaceFolder,
    parse_uri,
    register_plugin,
    unregister_plugin,
)
from LSP.plugin.core.typing import List, Optional
from LSP.plugin.core.views import text_document_identifier

# Fix reloading for submodules
for m in list(sys.modules.keys()):
    if m.startswith(__package__ + ".") and m != __name__:
        del sys.modules[m]

from .modules.version import CLANGD_VERSION  # noqa: E402

SESSION_NAME = "clangd"
STORAGE_DIR = "LSP-clangd"
SETTINGS_FILENAME = "LSP-clangd.sublime-settings"
GITHUB_DL_URL = 'https://github.com/clangd/clangd/releases/download/'\
                + '{release_tag}/clangd-{platform}-{release_tag}.zip'
# Options under `initializationOptions` that are prefixed with this prefix
# aren't really `initializationOptions` but get converted to command line arguments
# when this plugin starts the server.
CLANGD_SETTING_PREFIX = "clangd."
CLANGD_SETTING_TO_ARGUMENT = {
    "number-workers": "-j"
}
VERSION_STRING = ".".join(str(s) for s in CLANGD_VERSION)


def get_argument_for_setting(key: str) -> str:
    """
    Returns the command argument for a `clangd.*` key.
    """
    return CLANGD_SETTING_TO_ARGUMENT.get(key, "--" + key)


def get_settings() -> sublime.Settings:
    return sublime.load_settings(SETTINGS_FILENAME)


def save_settings() -> None:
    return sublime.save_settings(SETTINGS_FILENAME)


def clangd_download_url():
    platform = sublime.platform()
    if platform == "osx":
        platform = "mac"
    return GITHUB_DL_URL.format(release_tag=VERSION_STRING, platform=platform)


def download_file(url: str, file: str) -> None:
    with urlopen(url) as response, open(file, "wb") as out_file:
        shutil.copyfileobj(response, out_file)


def download_server(path: str):
    with tempfile.TemporaryDirectory() as tempdir:
        zip_path = os.path.join(tempdir, "server.zip")

        sublime.status_message("{}: Downloading server...".format(SESSION_NAME))
        download_file(clangd_download_url(), zip_path)

        sublime.status_message("{}: Extracting server...".format(SESSION_NAME))
        with zipfile.ZipFile(zip_path, "r") as zip_file:
            zip_file.extractall(tempdir)

        shutil.move(os.path.join(tempdir, "clangd_{version}".format(version=VERSION_STRING)), path)


class Clangd(AbstractPlugin):
    @classmethod
    def name(cls) -> str:
        return SESSION_NAME

    @classmethod
    def storage_subpath(cls) -> str:
        return os.path.join(cls.storage_path(), STORAGE_DIR)

    @classmethod
    def managed_clangd_path(cls) -> Optional[str]:
        binary_name = "clangd.exe" if sublime.platform() == "windows" else "clangd"
        path = os.path.join(cls.storage_subpath(), "clangd_{version}/bin/{binary_name}".format(version=VERSION_STRING, binary_name=binary_name))
        if os.path.exists(path):
            return path
        return None

    @classmethod
    def system_clangd_path(cls) -> Optional[str]:
        system_binary = get_settings().get("system_binary")
        # Detect if clangd is installed or the command points to a valid binary.
        # Fallback, shutil.which has issues on Windows.
        system_binary_path = shutil.which(system_binary) or system_binary
        if not os.path.isfile(system_binary_path):
            return None
        return system_binary_path

    @classmethod
    def clangd_path(cls) -> Optional[str]:
        """The command to start clangd without any configuration arguments"""
        binary_setting = get_settings().get("binary")
        if binary_setting == "system":
            return cls.system_clangd_path()
        elif binary_setting == "github":
            return cls.managed_clangd_path()
        else:
            # binary_setting == "auto":
            return cls.system_clangd_path() or cls.managed_clangd_path()

    @classmethod
    def needs_update_or_installation(cls) -> bool:
        if get_settings().get("binary") == "custom":
            return False
        return cls.clangd_path() is None

    @classmethod
    def install_or_update(cls) -> None:
        # Binary cannot be set to custom because needs_update_or_installation
        # returns False in this case
        if get_settings().get("binary") == "system":
            ans = sublime.yes_no_cancel_dialog("clangd was not found in your path. Would you like to auto-install clangd from GitHub?")
            if ans == sublime.DIALOG_YES:
                get_settings().set("binary", "auto")
                save_settings()
            else:  # sublime.DIALOG_NO or sublime.DIALOG_CANCEL
                # dont raise explicitly here
                # server start fails in on_pre_start
                return

        # At this point clangd is not installed and
        # binary setting is "github" or "auto" -> perform installation

        if os.path.isdir(cls.storage_subpath()):
            shutil.rmtree(cls.storage_subpath())
        os.makedirs(cls.storage_subpath())
        download_server(cls.storage_subpath())

        # zip does not preserve file mode
        path = cls.managed_clangd_path()
        if not path:
            # this should never happen
            raise ValueError("installation failed silently")
        st = os.stat(path)
        os.chmod(path, st.st_mode | stat.S_IEXEC)

    @classmethod
    def on_pre_start(
        cls,
        window: sublime.Window,
        initiating_view: sublime.View,
        workspace_folders: List[WorkspaceFolder],
        configuration: ClientConfig,
    ) -> Optional[str]:

        if get_settings().get("binary") == "custom":
            clangd_base_command = configuration.init_options.get("custom_command")  # type: List[str]
        else:
            clangd_path = cls.clangd_path()
            if not clangd_path:
                raise ValueError("clangd is currently not installed.")
            clangd_base_command = [clangd_path]

        # The configuration is persisted
        # reset the command to prevent adding an argument multiple times
        configuration.command = clangd_base_command.copy()

        for key, value in configuration.init_options.get("clangd").items():
            if not value:
                # False or None
                continue
            elif value is True:
                configuration.command.append(get_argument_for_setting(key))
            elif isinstance(value, str) or isinstance(value, int):
                configuration.command.append("{key}={value}".format(key=get_argument_for_setting(key), value=value))
            else:
                raise TypeError("Type {} not supported for setting {}.".format(str(type(value)), key))
        return None


class LspClangdSwitchSourceHeader(LspTextCommand):

    session_name = SESSION_NAME

    def run(self, edit):
        session = self.session_by_name(SESSION_NAME)
        if not session:
            return
        session.send_request(
            Request("textDocument/switchSourceHeader", text_document_identifier(self.view)),
            self.on_response_async,
            self.on_error_async,
        )

    def on_response_async(self, response):
        if not response:
            sublime.status_message("{}: could not determine source/header".format(self.session_name))
            return
        # session.open_uri_async(response) does currently not focus the view
        _, file_path = parse_uri(response)
        window = self.view.window()
        if not window:
            return
        window.open_file(file_path)

    def on_error_async(self, error):
        sublime.status_message("{}: could not switch to source/header: {}".format(self.session_name, error))


def plugin_loaded() -> None:
    register_plugin(Clangd)


def plugin_unloaded() -> None:
    unregister_plugin(Clangd)

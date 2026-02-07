from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import zipfile
from typing import cast, final
from typing_extensions import override
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
from LSP.plugin.core.protocol import ResponseError
from LSP.plugin.core.views import text_document_identifier
from LSP.protocol import TextDocumentIdentifier

# Fix reloading for submodules
for m in list(sys.modules.keys()):
    if m.startswith(str(__package__) + ".") and m != __name__:
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

        sublime.status_message(f"{SESSION_NAME}: Downloading server...")
        download_file(clangd_download_url(), zip_path)

        sublime.status_message(f"{SESSION_NAME}: Extracting server...")
        with zipfile.ZipFile(zip_path, "r") as zip_file:
            zip_file.extractall(tempdir)

        shutil.move(os.path.join(tempdir, f"clangd_{VERSION_STRING}"), path)


@final
class Clangd(AbstractPlugin):

    @classmethod
    @override
    def name(cls) -> str:
        return SESSION_NAME

    @classmethod
    def storage_subpath(cls) -> str:
        return os.path.join(cls.storage_path(), STORAGE_DIR)

    @classmethod
    def managed_clangd_path(cls) -> str | None:
        binary_name = "clangd.exe" if sublime.platform() == "windows" else "clangd"
        path = os.path.join(cls.storage_subpath(), "clangd_{version}/bin/{binary_name}".format(version=VERSION_STRING, binary_name=binary_name))
        if os.path.exists(path):
            return path
        return None

    @classmethod
    def system_clangd_path(cls) -> str | None:
        system_binary = cast('str', get_settings().get("system_binary"))
        # Detect if clangd is installed or the command points to a valid binary.
        # Fallback, shutil.which has issues on Windows.
        system_binary_path = shutil.which(system_binary) or system_binary
        if not os.path.isfile(system_binary_path):
            return None
        return system_binary_path

    @classmethod
    def clangd_path(cls) -> str | None:
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
    @override
    def needs_update_or_installation(cls) -> bool:
        if get_settings().get("binary") == "custom":
            return False
        return cls.clangd_path() is None

    @classmethod
    @override
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
    @override
    def on_pre_start(
        cls,
        window: sublime.Window,
        initiating_view: sublime.View,
        workspace_folders: list[WorkspaceFolder],
        configuration: ClientConfig,
    ) -> str | None:

        if get_settings().get("binary") == "custom":
            clangd_base_command = cast('list[str]', configuration.init_options.get("custom_command"))
        else:
            clangd_path = cls.clangd_path()
            if not clangd_path:
                raise ValueError("clangd is currently not installed.")
            clangd_base_command = [clangd_path]

        # The configuration is persisted
        # reset the command to prevent adding an argument multiple times
        configuration.command = clangd_base_command.copy()

        for key, value in configuration.init_options.get("clangd").items():
            if value is None:
                continue  # Use clangd default

            if isinstance(value, bool):
                value = str(value).lower()

            if isinstance(value, str) or isinstance(value, int):
                configuration.command.append("{key}={value}".format(key=get_argument_for_setting(key), value=value))
            else:
                raise TypeError(f"Type {type(value)} not supported for setting {key}.")
        return None


@final
class LspClangdSwitchSourceHeader(LspTextCommand):

    session_name = SESSION_NAME

    @override
    def run(self, edit: sublime.Edit) -> None:
        session = self.session_by_name(SESSION_NAME)
        if not session:
            return
        request: Request[TextDocumentIdentifier, str] = Request("textDocument/switchSourceHeader",
                                                                text_document_identifier(self.view))
        session.send_request(request, self.on_response_async, self.on_error_async)

    def on_response_async(self, response: str):
        if not response:
            sublime.status_message("{}: could not determine source/header".format(self.session_name))
            return
        # session.open_uri_async(response) does currently not focus the view
        _, file_path = parse_uri(response)
        window = self.view.window()
        if not window:
            return
        window.open_file(file_path)

    def on_error_async(self, error: ResponseError):
        sublime.status_message("{}: could not switch to source/header: {}".format(self.session_name, error))


def plugin_loaded() -> None:
    register_plugin(Clangd)


def plugin_unloaded() -> None:
    unregister_plugin(Clangd)

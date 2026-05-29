from __future__ import annotations

import os
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from os import PathLike
from pathlib import Path
from typing import cast, final
from urllib.request import urlopen

import sublime
from LSP.plugin import (
    ClientConfig,
    LspPlugin,
    LspTextCommand,
    OnPreStartContext,
    PluginStartError,
    Request,
    ServerResponse,
    parse_uri,
)
from LSP.plugin.core.protocol import ResponseError
from LSP.plugin.core.views import text_document_identifier
from LSP.protocol import TextDocumentIdentifier
from typing_extensions import override

# Fix reloading for submodules
for m in list(sys.modules.keys()):
    if m.startswith(str(__package__) + ".") and m != __name__:
        del sys.modules[m]

from .modules.version import CLANGD_VERSION  # noqa: E402

SETTINGS_FILENAME = "LSP-clangd.sublime-settings"
GITHUB_DL_URL = 'https://github.com/clangd/clangd/releases/download/'\
                + '{release_tag}/clangd-{platform}-{release_tag}.zip'
CLANGD_SETTING_TO_ARGUMENT = {
    "number-workers": "-j"
}
VERSION_STRING = ".".join(str(s) for s in CLANGD_VERSION)


def get_argument_for_setting(key: str) -> str:
    """
    Returns the command argument for a `clangd.*` key.
    """
    return CLANGD_SETTING_TO_ARGUMENT.get(key, "--" + key)


def set_setting_and_save(key: str, value: str) -> None:
    settings = sublime.load_settings(SETTINGS_FILENAME)
    settings.set(key, value)
    return sublime.save_settings(SETTINGS_FILENAME)


def clangd_download_url():
    platform = sublime.platform()
    if platform == "osx":
        platform = "mac"
    return GITHUB_DL_URL.format(release_tag=VERSION_STRING, platform=platform)


def download_file(url: str, file: str) -> None:
    with urlopen(url) as response, open(file, "wb") as out_file:
        shutil.copyfileobj(response, out_file)


def download_server(path: str | PathLike[str]):
    with tempfile.TemporaryDirectory() as tempdir:
        zip_path = os.path.join(tempdir, "server.zip")

        download_file(clangd_download_url(), zip_path)

        with zipfile.ZipFile(zip_path, "r") as zip_file:
            zip_file.extractall(tempdir)

        shutil.move(os.path.join(tempdir, f"clangd_{VERSION_STRING}"), path)


@final
class Clangd(LspPlugin):

    @classmethod
    @override
    def on_pre_start_async(cls, context: OnPreStartContext) -> None:
        config = context.configuration
        if config.root_settings.get("binary") == "custom":
            clangd_base_command = cast('list[str]', config.initialization_options.get("custom_command"))
        else:
            clangd_path = cls.clangd_path(config)
            if clangd_path is None:
                cls.install_clangd(config)
            clangd_path = cls.clangd_path(config)
            if clangd_path is None:
                raise PluginStartError("clangd is currently not installed")
            clangd_base_command = [str(clangd_path)]

        config.command = clangd_base_command

        for key, value in config.initialization_options.get("clangd").items():
            if value is None:
                continue  # Use clangd default

            if isinstance(value, bool):
                value = str(value).lower()

            if isinstance(value, str) or isinstance(value, int):
                config.command.append("{key}={value}".format(key=get_argument_for_setting(key), value=value))
            else:
                raise TypeError(f"[LSP-clangd] Type {type(value)} not supported for setting {key}.")

    @classmethod
    def install_clangd(cls, configuration: ClientConfig) -> None:
        # Binary cannot be set to custom because needs_update_or_installation
        # returns False in this case
        if configuration.root_settings.get("binary") == "system":
            ans = sublime.ok_cancel_dialog (
                "clangd was not found in your path. Would you like to auto-install clangd from GitHub?",
                ok_title="Install")
            if ans == sublime.DIALOG_YES:
                set_setting_and_save("binary", "auto")
            else:  # sublime.DIALOG_NO or sublime.DIALOG_CANCEL
                raise PluginStartError("clangd is currently not installed")

        # At this point clangd is not installed and
        # binary setting is "github" or "auto" -> perform installation

        if cls.plugin_storage_path.is_dir():
            shutil.rmtree(cls.plugin_storage_path)
        cls.plugin_storage_path.mkdir(parents=True)
        download_server(cls.plugin_storage_path)

        # zip does not preserve file mode
        path = cls.managed_clangd_path()
        if not path:
            # this should never happen
            raise ValueError("installation failed silently")
        st = os.stat(path)
        os.chmod(path, st.st_mode | stat.S_IEXEC)

    @classmethod
    def clangd_path(cls, configuration: ClientConfig) -> Path | None:
        """The command to start clangd without any configuration arguments"""
        binary_setting = configuration.root_settings.get("binary")
        if binary_setting == "system":
            return cls.system_clangd_path(configuration)
        if binary_setting == "github":
            return cls.managed_clangd_path()
        # binary_setting == "auto":
        return cls.system_clangd_path(configuration) or cls.managed_clangd_path()

    @classmethod
    def system_clangd_path(cls, configuration: ClientConfig) -> Path | None:
        system_binary = cast('str', configuration.root_settings.get("system_binary"))
        # Detect if clangd is installed or the command points to a valid binary.
        # Fallback, shutil.which has issues on Windows.
        system_binary_path = Path(shutil.which(system_binary) or system_binary)
        return system_binary_path if system_binary_path.is_file() else None

    @classmethod
    def managed_clangd_path(cls) -> Path | None:
        binary_name = "clangd.exe" if sublime.platform() == "windows" else "clangd"
        path = cls.plugin_storage_path / f"clangd_{VERSION_STRING}" / "bin" / binary_name
        return path if path.exists() else None

    def on_server_response_async(self, response: ServerResponse) -> None:
        if response['method'] == "textDocument/hover" and isinstance(response['result'], dict):
            contents = response['result'].get("contents")
            if isinstance(contents, dict) and contents.get("kind") == "markdown":
                content = re.sub("[ ]{2,}\n-", "\n\n-", contents["value"])
                contents["value"] = content


@final
class LspClangdSwitchSourceHeader(LspTextCommand):

    @override
    def run(self, edit: sublime.Edit) -> None:
        if session := self.session_by_name(self.session_name):
            request: Request[TextDocumentIdentifier, str] = Request("textDocument/switchSourceHeader",
                                                                    text_document_identifier(self.view))
            session.send_request(request, self.on_response_async, self.on_error_async)

    def on_response_async(self, response: str):
        if not response:
            sublime.status_message(f"{self.session_name}: could not determine source/header")
            return
        # session.open_uri_async(response) does currently not focus the view
        _, file_path = parse_uri(response)
        if window := self.view.window():
            window.open_file(file_path)

    def on_error_async(self, error: ResponseError):
        sublime.status_message(f"{self.session_name}: could not switch to source/header: {error}")


def plugin_loaded() -> None:
    Clangd.register()


def plugin_unloaded() -> None:
    Clangd.unregister()

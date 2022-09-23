from LSP.plugin import AbstractPlugin, register_plugin, unregister_plugin, WorkspaceFolder, ClientConfig
from LSP.plugin.core.typing import Optional, Dict, List

import os
import shutil

import sublime

SESSION_NAME = "clangd"
STORAGE_DIR = "LSP-clangd"


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
        # TODO: Append arguments to command depending on settings
        return None


def plugin_loaded() -> None:
    register_plugin(Clangd)


def plugin_unloaded() -> None:
    unregister_plugin(Clangd)

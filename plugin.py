from __future__ import annotations

import itertools
import os
import re
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime
from os import PathLike
from pathlib import Path
from typing import TypedDict, cast, final
from urllib.request import urlopen

import sublime
import sublime_aio
from LSP.plugin import (
    ClientConfig,
    Error,
    LspPlugin,
    LspTextCommand,
    OnPreStartContext,
    PluginStartError,
    Promise,
    Request,
    ServerResponse,
    notification_handler,
    parse_uri,
    range_to_region,
    region_to_range,
    run_coroutine,
    text_document_identifier,
)
from LSP.plugin.core.tree_view import TreeDataProvider, TreeItem, new_tree_view_sheet
from LSP.plugin.core.views import (
    entire_content_range,
    first_selection_region,
)
from LSP.protocol import DocumentUri, Range, TextDocumentIdentifier
from typing_extensions import override

SETTINGS_FILENAME = "LSP-clangd.sublime-settings"
GITHUB_DL_URL = (
    "https://github.com/clangd/clangd/releases/download/" + "{release_tag}/clangd-{platform}-{release_tag}.zip"
)
CLANGD_SETTING_TO_ARGUMENT = {"number-workers": "-j"}
CLANGD_VERSION = "23.1.0"
"""The clangd release tag. You can find them on https://github.com/clangd/clangd/releases"""
INACTIVE_REGIONS_KEY = "LSP-clangd-inactive-regions"


class FileStatus(TypedDict):
    """Sent when the current activity for a file changes. Replaces previous activity for that file."""

    uri: DocumentUri
    """The text document's URI."""
    state: str
    """The human-readable state of the file, for example "parsing includes" or "idle"."""


class InactiveRegions(TypedDict):
    textDocument: TextDocumentIdentifier
    """The document whose status is being updated."""
    regions: list[Range]
    """An array of ranges that are inactive."""


class ASTNode(TypedDict):
    role: str
    """
    The general kind of node, such as “expression”. Corresponds to clang’s base AST node type, such as Expr. The most
    common are “expression”, “statement”, “type” and “declaration”.
    """
    kind: str
    """
    The specific kind of node, such as “BinaryOperator”. Corresponds to clang’s concrete node class, with Expr etc
    suffix dropped.
    """
    detail: str | None
    """Brief additional details, such as ‘||’. Information present here depends on the node kind."""
    arcana: str | None
    """
    One line dump of information, similar to that printed by `clang -Xclang -ast-dump`. Only available for certain types
    of nodes.
    """
    range: Range | None
    """
    The part of the code that produced this node. Missing for implicit nodes, nodes produced by macro expansion, etc.
    """
    children: list["ASTNode"] | None
    """
    Descendants describing the internal structure. The tree of nodes is similar to that printed by
    `clang -Xclang -ast-dump`, or that traversed by `clang::RecursiveASTVisitor`.
    """


class MemoryTree(TypedDict):
    _total: int
    """Number of bytes used, including child components."""
    _self: int
    """Number of bytes used, excluding child components."""
    _name: str
    """Custom client property to store the name of this node."""


def get_argument_for_setting(key: str) -> str:
    """
    Returns the command argument for a `clangd.*` key.
    """
    return CLANGD_SETTING_TO_ARGUMENT.get(key, "--" + key)


def set_setting_and_save(key: str, value: str) -> None:
    settings = sublime.load_settings(SETTINGS_FILENAME)
    settings.set(key, value)
    return sublime.save_settings(SETTINGS_FILENAME)


def project_lsp_settings(window: sublime.Window | None, config_name: str) -> tuple[dict, dict] | None:
    """Returns the project data and the config overrides within it, if the project defines any."""
    project_data = window.project_data() if window else None
    if not isinstance(project_data, dict):
        return None
    settings = project_data.get("settings")
    lsp_settings = settings.get("LSP") if isinstance(settings, dict) else None
    overrides = lsp_settings.get(config_name) if isinstance(lsp_settings, dict) else None
    return (project_data, overrides) if isinstance(overrides, dict) else None


def get_project_lsp_setting(window: sublime.Window | None, config_name: str, key: str) -> bool:
    project_settings = project_lsp_settings(window, config_name)
    return project_settings is not None and key in project_settings[1]


def set_project_lsp_setting_and_save(window: sublime.Window, config_name: str, key: str, value: str) -> None:
    project_settings = project_lsp_settings(window, config_name)
    if project_settings is None:
        return
    project_data, overrides = project_settings
    overrides[key] = value
    window.set_project_data(project_data)


def clangd_download_url():
    platform = sublime.platform()
    if platform == "osx":
        platform = "mac"
    return GITHUB_DL_URL.format(release_tag=CLANGD_VERSION, platform=platform)


def download_file(url: str, file: str) -> None:
    with urlopen(url) as response, open(file, "wb") as out_file:
        shutil.copyfileobj(response, out_file)


def download_server(path: str | PathLike[str]):
    with tempfile.TemporaryDirectory() as tempdir:
        zip_path = os.path.join(tempdir, "server.zip")

        download_file(clangd_download_url(), zip_path)

        with zipfile.ZipFile(zip_path, "r") as zip_file:
            zip_file.extractall(tempdir)

        shutil.move(os.path.join(tempdir, f"clangd_{CLANGD_VERSION}"), path)


@final
class Clangd(LspPlugin):
    @classmethod
    @override
    def on_pre_start_async(cls, context: OnPreStartContext) -> None:
        config = context.configuration
        if config.root_settings.get("binary") == "custom":
            clangd_base_command = cast("list[str]", config.initialization_options.get("custom_command"))
        else:
            clangd_path = cls.clangd_path(config)
            if clangd_path is None:
                cls.install_clangd(config, context.view.window())
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
    def install_clangd(cls, configuration: ClientConfig, window: sublime.Window | None) -> None:
        # Binary cannot be set to custom because needs_update_or_installation
        # returns False in this case
        if configuration.root_settings.get("binary") == "system":
            in_project = get_project_lsp_setting(window, configuration.name, "binary")
            settings_location = "project settings" if in_project else "LSP-clangd settings"
            answer = sublime.ok_cancel_dialog(
                "clangd was not found in your path. Would you like to auto-install clangd from GitHub?\n\n"
                f"The \"binary\" setting will be changed to \"auto\" in the {settings_location}.",
                ok_title="Install")
            if not answer:
                raise PluginStartError("clangd is currently not installed")
            if window and in_project:
                set_project_lsp_setting_and_save(window, configuration.name, "binary", "auto")
            else:
                set_setting_and_save("binary", "auto")

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
        system_binary = cast("str", configuration.root_settings.get("system_binary"))
        # Detect if clangd is installed or the command points to a valid binary.
        # Fallback, shutil.which has issues on Windows.
        system_binary_path = Path(shutil.which(system_binary) or system_binary)
        return system_binary_path if system_binary_path.is_file() else None

    @classmethod
    def managed_clangd_path(cls) -> Path | None:
        binary_name = "clangd.exe" if sublime.platform() == "windows" else "clangd"
        path = cls.plugin_storage_path / f"clangd_{CLANGD_VERSION}" / "bin" / binary_name
        return path if path.exists() else None

    async def on_server_response(self, response: ServerResponse) -> None:
        if response["method"] == "textDocument/hover" and isinstance(response["result"], dict):
            contents = response["result"].get("contents")
            if isinstance(contents, dict) and contents.get("kind") == "markdown":
                content = re.sub("[ ]{2,}\n-", "\n\n-", contents["value"])
                contents["value"] = content

    @notification_handler("textDocument/clangd.fileStatus")
    def on_file_status(self, params: FileStatus) -> None:
        if (session := self.weaksession()) and (sb := session.get_session_buffer_for_uri_async(params["uri"])):
            state = "" if params["state"] == "idle" else params["state"]
            for session_view in sb.session_views:
                session.config.set_view_status(session_view.view, state)

    @notification_handler("textDocument/inactiveRegions")
    def on_inactive_regions(self, inactive: InactiveRegions) -> None:
        if (session := self.weaksession()) and (
            sb := session.get_session_buffer_for_uri_async(inactive["textDocument"]["uri"])
        ):
            regions: list[sublime.Region] | None = None
            annotations: list[str] | None = None
            for sv in sb.session_views:
                if regions is None:
                    regions = list(
                        itertools.chain.from_iterable(
                            sv.view.split_by_newlines(r1)
                            for r1 in iter(range_to_region(sv.view, r0) for r0 in inactive["regions"])
                        )
                    )
                    annotations = ["inactive"] * len(regions)
                sv.view.add_regions(
                    INACTIVE_REGIONS_KEY,
                    regions,
                    annotations=annotations or [],
                    annotation_color="region.yellowish",
                )


@final
class LspClangdSwitchSourceHeader(LspTextCommand):
    @override
    def run(self, edit: sublime.Edit) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        run_coroutine(self._run())

    async def _run(self) -> None:
        session = self.session_by_name(self.session_name)
        if not session:
            return
        response: str | Error = await session.request(
            Request(
                "textDocument/switchSourceHeader", text_document_identifier(self.view), view=self.view, progress=True
            )
        )
        if isinstance(response, Error):
            return await sublime_aio.error_message(f"Error determining source/header: {response}")
        if not response:
            sublime.status_message(f"{self.session_name}: could not determine source/header")
            return
        # session.open_uri_async(response) does currently not focus the view
        _, file_path = parse_uri(response)
        if window := self.view.window():
            window.open_file(file_path)


def ast_kind_to_st_kind(kind: str) -> sublime.Kind:
    # TODO
    return sublime.KIND_AMBIGUOUS


@final
class ASTNodeTreeModel(TreeDataProvider):
    _root: ASTNode

    def __init__(self, view: sublime.View, root: ASTNode) -> None:
        self._view = view
        self._root = root

    @override
    def get_children(self, element: ASTNode | None) -> Promise[list[ASTNode]]:
        if element is None:
            element = self._root
        return Promise.resolve(element.get("children") or [])

    @override
    def get_tree_item(self, element: ASTNode) -> TreeItem:
        if range := element.get("range"):
            description = f"Line {range['start']['line'] + 1}, Column {range['start']['character'] + 1}"
        elif arcana := element["arcana"]:
            description = arcana
        else:
            description = ""
        return TreeItem(
            label=element["kind"],
            kind=ast_kind_to_st_kind(element["kind"]),
            description=description,
        )


@final
class LspClangdViewSyntaxTree(LspTextCommand):
    capability = "astProvider"

    @override
    def want_event(self) -> bool:
        return False

    def run(self, edit: sublime.Edit) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        run_coroutine(self._run())

    async def _run(self) -> None:
        session = self.session_by_name(self.session_name)
        if not session:
            print(f"no session with name {self.session_name}")
            return
        region = first_selection_region(self.view)
        now = datetime.now().strftime("%H:%M:%S")
        response: ASTNode | Error = await session.request(
            Request(
                "textDocument/ast",
                {
                    "textDocument": text_document_identifier(self.view),
                    "range": entire_content_range(self.view)
                    if not region or region.empty()
                    else region_to_range(self.view, region),
                },
                view=self.view,
                progress=True,
            )
        )
        if isinstance(response, Error):
            sublime.error_message(f"Error loading syntax tree: {response}")
            return
        window = self.view.window()
        if not window:
            return
        name = f"Syntax Tree of {self.view.file_name()}"
        new_tree_view_sheet(
            window=window,
            name=name,
            data_provider=ASTNodeTreeModel(self.view, response),
            header=f"{name} (retrieved: {now})",
        )


def convert_size(size_bytes: int | float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    raise OverflowError("gigantic byte size")


@final
class MemoryUsageTreeModel(TreeDataProvider):
    _root: MemoryTree

    @classmethod
    def from_memory_tree(cls, memory_tree: MemoryTree) -> "MemoryUsageTreeModel":
        cls._process_memory_tree_recursive("root", memory_tree)
        return MemoryUsageTreeModel(memory_tree)

    @classmethod
    def _process_memory_tree_recursive(cls, name: str, node: MemoryTree) -> None:
        node["_name"] = name if not name.startswith("file:") else parse_uri(name)[1]
        for name, child in node.items():
            if not name.startswith("_") and isinstance(child, dict):
                cls._process_memory_tree_recursive(name, cast("MemoryTree", child))

    def __init__(self, root: MemoryTree) -> None:
        self._root = root

    @override
    def get_children(self, element: MemoryTree | None) -> Promise[list[MemoryTree]]:
        if element is None:
            element = self._root
        return Promise.resolve([v for k, v in element.items() if not k.startswith("_")])  # pyright: ignore[reportReturnType]

    @override
    def get_tree_item(self, element: MemoryTree) -> TreeItem:
        return TreeItem(
            label=element["_name"],
            kind=sublime.KIND_AMBIGUOUS,
            description=f"self: {convert_size(element['_self'])}, total: {convert_size(element['_total'])}",
        )


@final
class LspClangdMemoryUsage(LspTextCommand):
    capability = "memoryUsageProvider"

    @override
    def want_event(self) -> bool:
        return False

    def run(self, edit: sublime.Edit) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        run_coroutine(self._run())

    async def _run(self) -> None:
        session = self.session_by_name(self.session_name)
        if not session:
            return
        response: MemoryTree | Error = await session.request(Request("$/memoryUsage", view=self.view, progress=True))
        if isinstance(response, Error):
            sublime.error_message(f"Error loading memory usage: {response}")
            return
        window = self.view.window()
        if not window:
            return
        new_tree_view_sheet(
            window=window,
            name=f"{self.session_name}-memory-usage",
            data_provider=MemoryUsageTreeModel.from_memory_tree(response),
            header=f"{self.session_name} memory usage",
        )


plugin_loaded = Clangd.register
plugin_unloaded = Clangd.unregister

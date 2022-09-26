# LSP-clangd
C++ support for Sublime's LSP plugin provided through clangd.

## Installation
- Install LSP and LSP-clangd from Package Control
- Install clangd using your package manager or let this plugin install clangd for you

## Usage

By default, clangd will assume your code is built as clang some_file.cc, and you’ll probably get errors about missing #included files, etc. 

For complex projects clangd needs to know your build flags. This can be done using a `compile_commands.json` or `compile_flags.txt` file.

For CMake-based projects a `compile_commands.json` file can be generated using the `-DCMAKE_EXPORT_COMPILE_COMMANDS=1` flag.
```bash
cd build
cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=1 ..
# compile_commands.json will be written to your build directory.
```
If your build directory is $SRC or $SRC/build, clangd will find it. Otherwise, symlink or copy it to $SRC, the root of your source tree.

See [clangd website](https://clangd.llvm.org/installation#project-setup) for instructions using other build systems.

## Sublime Commands

| Sublime Command                 | Description                                                 |
| ------------------------------- | ----------------------------------------------------------- |
| lsp_clangd_switch_source_header | Switch between the main source file (.cpp) and header (.h). |
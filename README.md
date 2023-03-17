# LSP-clangd

C/C++ and Objective-C/C++ support for Sublime's LSP plugin provided through clangd.

## Installation

- Install [LSP](https://packagecontrol.io/packages/LSP) and `LSP-clangd` from Package Control
- (Optional) Install clangd using your package manager or let this package install clangd for you

## Usage

By default, clangd will assume your code is built as `clang some_file.cc`, and you’ll probably get errors about missing `#include`d files, etc.

For complex projects, clangd needs to know your build flags. This can be done using a `compile_commands.json` or `compile_flags.txt` file.

For CMake-based projects a `compile_commands.json` file can be generated using the `-DCMAKE_EXPORT_COMPILE_COMMANDS=1` flag.

```bash
cd build
cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=1 ..
# compile_commands.json will be written to your build directory.
```

If your build directory is equivalent to the root of the project or `<project_root>/build` then clangd will find it. Otherwise, symlink or copy it to the root of your project.

> See [clangd Project Setup](https://clangd.llvm.org/installation#project-setup) for more information on using `compile_commands.json`, `compile_flags.txt` and other build systems.

## Configuration

Here are some ways to configure the package and the language server.

- From `Preferences > Package Settings > LSP > Servers > LSP-clangd`
- From the command palette: `Preferences: LSP-clangd Settings`
- Project-specific configuration.
  From the command palette run `Project: Edit Project` and add your settings in:

  ```js
  {
     "settings": {
        "LSP": {
           "clangd": {
              "initializationOptions": {
                // Put your settings here eg.
                // "clangd.header-insertion": "iwyu",
              }
           }
        }
     }
  }
  ```

## Sublime Commands

| Sublime Command                 | Description                                                 |
| ------------------------------- | ----------------------------------------------------------- |
| `lsp_clangd_switch_source_header` | Switch between the main source file (.cpp) and header (.h). |

#include <iostream>

#include "greeter.hpp"

int main() {
    sample::Greeter greeter("clangd");
    std::cout << greeter.greet() << '\n';

    // Type `greeter.` below to test completions, hover `greet` for docs.

    // Uncomment to check diagnostics:
    // int unused = undefined_symbol;

    return 0;
}

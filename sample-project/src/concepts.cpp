// Semantic tokens for C++20 concepts.
//
// With "semantic_highlighting" enabled in the LSP settings, put the caret on a concept name and run
// "Show Scope Name" from the command palette. The expected scopes are noted next to each usage. Besides the noted
// modifiers, clangd also reports the "globalScope" modifier on all of them.

#include <concepts>
#include <string>

namespace sample {

// Concept definition: "concept" token with the "declaration" modifier.
// Expected scope: entity.name.type.concept.lsp meta.semantic-token.concept.declaration.lsp
template <typename T>
concept Greetable = requires(const T& value) {
    // Concepts from the standard library (also std::integral below) have the "defaultLibrary" modifier.
    // Expected scope: support.type.concept.lsp meta.semantic-token.concept.defaultlibrary.lsp
    { value.greet() } -> std::convertible_to<std::string>;
};

// The remaining usages of Greetable are "concept" tokens without other modifiers.
// Expected scope: storage.type.concept.lsp meta.semantic-token.concept.globalscope.lsp

// In a template parameter list.
template <Greetable T>
std::string greet_once(const T& value) {
    return value.greet();
}

// In a requires clause.
template <typename T>
    requires Greetable<T>
std::string greet_twice(const T& value) {
    return value.greet() + value.greet();
}

// As a constrained placeholder type, including a concept from the standard library.
std::string greet_abbreviated(const Greetable auto& value, std::integral auto times) {
    std::string result;
    for (decltype(times) i = 0; i < times; ++i) {
        result += value.greet();
    }
    return result;
}

// As a boolean expression.
template <typename T>
constexpr bool is_greetable = Greetable<T>;

struct Silent {};

static_assert(!is_greetable<Silent>);

}  // namespace sample

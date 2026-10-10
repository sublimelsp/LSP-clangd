#include "greeter.hpp"

#include <utility>

namespace sample {

Greeter::Greeter(std::string name) : name_(std::move(name)) {}

std::string Greeter::greet() const {
    return greet("Hello");
}

std::string Greeter::greet(const std::string& greeting) const {
    return greeting + ", " + name_ + "!";
}

std::string Greeter::greet(const std::string& greeting, int times) const {
    std::string result;
    for (int i = 0; i < times; ++i) {
        result += greet(greeting) + "\n";
    }
    return result;
}

}  // namespace sample

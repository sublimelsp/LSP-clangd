#pragma once

#include <string>

namespace sample {

class Greeter {
public:
    explicit Greeter(std::string name);

    /// Returns a greeting for the stored name.
    std::string greet() const;

    /// Overloads to check completion style (detailed vs bundled).
    std::string greet(const std::string& greeting) const;
    std::string greet(const std::string& greeting, int times) const;

private:
    std::string name_;
};

}  // namespace sample

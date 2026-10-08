#pragma once
// Width-stable Win32/MSVCR integer conversion helpers.
//
// Windows x86 "long" and "unsigned long" are 32-bit even when the host
// compiling ReflexRecomp has 64-bit long. The C library's strtoll/strtoull
// helpers are used solely to lex the input; the result is explicitly
// saturated / reduced to Win32's 32-bit return width.
//
// No guest memory or host FILE* is touched here, which permits a fast native
// unit test outside the private translated game.
#include <cctype>
#include <cerrno>
#include <climits>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <string>

namespace reflex_crt {

struct IntegerParse {
    uint32_t value = 0;
    size_t consumed = 0;
};

inline bool valid_base(int base) {
    return base == 0 || (base >= 2 && base <= 36);
}

inline IntegerParse parse_signed32(const std::string &text, int base) {
    if (!valid_base(base))
        return {};
    errno = 0;
    char *end = nullptr;
    const long long parsed = std::strtoll(text.c_str(), &end, base);
    const size_t consumed = end > text.c_str()
        ? static_cast<size_t>(end - text.c_str()) : 0;
    // Compare the parsed value, not the sign of errno. On ERANGE the host
    // returns LLONG_MIN for a negative overflow and LLONG_MAX otherwise.
    const int32_t narrowed = parsed < static_cast<long long>(INT32_MIN)
        ? INT32_MIN
        : parsed > static_cast<long long>(INT32_MAX)
            ? INT32_MAX
            : static_cast<int32_t>(parsed);
    return {static_cast<uint32_t>(narrowed), consumed};
}

inline IntegerParse parse_unsigned32(const std::string &text, int base) {
    if (!valid_base(base))
        return {};
    const char *first = text.c_str();
    const char *digits = first;
    while (*digits && std::isspace(static_cast<unsigned char>(*digits)))
        ++digits;
    const bool negative = *digits == '-';
    if (negative)
        ++digits;

    errno = 0;
    char *end = nullptr;
    const unsigned long long magnitude =
        std::strtoull(negative ? digits : first, &end, base);
    // Inputs with no conversion ("-", "-xyz") must leave endptr at
    // the original string even if whitespace/sign characters were read.
    const char *parse_start = negative ? digits : first;
    if (end == parse_start)
        return {};
    const size_t consumed = static_cast<size_t>(end - first);
    if (errno == ERANGE || magnitude > UINT32_MAX)
        return {UINT32_MAX, consumed};
    const uint32_t value = static_cast<uint32_t>(magnitude);
    // MSVCR's unsigned 32-bit strtoul accepts a leading minus and negates
    // the *32-bit* magnitude, not the host's 64-bit ULONG value.
    return {negative ? (uint32_t{0} - value) : value, consumed};
}

} // namespace reflex_crt

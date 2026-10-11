#pragma once
// Bounded MSVCR90 swprintf_s formatting on the guest's UTF-16LE arena.
// Host wchar_t is 32 bits on Linux/macOS; never pass guest data to host swprintf.
// This helper does not require the translated game or host import dispatcher.
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>

namespace reflex_crt {

inline int guest_swprintf_s(uint8_t *memory, uint32_t arena_size,
                           uint32_t dst, uint32_t capacity,
                           uint32_t fmt, uint32_t varargs) {
    const auto valid = [arena_size](uint64_t at, uint64_t bytes) {
        return at != 0 && at < arena_size && bytes <= arena_size - at;
    };
    const auto rd16 = [memory](uint32_t at) {
        uint16_t v;
        std::memcpy(&v, memory + at, 2);
        return v;
    };
    const auto rd32 = [memory](uint32_t at) {
        uint32_t v;
        std::memcpy(&v, memory + at, 4);
        return v;
    };
    const auto clear = [&]() {
        if (memory && valid(dst, 2))
            std::memset(memory + dst, 0, 2);
        return -1;
    };
    // Limit pathological format expansion independently of the guest buffer.
    constexpr uint32_t kMaxChars = 32768;
    constexpr uint32_t kMaxField = 4096;
    if (!memory || !capacity || capacity > kMaxChars + 1 ||
        !valid(dst, uint64_t(capacity) * 2) || !valid(fmt, 2))
        return clear();

    std::u16string output;
    uint64_t ap = varargs;
    const auto next_arg = [&](uint32_t &value) {
        if (!valid(ap, 4))
            return false;
        value = rd32(static_cast<uint32_t>(ap));
        ap += 4;
        return true;
    };
    const auto append = [&](const std::u16string &part) {
        if (part.size() > kMaxChars - output.size())
            return false;
        output += part;
        return true;
    };
    uint64_t at = fmt;
    bool terminated = false;
    for (uint32_t steps = 0; steps < kMaxField; ++steps) {
        if (!valid(at, 2))
            return clear();
        const char16_t ch = static_cast<char16_t>(rd16(static_cast<uint32_t>(at)));
        at += 2;
        if (!ch) {
            terminated = true;
            break;
        }
        if (ch != u'%') {
            if (!append(std::u16string(1, ch)))
                return clear();
            continue;
        }
        if (!valid(at, 2))
            return clear();
        char16_t spec = static_cast<char16_t>(rd16(static_cast<uint32_t>(at)));
        if (spec == u'%') {
            at += 2;
            if (!append(u"%"))
                return clear();
            continue;
        }
        bool left = false, zero = false, plus = false, space = false, alternate = false;
        while (spec == u'-' || spec == u'0' || spec == u'+' ||
               spec == u' ' || spec == u'#') {
            if (spec == u'-') left = true;
            if (spec == u'0') zero = true;
            if (spec == u'+') plus = true;
            if (spec == u' ') space = true;
            if (spec == u'#') alternate = true;
            at += 2;
            if (!valid(at, 2)) return clear();
            spec = static_cast<char16_t>(rd16(static_cast<uint32_t>(at)));
        }
        uint32_t width = 0;
        while (spec >= u'0' && spec <= u'9') {
            width = width * 10 + (spec - u'0');
            if (width > kMaxField) return clear();
            at += 2;
            if (!valid(at, 2)) return clear();
            spec = static_cast<char16_t>(rd16(static_cast<uint32_t>(at)));
        }
        bool has_precision = false;
        uint32_t precision = 0;
        if (spec == u'.') {
            has_precision = true;
            at += 2;
            if (!valid(at, 2)) return clear();
            spec = static_cast<char16_t>(rd16(static_cast<uint32_t>(at)));
            while (spec >= u'0' && spec <= u'9') {
                precision = precision * 10 + (spec - u'0');
                if (precision > kMaxField) return clear();
                at += 2;
                if (!valid(at, 2)) return clear();
                spec = static_cast<char16_t>(rd16(static_cast<uint32_t>(at)));
            }
        }
        bool narrow = false, wide = false, integer64 = false;
        if (spec == u'h' || spec == u'l' || spec == u'w') {
            narrow = spec == u'h';
            wide = !narrow;
            at += 2;
            if (!valid(at, 2)) return clear();
            char16_t next = static_cast<char16_t>(rd16(static_cast<uint32_t>(at)));
            if (spec == u'l' && next == u'l') {
                integer64 = true;
                at += 2;
                if (!valid(at, 2)) return clear();
                next = static_cast<char16_t>(rd16(static_cast<uint32_t>(at)));
            }
            spec = next;
        } else if (spec == u'I') {
            if (!valid(at + 2, 4) || rd16(static_cast<uint32_t>(at + 2)) != u'6' ||
                rd16(static_cast<uint32_t>(at + 4)) != u'4')
                return clear();
            integer64 = true;
            at += 6;
            if (!valid(at, 2)) return clear();
            spec = static_cast<char16_t>(rd16(static_cast<uint32_t>(at)));
        }
        at += 2;
        std::u16string piece;
        bool numeric = false;
        if (spec == u's' || spec == u'S') {
            uint32_t ptr = 0;
            if (!next_arg(ptr) || !ptr) return clear();
            // MSVCR wide printf: %s/%ls -> UTF-16, %S/%hs -> narrow.
            const bool bytes = narrow || (spec == u'S' && !wide);
            const uint32_t limit = has_precision ? precision : kMaxField;
            bool ended = false;
            for (uint32_t i = 0; i < limit; ++i) {
                const uint64_t addr = uint64_t(ptr) + uint64_t(i) * (bytes ? 1u : 2u);
                if (!valid(addr, bytes ? 1u : 2u)) return clear();
                const char16_t value = bytes
                    ? static_cast<char16_t>(memory[addr])
                    : static_cast<char16_t>(rd16(static_cast<uint32_t>(addr)));
                if (!value) { ended = true; break; }
                piece.push_back(value);
            }
            if (!has_precision && !ended) return clear();
        } else if (spec == u'c' || spec == u'C') {
            uint32_t value = 0;
            if (!next_arg(value)) return clear();
            piece.push_back(static_cast<char16_t>(value & 0xffffu));
        } else if (spec == u'd' || spec == u'i' || spec == u'u' ||
                   spec == u'x' || spec == u'X' || spec == u'o' || spec == u'p') {
            numeric = true;
            uint32_t low = 0, high = 0;
            if (!next_arg(low) || (integer64 && !next_arg(high))) return clear();
            const uint64_t bits = uint64_t(low) | (uint64_t(high) << 32);
            const bool signed_decimal = spec == u'd' || spec == u'i';
            const int64_t signed_value = integer64
                ? static_cast<int64_t>(bits)
                : static_cast<int32_t>(low);
            const bool negative = signed_decimal && signed_value < 0;
            uint64_t magnitude = negative ? uint64_t(-(signed_value + 1)) + 1u
                : signed_decimal ? uint64_t(signed_value)
                : integer64 ? bits : uint64_t(low);
            const uint32_t base = (spec == u'x' || spec == u'X' || spec == u'p')
                ? 16u : (spec == u'o' ? 8u : 10u);
            std::u16string digits;
            do {
                const uint32_t d = magnitude % base;
                digits.push_back(static_cast<char16_t>(
                    d < 10 ? u'0' + d : (spec == u'X' ? u'A' : u'a') + d - 10));
                magnitude /= base;
            } while (magnitude);
            std::reverse(digits.begin(), digits.end());
            if (has_precision && precision == 0 && bits == 0)
                digits.clear();
            if (has_precision && precision > digits.size())
                digits.insert(digits.begin(), precision - digits.size(), u'0');
            std::u16string prefix;
            if (negative) prefix = u"-";
            else if (signed_decimal && plus) prefix = u"+";
            else if (signed_decimal && space) prefix = u" ";
            if ((alternate && bits != 0 && (spec == u'x' || spec == u'X')) ||
                spec == u'p')
                prefix += (spec == u'X' ? u"0X" : u"0x");
            if (alternate && spec == u'o' && (digits.empty() || digits[0] != u'0'))
                prefix += u"0";
            if (zero && !left && !has_precision && width > prefix.size() + digits.size())
                digits.insert(digits.begin(), width - prefix.size() - digits.size(), u'0');
            piece = prefix + digits;
        } else {
            // Fail rather than silently fabricate unsupported MSVC printf output.
            return clear();
        }
        if (piece.size() < width) {
            const std::u16string fill(width - piece.size(), u' ');
            if (left) piece += fill;
            else piece = fill + piece;
        }
        (void)numeric;
        if (!append(piece))
            return clear();
    }
    if (!terminated || output.size() >= capacity ||
        output.size() > static_cast<size_t>(std::numeric_limits<int>::max()))
        return clear();
    for (size_t i = 0; i < output.size(); ++i) {
        const uint16_t value = static_cast<uint16_t>(output[i]);
        std::memcpy(memory + dst + i * 2u, &value, 2);
    }
    std::memset(memory + dst + output.size() * 2u, 0, 2);
    return static_cast<int>(output.size());
}
}  // namespace reflex_crt

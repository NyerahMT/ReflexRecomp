#pragma once
// Microsoft Visual C++ 2008 _exit(int) is a non-returning, no-atexit exit.
// Keep the host logic separate so it can be validated without guest assets.
// Do not replace this with exit(), which runs CRT handlers, or a stub that
// resumes guest code after it has requested process termination.
#include <cstdint>
#include <cstdlib>
namespace reflex_crt {
[[noreturn]] inline void quick_exit(uint32_t code) {
    std::_Exit(static_cast<int>(code));
}
} // namespace reflex_crt

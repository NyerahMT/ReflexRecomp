#ifndef REFLEX_PACKED_SSE_H
#define REFLEX_PACKED_SSE_H
#include "x86.h"
#ifdef __cplusplus
extern "C" {
#endif
/* Execute a verified 32-bit x86 packed-single instruction from guest code.
 * Unsupported opcode or addressing mode fails explicitly, never silently. */
void reflex_packed_sse(X86 *cpu, uint32_t guest_pc);
#ifdef __cplusplus
}
#endif
#endif

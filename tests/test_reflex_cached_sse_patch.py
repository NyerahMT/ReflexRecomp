"""Regression tests for exact-address patches to Reflex's cached translation.

No game data is needed: private generated chunks are represented by a tiny
synthetic C fixture containing only the known uncompilable trap statements.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "patch_reflex_cached_sse.py"
SPEC = importlib.util.spec_from_file_location("reflex_cached_sse", SCRIPT)
patcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patcher)


class CachedSsePatchTests(unittest.TestCase):
    TRAPS = (
        "0x007b6d4fu",
        "0x007b34d4u",
        "0x007b350au",
        "0x00784eecu",
    )
    PATCHES = (
        patcher.patch_generated_sse,
        patcher.patch_cached_mulps,
        patcher.patch_cached_mulps_reg,
        patcher.patch_cached_cvtps2pd,
    )

    def _fixture(self, directory):
        chunk = directory / "chunk_0000.c"
        chunk.write_text("void x(X86 *c) {\n" + "".join(
            f"    recomp_unmodelled(c, {a}); return;\n" for a in self.TRAPS
        ) + "}\n")
        return chunk

    def test_all_known_traps_replaced_and_idempotent(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            chunk = self._fixture(root)
            for patch in self.PATCHES:
                self.assertEqual(patch(root), chunk)
                self.assertEqual(patch(root), chunk)
            generated = chunk.read_text()
            for address in self.TRAPS:
                self.assertNotIn(f"recomp_unmodelled(c, {address})", generated)
            self.assertIn("Reflex CVTPD2PS 007b6d4f", generated)
            self.assertIn("Reflex MULPS 007b34d4", generated)
            self.assertIn("Reflex MULPS 007b350a", generated)
            self.assertIn("Reflex CVTPS2PD 00784eec", generated)
            self.assertIn("const double reflex_pd1", generated)
            self.assertIn("c->xmm[1][3] = 0;", generated)

    def test_missing_address_fails_closed(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            chunk = self._fixture(root)
            chunk.write_text(chunk.read_text().replace(
                "recomp_unmodelled(c, 0x00784eecu); return;", ""
            ))
            with self.assertRaisesRegex(RuntimeError, "exactly one CVTPS2PD trap"):
                patcher.patch_cached_cvtps2pd(root)

    def test_duplicate_address_fails_closed(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            chunk = self._fixture(root)
            chunk.write_text(chunk.read_text() +
                             "recomp_unmodelled(c, 0x007b34d4u); return;\n")
            with self.assertRaisesRegex(RuntimeError, "exactly one MULPS translation trap"):
                patcher.patch_cached_mulps(root)


if __name__ == "__main__":
    unittest.main()

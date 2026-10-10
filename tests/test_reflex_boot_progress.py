import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "check_reflex_boot_progress.py"
SPEC = importlib.util.spec_from_file_location("reflex_boot_progress", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def sample(count, name, result=-1):
    return (f'[reflex-stricmp] call={count} ret=0084a8f0 '
            f'lhs=021d5b40 "Intro.ENG" rhs=0efff730 "{name}" '
            f'rc={result} esi=021d4bb0 edi=00000014')


class BootProgressTests(unittest.TestCase):
    def test_classifies_persistent_intro_miss_as_stalled(self):
        log = "\n".join(sample(2 ** i, "Intro" if i % 2 else "Intro.")
                        for i in range(2, 22))
        result = module.classify_log(log)
        self.assertEqual(result.status, "ui_lookup_stalled")
        self.assertGreaterEqual(result.comparisons, 1_000_000)

    def test_guest_failure_after_intro_match_is_not_success(self):
        log = "\n".join([
            sample(256, "Intro.ENG", 0),
            "[reflex-intro-probe] exact Intro. -> Intro.ENG match count=1",
            "[recomp] TerminateProcess(3221226505)",
            "[recomp] guest process exited with code 3221226505",
        ])
        result = module.classify_log(log)
        self.assertEqual(result.status, "guest_terminated")
        self.assertEqual(result.comparisons, 256)
        self.assertIn("0xc0000409", result.reason)

    def test_does_not_fail_legitimate_resource_lookups(self):
        log = "\n".join(sample(2 ** i, "Intro.ENG", 0)
                        for i in range(2, 22))
        self.assertEqual(module.classify_log(log).status, "not_stalled")

    def test_does_not_fail_low_volume_lookups(self):
        log = "\n".join(sample(2 ** i, "Intro") for i in range(2, 17))
        self.assertEqual(module.classify_log(log).status, "not_stalled")

    def test_does_not_fail_absent_samples(self):
        self.assertEqual(module.classify_log("booted").status, "unknown")

    def test_tail_must_be_consistently_unresolved(self):
        log = "\n".join(sample(2 ** i, "Intro" if i % 2 else "Intro.")
                        for i in range(2, 22))
        log += "\n" + sample(2 ** 22, "Gameplay.ENG", 0)
        log += "\n" + sample(2 ** 23, "FrontEnd.ENG", 0)
        log += "\n" + sample(2 ** 24, "Race.ENG", 0)
        self.assertEqual(module.classify_log(log).status, "not_stalled")


if __name__ == "__main__":
    unittest.main()

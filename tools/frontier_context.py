#!/usr/bin/env python3
"""Print a tiny private-listing context around one or more guest addresses."""

from pathlib import Path
import argparse
import csv
import re

ROOT = Path(__file__).resolve().parents[1]

LINE_RE = re.compile(r"^([0-9A-Fa-f]{8})\s{2}(.*)$")


def load_names(root: Path):
    names = {}
    index = root / "functions.tsv"
    if not index.is_file():
        return names
    with index.open(newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            try:
                names[int(row["address"], 16)] = row["name"]
            except Exception:
                pass
    return names


def parse_asm(path: Path):
    rows = []
    for raw in path.read_text(errors="replace").splitlines():
        m = LINE_RE.match(raw)
        if m:
            rows.append((int(m.group(1), 16), raw))
    return rows


def context_for(root: Path, target: int, names):
    funcs = root / "functions"
    exact = None
    containing = None
    for path in funcs.glob("*.asm"):
        rows = parse_asm(path)
        if not rows:
            continue
        addrs = [a for a, _ in rows]
        if target in addrs:
            exact = (path, rows)
            break
        if min(addrs) <= target <= max(addrs):
            containing = (path, rows)

    found = exact or containing
    print(f"target=0x{target:08x}")
    if not found:
        print("  function=not-found")
        return

    path, rows = found
    try:
        start = int(path.stem, 16)
    except ValueError:
        start = rows[0][0]
    print(f"  function=0x{start:08x} {names.get(start, '')}".rstrip())

    nearest = min(range(len(rows)), key=lambda i: abs(rows[i][0] - target))
    lo = max(0, nearest - 16)
    if target == start and start in {0x0084a7f0, 0x0084a890, 0x0084a840, 0x0084c190, 0x0084c5b0}:
        forward = 240
    elif target == start and start in {0x00804340, 0x00806110}:
        forward = 420 if start == 0x00804340 else 320
    else:
        forward = 64 if target == start and start in {0x007b56d0, 0x007b6680, 0x00756e10, 0x0078fbe0} else 10
    hi = min(len(rows), nearest + forward)
    for i in range(lo, hi):
        mark = ">" if i == nearest else " "
        print(f"  {mark} {rows[i][1]}")

    if start == 0x007adc60:
        print("  field refs for [ESI + 0x30]:")
        for _, raw in rows:
            if "[ESI + 0x30]" in raw:
                print(f"    {raw}")



def print_literal_xrefs(root: Path, literal: str, limit: int = 80):
    funcs = root / "functions"
    needle = literal.lower()
    print(f"xrefs={literal}")
    count = 0
    for path in sorted(funcs.glob("*.asm")):
        for raw in path.read_text(errors="replace").splitlines():
            if needle in raw.lower():
                print(f"  {path.stem}: {raw}")
                count += 1
                if count >= limit:
                    print(f"  ... truncated at {limit} hits")
                    return
    if count == 0:
        print("  none")


def print_string_rows(root: Path, addresses):
    path = root / "strings.tsv"
    print("strings:")
    if not path.is_file():
        print("  strings.tsv missing")
        return
    needles = {a.lower().removeprefix("0x").lstrip("0") or "0" for a in addresses}
    found = set()
    for raw in path.read_text(errors="replace").splitlines():
        low = raw.lower()
        fields = re.split(r"\t+", low)
        for field in fields[:3]:
            token = field.strip().removeprefix("0x").lstrip("0") or "0"
            if token in needles:
                print("  " + raw)
                found.add(token)
                break
    for needle in sorted(needles - found):
        print(f"  0x{needle}: not-found")



def print_resource_string_references(root: Path) -> None:
    """Locate private code references to Intro and localization key fragments."""
    print("resource-key-text-xrefs:")
    path = root / "strings.tsv"
    if not path.is_file():
        print("  private strings.tsv unavailable")
        return
    terms = ("intro", "english", "locale", ".eng", "localized")
    found = 0
    for raw in path.read_text(errors="replace").splitlines():
        fields = raw.split("\t")
        if len(fields) < 4:
            continue
        value = "\t".join(fields[3:]).lower()
        if "intro" not in value and not any(value.startswith(t) for t in terms[1:]):
            continue
        print("  " + raw[:260])
        found += 1
        if found >= 80:
            print("  ... truncated")
            break
    if not found:
        print("  none")


def print_stdio_metadata(root: Path):
    terms = ("fopen", "fread", "fgets", "fseek", "ftell", "fclose", "rewind")
    print("stdio-metadata:")
    hits = 0
    for path in sorted(root.glob("*.tsv")):
        for raw in path.read_text(errors="replace").splitlines():
            low = raw.lower()
            if any(term in low for term in terms):
                print(f"  {path.name}: {raw}")
                hits += 1
                if hits >= 80:
                    print("  ... truncated")
                    return
    if hits == 0:
        print("  none")


def print_symbol_hits():
    path = ROOT / "build" / "recomp" / "gen" / "symbols.json"
    print("symbol-hits:")
    if not path.is_file():
        print("  symbols.json missing")
        return
    raw = path.read_text(errors="replace")
    needles = ("fopen", "fread", "fgets", "fseek", "ftell", "fclose",
               "009162dc", "009162f0", "0x009162dc", "0x009162f0")
    seen = set()
    for needle in needles:
        start = 0
        while True:
            i = raw.lower().find(needle.lower(), start)
            if i < 0:
                break
            snippet = raw[max(0, i - 180):min(len(raw), i + 260)].replace("\n", " ")
            if snippet not in seen:
                print("  " + snippet)
                seen.add(snippet)
            start = i + len(needle)
            if len(seen) >= 30:
                return
    if not seen:
        print("  none")


def print_generated_stdio_hits():
    root = ROOT / "build" / "recomp" / "gen"
    print("generated-stdio-hits:")
    if not root.is_dir():
        print("  generated baseline missing")
        return
    needles = ("fopen", "fgets", "fread", "fseek", "ftell", "fclose",
               "9162dc", "9162f0")
    hits = 0
    for path in sorted(root.glob("*")):
        if not path.is_file() or path.suffix.lower() not in {".c", ".h", ".json", ".txt"}:
            continue
        for n, raw in enumerate(path.read_text(errors="replace").splitlines(), 1):
            low = raw.lower()
            if any(x in low for x in needles):
                print(f"  {path.name}:{n}: {raw[:500]}")
                hits += 1
                if hits >= 80:
                    print("  ... truncated")
                    return
    if hits == 0:
        print("  none")


def print_callers(root: Path, target: str, limit: int = 40):
    print(f"callers={target}")
    funcs = root / "functions"
    needle = f"call {target}".lower()
    hits = 0
    for path in sorted(funcs.glob("*.asm")):
        rows = parse_asm(path)
        for i, (_, raw) in enumerate(rows):
            if needle in raw.lower():
                lo = max(0, i - 7)
                print(f"  function={path.stem}")
                for _, row in rows[lo:i + 2]:
                    print(f"    {row}")
                hits += 1
                if hits >= limit:
                    print("  ... truncated")
                    return
    if hits == 0:
        print("  none")


def print_function_strings(root: Path, functions):
    path = root / "strings.tsv"
    print("function-strings:")
    if not path.is_file():
        print("  strings.tsv missing")
        return
    wanted = {f.lower().removeprefix("0x").lstrip("0") for f in functions}
    hits = 0
    for raw in path.read_text(errors="replace").splitlines():
        fields = raw.split("\t")
        if len(fields) < 4:
            continue
        fn = fields[2].lower().removeprefix("0x").lstrip("0")
        if fn in wanted:
            print("  " + raw)
            hits += 1
    if hits == 0:
        print("  none")

def print_metadata_matches(root: Path, addresses):
    print("metadata-address-hits:")
    needles = tuple(a.lower().removeprefix("0x") for a in addresses)
    hits = 0
    for path in sorted(root.glob("*.tsv")):
        for raw in path.read_text(errors="replace").splitlines():
            low = raw.lower().replace("0x", "")
            if any(n in low for n in needles):
                print(f"  {path.name}: {raw}")
                hits += 1
                if hits >= 100:
                    print("  ... truncated")
                    return
    if hits == 0:
        print("  none")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="only print context for the requested addresses")
    ap.add_argument("listing_root", type=Path)
    ap.add_argument("addresses", nargs="+")
    args = ap.parse_args()

    names = load_names(args.listing_root)
    if args.quick:
        print_callers(args.listing_root, "0x00883ab2", 100)
        # Direct guest->guest calls can compile to native calls without
        # recomp_call(). Find actual generated C function labels for resource
        # submission and lookup before instrumenting the dispatch path.
        print("generated-resource-call-sites:")
        chunks = Path("build/recomp/gen")
        for code_term in ("0084c190", "0084a7f0", "0084a890"):
            found = 0
            for path in sorted(chunks.glob("chunk_*.c")):
                if found >= 12:
                    break
                lines = path.read_text(errors="replace").splitlines()
                for index, line in enumerate(lines):
                    if code_term not in line.lower():
                        continue
                    print(f"  {code_term} {path.name}:{index + 1}")
                    for nearby in lines[max(0, index - 3): index + 5]:
                        print("    " + nearby[:220])
                    found += 1
                    if found >= 12:
                        break
            if found == 0:
                print(f"  {code_term} not present in translation source")

        print_resource_string_references(args.listing_root)
        # Trace the UI resource lookup that repeatedly requests Intro/Intro.
        print_callers(args.listing_root, "0x0084a890", 60)
        print_metadata_matches(args.listing_root, ["0091600c", "009160f8", "00916014", "language.txt", "00916078"])
        print_callers(args.listing_root, "0x0084a7f0", 60)
        print_callers(args.listing_root, "0x0084c190", 60)
        # Pair the queue submitter with its free-slot allocator and discover
        # which worker receives DatabaseThreadEvent.
        print_callers(args.listing_root, "0x0084c5b0", 40)
        print_metadata_matches(args.listing_root,
                               ["DatabaseThreadEvent", "00916034", "00916078"])
        print_function_strings(args.listing_root,
                               ["0084c190", "0084c5b0", "0084a7f0"])

        print_function_strings(args.listing_root, ["0084a890", "0084a7f0", "0084a950"])

        # Resource lookup protects the resource map with a lock at
        # [this + 0x62b54]. This is a critical section, NOT a language ID.
        print("ui-critical-section-member-xrefs: 0x62b54")
        field_count = 0
        for path in sorted((args.listing_root / "functions").glob("*.asm")):
            rows = parse_asm(path)
            for i, (_, line) in enumerate(rows):
                if "0x62b54" not in line.lower():
                    continue
                print(f"  function={path.stem}")
                for _, near in rows[max(0, i - 5):i + 7]:
                    print(f"    {near}")
                field_count += 1
                if field_count >= 35:
                    break
            if field_count >= 35:
                print("  ... truncated at 35 matches")
                break
        if field_count == 0:
            print("  none")

        print_literal_xrefs(args.listing_root, "0x00d67ce8", 120)
        print_literal_xrefs(args.listing_root, "0x00d67cec", 120)
        print_literal_xrefs(args.listing_root, "0x00d67fd0", 120)
        print_literal_xrefs(args.listing_root, "0x00916008", 120)
        print_literal_xrefs(args.listing_root, "0x0091600c", 120)
        print_literal_xrefs(args.listing_root, "0x00916034", 120)
        print_literal_xrefs(args.listing_root, "0x00916078", 120)
        print_literal_xrefs(args.listing_root, "0x009160f8", 120)
        print_literal_xrefs(args.listing_root, "0x00972db8", 120)
        print_literal_xrefs(args.listing_root, "0x00a957f8", 120)
        print_literal_xrefs(args.listing_root, "0x00a957fc", 120)
        print_string_rows(args.listing_root, [
            "00972db8", "00972f38",
            "00970078", "00970d84", "00970d90", "00970d98",
            "0096d61c", "0096d644", "00952780",
            "00934c88", "00935138", "00946294", "0094629c",
        ])
        print_function_strings(args.listing_root, ["00594220", "007adc60", "00883ab2"])
        for raw in args.addresses:
            target = int(raw.lower().removeprefix("0x"), 16)
            context_for(args.listing_root, target, names)
        return

    print_symbol_hits()
    print_generated_stdio_hits()
    print_callers(args.listing_root, "0x008104d0", 24)
    print_callers(args.listing_root, "0x008434f0", 40)
    print_callers(args.listing_root, "0x0084df50", 40)
    print_callers(args.listing_root, "0x00880470", 40)
    print_callers(args.listing_root, "0x0087bd40", 40)
    print_callers(args.listing_root, "0x005c3380", 40)
    print_callers(args.listing_root, "0x0087bc40", 40)
    print_callers(args.listing_root, "0x0087bbd0", 40)
    print_callers(args.listing_root, "0x005ebd00", 40)
    print_stdio_metadata(args.listing_root)
    print_metadata_matches(args.listing_root, ["009322a0", "009322a4", "009322a8"])
    print_string_rows(args.listing_root, ["00952780", "0096d61c", "0096d644", "00970d84", "0096def0", "0096dee4", "009772a8", "00976b18", "00974650"])
    print_function_strings(args.listing_root, ["007562b0", "007564f0", "00756e10"])
    print_literal_xrefs(args.listing_root, "0x00a95960")
    for literal in ("0x952780", "0x96d61c", "0x96d644", "0x970d84"):
        print_literal_xrefs(args.listing_root, literal, 24)
    print("writes=0x00a95960")
    write_count = 0
    for path in sorted((args.listing_root / "functions").glob("*.asm")):
        for raw in path.read_text(errors="replace").splitlines():
            low = raw.lower()
            if "[0x00a95960]" in low and re.search(r"\bmov\s+(?:dword ptr\s+)?\[0x00a95960\]\s*,", low):
                print(f"  {path.stem}: {raw}")
                write_count += 1
    if write_count == 0:
        print("  none")

    print("member-writes=singleton+0x0c")
    member_hits = 0
    funcs = args.listing_root / "functions"
    for path in sorted(funcs.glob("*.asm")):
        rows = parse_asm(path)
        for i, (_, raw) in enumerate(rows):
            low = raw.lower()
            m = re.search(r"mov\s+(e(?:ax|cx|dx|bx|si|di)),(?:dword ptr )?\[0x00a95960\]", low)
            if not m:
                continue
            reg = m.group(1)
            window = rows[i + 1:i + 7]
            pat = re.compile(rf"\bmov\s+(?:dword ptr\s+)?\[{reg} \+ 0xc\]\s*,", re.I)
            for _, nxt in window:
                if pat.search(nxt):
                    print(f"  {path.stem}: {raw}  ==>  {nxt}")
                    member_hits += 1
    if member_hits == 0:
        print("  none")
    required = {
        "007add8d",
        "0084dfb0", "0084dfbb", "0084dfc0", "0084dfc9", "0084dfd0",
        "00843546", "0084357d", "00843584", "008435a0", "008435c0",
        "008804a8", "008804d0", "008804f4", "00880510",
        "005c3380", "005ebd00", "005ebd40", "005ebd80",
        "0087bb80", "0087bbd0", "0087bc00", "0087bc40",
        "0087bc80", "0087bcf0", "0087bd00", "0087bd40", "0087be00", "0087be80",
    }
    present = {a.lower().removeprefix("0x") for a in args.addresses}
    for address in sorted(required - present):
        args.addresses.append(address)
    for raw in args.addresses:
        target = int(raw.lower().removeprefix("0x"), 16)
        context_for(args.listing_root, target, names)


if __name__ == "__main__":
    main()

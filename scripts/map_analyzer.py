#!/usr/bin/env python3
import re
import glob
import os
import sys
from collections import defaultdict

REGION_RE = re.compile(r'^(\w+)\s+0x([0-9A-Fa-f]+)\s+0x([0-9A-Fa-f]+)\s+(\w+)')
LINE1 = re.compile(r'^\s*(\.\S+)\s*$')
LINE2 = re.compile(r'^\s*0x([0-9A-Fa-f]+)\s+0x([0-9A-Fa-f]+)\s+(\S+\.o(?:bj)?)\s*$')
INLINE = re.compile(r'^\s*(\.\S+)\s+0x([0-9A-Fa-f]+)\s+0x([0-9A-Fa-f]+)\s+(\S+\.o(?:bj)?)\s*$')

def parse_regions(text):
    regions = {}
    in_block = False
    for line in text.splitlines():
        if line.strip().startswith("Memory Configuration"):
            in_block = True
            continue
        if in_block:
            if line.strip().startswith("Linker script and memory map"):
                break
            m = REGION_RE.match(line.strip())
            if m and m.group(1).lower() != "default":
                regions[m.group(1)] = {"origin": int(m.group(2), 16), "length": int(m.group(3), 16), "used": 0}
    return regions

def parse_sections(text):
    modules = defaultdict(lambda: defaultdict(int))
    secs = []
    lines = text.splitlines()
    started = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if not started:
            if line.strip().startswith("Linker script and memory map"):
                started = True
            i += 1
            continue
        if "Archive member included" in line:
            break
        m_in = INLINE.match(line)
        if m_in:
            secs.append((m_in.group(1), int(m_in.group(2), 16), int(m_in.group(3), 16), m_in.group(4)))
            i += 1
            continue
        m1 = LINE1.match(line)
        if m1 and i + 1 < len(lines):
            m2 = LINE2.match(lines[i + 1])
            if m2:
                secs.append((m1.group(1), int(m2.group(1), 16), int(m2.group(2), 16), m2.group(3)))
                i += 2
                continue
        i += 1

    for sec, addr, size, obj in secs:
        if size == 0:
            continue
        base = obj.split("/")[-1].split("(")[-1].replace(")", "")
        base = re.sub(r"\.c\.obj$|\.s\.obj$|\.o$|\.cpp\.obj$", "", base)
        if sec.startswith(".text") or sec.startswith(".rodata") or sec == ".isr_vector" or sec.startswith(".ARM"):
            modules[base]["flash"] += size
        elif sec.startswith(".data"):
            modules[base]["flash"] += size
            modules[base]["ram"] += size
        elif sec.startswith(".bss") or sec.startswith("._user_heap"):
            modules[base]["ram"] += size
    return modules, secs

def assign_region(addr, regions):
    for name, r in regions.items():
        if r["origin"] <= addr < r["origin"] + r["length"]:
            return name
    return None

def fmt(n):
    return f"{n:,} B ({n / 1024:.1f} KB)"

def bar(pct, width=20):
    filled = int(min(pct, 100) / 100 * width)
    return "#" * filled + "-" * (width - filled)

def analyze_map(path, meta=None):
    with open(path, errors="ignore") as f:
        text = f.read()

    regions = parse_regions(text)
    modules, secs = parse_sections(text)

    for sec, addr, size, obj in secs:
        region = assign_region(addr, regions)
        if region:
            regions[region]["used"] += size

    lines = []
    lines.append(f"## {os.path.basename(path)}")
    lines.append("")

    if meta:
        lines.append("| Parameter | Value |")
        lines.append("|---|---|")
        for k, v in meta.items():
            if v:
                lines.append(f"| {k} | {v} |")
        lines.append("")

    lines.append("### Memory regions")
    lines.append("")
    lines.append("| Region | Used | Total | Fill |")
    lines.append("|---|---|---|---|")
    for name, r in regions.items():
        pct = r["used"] / r["length"] * 100 if r["length"] else 0
        lines.append(f"| {name} | {fmt(r['used'])} | {fmt(r['length'])} | `[{bar(pct)}]` {pct:.1f}% |")

    lines.append("")
    lines.append("### Top modules by flash usage")
    lines.append("")
    lines.append("| Module | Flash | RAM |")
    lines.append("|---|---|---|")
    for name, sizes in sorted(modules.items(), key=lambda x: -x[1]["flash"])[:20]:
        lines.append(f"| `{name}` | {fmt(sizes.get('flash', 0))} | {fmt(sizes.get('ram', 0))} |")

    lines.append("")
    return "\n".join(lines)

def build_meta_from_env():
    env_path = os.environ.get("ENV_PATH", "./build.env")
    meta = {}
    if not os.path.isfile(env_path):
        return meta
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            meta[key.strip()] = value.strip()
    result = {}
    if meta.get("BOARD_NAME"):
        result["Board"] = meta["BOARD_NAME"]
    if meta.get("BOARD_VERSION"):
        result["Board version"] = meta["BOARD_VERSION"]
    fw = ".".join(filter(None, [meta.get("FW_VERSION_MAJOR"), meta.get("FW_VERSION_MINOR"), meta.get("FW_VERSION_PATCH")]))
    if fw:
        result["Firmware version"] = f"v{fw}"
    if os.environ.get("GIT_COMMIT_HASH"):
        result["Commit"] = os.environ["GIT_COMMIT_HASH"]
    if os.environ.get("BUILD_TYPE"):
        result["Build type"] = os.environ["BUILD_TYPE"]
    return result

def main():
    search_paths = sys.argv[1:] if len(sys.argv) > 1 else ["."]
    maps = []
    for p in search_paths:
        maps.extend(glob.glob(f"{p}/**/*.map", recursive=True))
        maps.extend(glob.glob(f"{p}/*.map"))
    maps = sorted(set(maps))

    if not maps:
        print("No .map files found, memory_report.md not generated", file=sys.stderr)
        sys.exit(0)

    meta = build_meta_from_env()
    out = ["# Memory Report", ""]
    for m in maps:
        out.append(analyze_map(m, meta))

    report = "\n".join(out)

    output_path = os.environ.get("REPORT_PATH", "memory_report.md")
    with open(output_path, "w") as f:
        f.write(report)

    print(f"memory_report.md written ({len(maps)} map file(s))")

    gh_output = os.environ.get("GITHUB_OUTPUT", "")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"report_path={output_path}\n")

if __name__ == "__main__":
    main()

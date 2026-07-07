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

EXCLUDE_DIR_PARTS = {"build", "Debug", "Release", "CMakeFiles"}

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

def analyze_map(path, label, meta=None):
    with open(path, errors="ignore") as f:
        text = f.read()

    regions = parse_regions(text)
    modules, secs = parse_sections(text)

    for sec, addr, size, obj in secs:
        region = assign_region(addr, regions)
        if region:
            regions[region]["used"] += size

    lines = []
    lines.append(f"## {label}")
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

def build_meta_from_env(build_type_override=None):
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
    result["Build type"] = build_type_override or os.environ.get("BUILD_TYPE", "")
    return result

def dedup_maps(root_dirs):
    seen_content_hash = {}
    result = []
    for root in root_dirs:
        for path in sorted(glob.glob(f"{root}/**/*.map", recursive=True)) + sorted(glob.glob(f"{root}/*.map")):
            path = os.path.normpath(path)
            if any(part in EXCLUDE_DIR_PARTS for part in path.split(os.sep)):
                continue
            try:
                size = os.path.getsize(path)
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            key = (size, round(mtime, 0))
            if key in seen_content_hash:
                continue
            seen_content_hash[key] = path
            result.append(path)
    return sorted(set(result))

def label_for(path):
    name = os.path.basename(path)
    if "Debug" in path:
        cfg = "Debug"
    elif "Release" in path:
        cfg = "Release"
    else:
        cfg = ""
    return f"{name} ({cfg})" if cfg else name

def main():
    search_paths = sys.argv[1:] if len(sys.argv) > 1 else ["."]
    maps = dedup_maps(search_paths)

    if not maps:
        print("No .map files found, memory_report.md not generated", file=sys.stderr)
        sys.exit(0)

    out = ["# Memory Report", ""]
    for m in maps:
        cfg = "Debug" if "Debug" in m else ("Release" if "Release" in m else None)
        meta = build_meta_from_env(build_type_override=cfg)
        out.append(analyze_map(m, label_for(m), meta))

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

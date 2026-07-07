#!/usr/bin/env python3
"""
cproject_to_makefile.py  —  Generate Debug/Makefile (and/or Release/Makefile)
from STM32CubeIDE .cproject XML without requiring CubeIDE to be installed.

Usage:
    python3 cproject_to_makefile.py [--config Debug|Release|Both] [--project-dir .]

What it extracts from .cproject:
    - source directories (sourceEntries)
    - include paths  (-I)
    - preprocessor defines (-D)
    - linker script  (-T)
    - MCU target     (target_mcu option → CPU/FPU flags)
    - debug / optimisation level per config
"""

import argparse
import os
import sys
import glob
from pathlib import Path
from xml.etree import ElementTree as ET

# ── MCU → compiler flags table ─────────────────────────────────────────────
MCU_FLAGS: dict[str, str] = {
    # Cortex-M0 / M0+
    "STM32G0": "-mcpu=cortex-m0plus -mthumb",
    "STM32L0": "-mcpu=cortex-m0plus -mthumb",
    "STM32F0": "-mcpu=cortex-m0 -mthumb",
    # Cortex-M3
    "STM32F1": "-mcpu=cortex-m3 -mthumb",
    "STM32F2": "-mcpu=cortex-m3 -mthumb",
    "STM32L1": "-mcpu=cortex-m3 -mthumb",
    # Cortex-M4 (no FPU variants)
    "STM32F3": "-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard",
    "STM32L4": "-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard",
    "STM32G4": "-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard",
    "STM32WB": "-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard",
    # Cortex-M4 + FPU (F4 family)
    "STM32F4": "-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard",
    # Cortex-M7
    "STM32F7": "-mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard",
    "STM32H7": "-mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard",
    # Cortex-M33
    "STM32L5": "-mcpu=cortex-m33 -mthumb -mfpu=fpv5-sp-d16 -mfloat-abi=hard",
    "STM32U5": "-mcpu=cortex-m33 -mthumb -mfpu=fpv5-sp-d16 -mfloat-abi=hard",
    "STM32H5": "-mcpu=cortex-m33 -mthumb -mfpu=fpv5-sp-d16 -mfloat-abi=hard",
    "STM32WL": "-mcpu=cortex-m4 -mthumb",
}

DEBUG_LEVEL_MAP = {
    "value.g0": "-g0", "value.g1": "-g1", "value.g2": "-g2",
    "value.g3": "-g3", "value.gdwarf2": "-gdwarf-2", "value.gdwarf4": "-gdwarf-4",
}
OPT_LEVEL_MAP = {
    "value.o0": "-O0", "value.o1": "-O1", "value.o2": "-O2", "value.o3": "-O3",
    "value.os": "-Os", "value.og": "-Og",
}


def mcu_flags(mcu_str: str) -> str:
    """Return CPU/FPU flags for a given MCU string like 'STM32F103C8Tx'."""
    upper = mcu_str.upper()
    for prefix, flags in MCU_FLAGS.items():
        if upper.startswith(prefix):
            return flags
    # fallback — generic thumb
    return "-mcpu=cortex-m3 -mthumb"


def find_option(tool_el, superclass_fragment: str):
    """Find first <option> whose superClass contains superclass_fragment."""
    for opt in tool_el.iter("option"):
        sc = opt.get("superClass", "")
        if superclass_fragment in sc:
            return opt
    return None


def list_option_values(opt_el) -> list[str]:
    return [v.get("value", "") for v in opt_el.findall("listOptionValue")]


class CProjectConfig:
    def __init__(self, cfg_el, project_dir: Path, proj_name: str):
        self.name: str = cfg_el.get("name", "Debug")          # Debug / Release
        self.proj_name = proj_name
        self.project_dir = project_dir
        self.source_dirs: list[str] = []
        self.includes: list[str] = []
        self.defines: list[str] = []
        self.linker_script: str = ""
        self.cpu_flags: str = "-mcpu=cortex-m3 -mthumb"
        self.debug_flag: str = "-g3"
        self.opt_flag: str = "-O0"
        self.asm_debug_flag: str = "-g3"
        self._parse(cfg_el)

    def _parse(self, cfg_el):
        # source directories
        for entry in cfg_el.iter("entry"):
            if entry.get("kind") == "sourcePath":
                self.source_dirs.append(entry.get("name", ""))

        # toolchain options
        for tc in cfg_el.iter("toolChain"):
            # MCU target
            mcu_opt = find_option(tc, "option.target_mcu")
            if mcu_opt is not None:
                self.cpu_flags = mcu_flags(mcu_opt.get("value", ""))

        # C compiler options
        for tool in cfg_el.iter("tool"):
            sc = tool.get("superClass", "")

            if "tool.c.compiler" in sc and "cpp" not in sc:
                dbg = find_option(tool, "c.compiler.option.debuglevel")
                if dbg:
                    val = dbg.get("value", "")
                    self.debug_flag = DEBUG_LEVEL_MAP.get(val.split(".")[-2] + "." + val.split(".")[-1], "-g3")

                opt = find_option(tool, "c.compiler.option.optimization.level")
                if opt:
                    val = opt.get("value", "")
                    self.opt_flag = OPT_LEVEL_MAP.get(val.split(".")[-2] + "." + val.split(".")[-1], "-O0")

                inc_opt = find_option(tool, "compiler.option.includepaths")
                if inc_opt:
                    self.includes = list_option_values(inc_opt)

                def_opt = find_option(tool, "c.compiler.option.definedsymbols")
                if def_opt:
                    self.defines = list_option_values(def_opt)

            if "tool.assembler" in sc:
                dbg = find_option(tool, "assembler.option.debuglevel")
                if dbg:
                    val = dbg.get("value", "")
                    self.asm_debug_flag = DEBUG_LEVEL_MAP.get(
                        val.split(".")[-2] + "." + val.split(".")[-1], "-g3")

            if "tool.c.linker" in sc and "cpp" not in sc:
                script_opt = find_option(tool, "linker.option.script")
                if script_opt:
                    raw = script_opt.get("value", "")
                    # resolve ${workspace_loc:/${ProjName}/foo.ld} → ../foo.ld
                    if "workspace_loc" in raw:
                        fname = raw.split("/")[-1].rstrip("}")
                        self.linker_script = f"../{fname}"
                    else:
                        self.linker_script = raw

    def collect_sources(self) -> tuple[list[str], list[str]]:
        """Walk source_dirs, return (c_sources, asm_sources) relative to build dir."""
        c_srcs, asm_srcs = [], []
        for sd in self.source_dirs:
            src_path = self.project_dir / sd
            for f in sorted(src_path.rglob("*.c")):
                rel = os.path.relpath(f, self.project_dir / self.name)
                c_srcs.append(rel.replace("\\", "/"))
            for pat in ("*.s", "*.S"):
                for f in sorted(src_path.rglob(pat)):
                    rel = os.path.relpath(f, self.project_dir / self.name)
                    asm_srcs.append(rel.replace("\\", "/"))
        return c_srcs, asm_srcs

    def generate(self) -> str:
        c_srcs, asm_srcs = self.collect_sources()
        all_srcs = c_srcs + asm_srcs

        inc_flags = " ".join(f"-I{i}" for i in self.includes)
        def_flags = " ".join(f"-D{d}" for d in self.defines)
        ld_script = self.linker_script or f"../{self.proj_name}.ld"
        cfg_lower = self.name.lower()
        is_debug = self.name == "Debug"

        obj_list = " \\
\t".join(
            src.replace("../", "").replace("/", "_").replace(".c", ".o").replace(".s", ".o").replace(".S", ".o")
            for src in all_srcs
        )

        # build OBJS with proper subdir paths
        obj_lines = []
        for src in all_srcs:
            obj = src.replace("../", "").replace("/", "_")
            obj = obj[:-2] + ".o" if obj.endswith(".c") else obj[:-2] + ".o"
            obj_lines.append(f"{obj}: {src}")

        lines = []
        lines.append(f"# Auto-generated by cproject_to_makefile.py — DO NOT EDIT")
        lines.append(f"# Config: {self.name} | Project: {self.proj_name}")
        lines.append("")
        lines.append("CC      = arm-none-eabi-gcc")
        lines.append("AS      = arm-none-eabi-gcc -x assembler-with-cpp")
        lines.append("CP      = arm-none-eabi-objcopy")
        lines.append("SZ      = arm-none-eabi-size")
        lines.append("HEX     = $(CP) -O ihex")
        lines.append("BIN     = $(CP) -O binary -S")
        lines.append("")
        lines.append(f"TARGET  = {self.proj_name}")
        lines.append(f"BUILD_DIR = {self.name}")
        lines.append("")
        lines.append(f"CPU     = {self.cpu_flags}")
        lines.append(f"OPT     = {self.opt_flag}")
        lines.append(f"DEBUG   = {self.debug_flag}")
        lines.append("")
        lines.append(f"DEFS    = {def_flags}")
        lines.append(f"INCS    = {inc_flags}")
        lines.append(f"LDSCRIPT = {ld_script}")
        lines.append("")
        lines.append("CFLAGS  = $(CPU) $(OPT) $(DEBUG) $(DEFS) $(INCS) \\")
        lines.append("          -Wall -fdata-sections -ffunction-sections")
        lines.append("ASFLAGS = $(CPU) $(DEBUG) $(DEFS) $(INCS) \\")
        lines.append("          -Wall -fdata-sections -ffunction-sections")
        lines.append("LDFLAGS = $(CPU) -specs=nano.specs -T$(LDSCRIPT) \\")
        lines.append("          -lc -lm -lnosys -Wl,-Map=$(TARGET).map,--cref -Wl,--gc-sections")
        lines.append("")
        lines.append("# Sources")
        for src in c_srcs:
            lines.append(f"C_SOURCES += {src}")
        for src in asm_srcs:
            lines.append(f"ASM_SOURCES += {src}")
        lines.append("")
        lines.append("OBJECTS = $(addprefix $(BUILD_DIR)/,$(notdir $(C_SOURCES:.c=.o)))")
        lines.append("OBJECTS += $(addprefix $(BUILD_DIR)/,$(notdir $(ASM_SOURCES:.s=.o)))")
        lines.append("OBJECTS += $(addprefix $(BUILD_DIR)/,$(notdir $(ASM_SOURCES:.S=.o)))")
        lines.append("")
        lines.append(".PHONY: all clean")
        lines.append("")
        lines.append("all: $(BUILD_DIR)/$(TARGET).elf $(BUILD_DIR)/$(TARGET).hex $(BUILD_DIR)/$(TARGET).bin")
        lines.append("")
        lines.append("$(BUILD_DIR)/%.o: ../%.c | $(BUILD_DIR)")
        lines.append("\t$(CC) -c $(CFLAGS) -Wa,-a,-ad,-alms=$(BUILD_DIR)/$(notdir $(<:.c=.lst)) $< -o $@")
        lines.append("")
        # per-source-dir vpath rules
        for sd in self.source_dirs:
            lines.append(f"$(BUILD_DIR)/%.o: ../{sd}/%.c | $(BUILD_DIR)")
            lines.append("\t$(CC) -c $(CFLAGS) $< -o $@")
            lines.append(f"$(BUILD_DIR)/%.o: ../{sd}/Startup/%.s | $(BUILD_DIR)")
            lines.append("\t$(AS) -c $(ASFLAGS) $< -o $@")
            lines.append(f"$(BUILD_DIR)/%.o: ../{sd}/Startup/%.S | $(BUILD_DIR)")
            lines.append("\t$(AS) -c $(ASFLAGS) $< -o $@")
            lines.append("")
        lines.append("$(BUILD_DIR)/$(TARGET).elf: $(OBJECTS) | $(BUILD_DIR)")
        lines.append("\t$(CC) $(OBJECTS) $(LDFLAGS) -o $@")
        lines.append("\t$(SZ) $@")
        lines.append("")
        lines.append("$(BUILD_DIR)/%.hex: $(BUILD_DIR)/%.elf")
        lines.append("\t$(HEX) $< $@")
        lines.append("")
        lines.append("$(BUILD_DIR)/%.bin: $(BUILD_DIR)/%.elf")
        lines.append("\t$(BIN) $< $@")
        lines.append("")
        lines.append("$(BUILD_DIR):")
        lines.append("\tmkdir -p $@")
        lines.append("")
        lines.append("clean:")
        lines.append("\trm -fR $(BUILD_DIR)")
        lines.append("")
        return "\n".join(lines)


def parse_cproject(project_dir: Path) -> list[CProjectConfig]:
    cproject_path = project_dir / ".cproject"
    if not cproject_path.exists():
        print(f"::error::No .cproject found in {project_dir}", file=sys.stderr)
        sys.exit(1)

    tree = ET.parse(cproject_path)
    root = tree.getroot()

    # resolve project name from .project or cdtBuildSystem project element
    proj_name = project_dir.name
    proj_file = project_dir / ".project"
    if proj_file.exists():
        ptree = ET.parse(proj_file)
        name_el = ptree.getroot().find("name")
        if name_el is not None and name_el.text:
            proj_name = name_el.text.strip()

    configs = []
    for cfg_el in root.iter("configuration"):
        # only top-level managed build configs (have artifactExtension)
        if cfg_el.get("artifactExtension"):
            configs.append(CProjectConfig(cfg_el, project_dir, proj_name))
    return configs


def main():
    parser = argparse.ArgumentParser(description="Generate Makefile(s) from STM32CubeIDE .cproject")
    parser.add_argument("--config", default="Both", choices=["Debug", "Release", "Both"])
    parser.add_argument("--project-dir", default=".", help="Path to project root (contains .cproject)")
    parser.add_argument("--dry-run", action="store_true", help="Print Makefile to stdout, don't write")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    configs = parse_cproject(project_dir)

    if not configs:
        print("::error::No configurations found in .cproject", file=sys.stderr)
        sys.exit(1)

    for cfg in configs:
        if args.config != "Both" and cfg.name != args.config:
            continue
        makefile_content = cfg.generate()
        if args.dry_run:
            print(f"### {cfg.name}/Makefile ###")
            print(makefile_content)
        else:
            out_dir = project_dir / cfg.name
            out_dir.mkdir(exist_ok=True)
            out_path = out_dir / "Makefile"
            out_path.write_text(makefile_content)
            print(f"Generated {out_path}")


if __name__ == "__main__":
    main()

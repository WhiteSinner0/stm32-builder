#!/usr/bin/env python3
"""
cproject_to_makefile.py  -  Generate Debug/Makefile (and/or Release/Makefile)
from STM32CubeIDE .cproject XML without requiring CubeIDE to be installed.

Usage:
    python3 cproject_to_makefile.py [--config Debug|Release|Both] [--project-dir .]

Extracts from .cproject:
    - source directories (sourceEntries)
    - include paths  (-I)
    - preprocessor defines (-D)
    - linker script  (-T)
    - MCU target     (target_mcu -> CPU/FPU flags)
    - debug / optimisation level per config
"""

import argparse
import os
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

MCU_FLAGS = {
    "STM32G0": "-mcpu=cortex-m0plus -mthumb",
    "STM32L0": "-mcpu=cortex-m0plus -mthumb",
    "STM32F0": "-mcpu=cortex-m0 -mthumb",
    "STM32F1": "-mcpu=cortex-m3 -mthumb",
    "STM32F2": "-mcpu=cortex-m3 -mthumb",
    "STM32L1": "-mcpu=cortex-m3 -mthumb",
    "STM32F3": "-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard",
    "STM32L4": "-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard",
    "STM32G4": "-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard",
    "STM32WB": "-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard",
    "STM32F4": "-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard",
    "STM32F7": "-mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard",
    "STM32H7": "-mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard",
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


def mcu_flags(mcu_str):
    upper = mcu_str.upper()
    for prefix, flags in MCU_FLAGS.items():
        if upper.startswith(prefix):
            return flags
    return "-mcpu=cortex-m3 -mthumb"


def find_option(tool_el, superclass_fragment):
    for opt in tool_el.iter("option"):
        if superclass_fragment in opt.get("superClass", ""):
            return opt
    return None


def list_option_values(opt_el):
    return [v.get("value", "") for v in opt_el.findall("listOptionValue")]


class CProjectConfig:
    def __init__(self, cfg_el, project_dir, proj_name):
        self.name = cfg_el.get("name", "Debug")
        self.proj_name = proj_name
        self.project_dir = project_dir
        self.source_dirs = []
        self.includes = []
        self.defines = []
        self.linker_script = ""
        self.cpu_flags = "-mcpu=cortex-m3 -mthumb"
        self.debug_flag = "-g3"
        self.opt_flag = "-O0"
        self.asm_debug_flag = "-g3"
        self._parse(cfg_el)

    def _parse(self, cfg_el):
        for entry in cfg_el.iter("entry"):
            if entry.get("kind") == "sourcePath":
                self.source_dirs.append(entry.get("name", ""))

        for tc in cfg_el.iter("toolChain"):
            mcu_opt = find_option(tc, "option.target_mcu")
            if mcu_opt is not None:
                self.cpu_flags = mcu_flags(mcu_opt.get("value", ""))

        for tool in cfg_el.iter("tool"):
            sc = tool.get("superClass", "")

            if "tool.c.compiler" in sc and "cpp" not in sc:
                dbg = find_option(tool, "c.compiler.option.debuglevel")
                if dbg:
                    val = dbg.get("value", "")
                    key = ".".join(val.split(".")[-2:])
                    self.debug_flag = DEBUG_LEVEL_MAP.get(key, "-g3")

                opt = find_option(tool, "c.compiler.option.optimization.level")
                if opt:
                    val = opt.get("value", "")
                    key = ".".join(val.split(".")[-2:])
                    self.opt_flag = OPT_LEVEL_MAP.get(key, "-O0")

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
                    key = ".".join(val.split(".")[-2:])
                    self.asm_debug_flag = DEBUG_LEVEL_MAP.get(key, "-g3")

            if "tool.c.linker" in sc and "cpp" not in sc:
                script_opt = find_option(tool, "linker.option.script")
                if script_opt:
                    raw = script_opt.get("value", "")
                    if "workspace_loc" in raw:
                        fname = raw.split("/")[-1].rstrip("}")
                        self.linker_script = "../" + fname
                    else:
                        self.linker_script = raw

    def collect_sources(self):
        c_srcs, asm_srcs = [], []
        build_dir = self.project_dir / self.name
        for sd in self.source_dirs:
            src_path = self.project_dir / sd
            for f in sorted(src_path.rglob("*.c")):
                rel = os.path.relpath(f, build_dir).replace("\\", "/")
                c_srcs.append(rel)
            for pat in ("*.s", "*.S"):
                for f in sorted(src_path.rglob(pat)):
                    rel = os.path.relpath(f, build_dir).replace("\\", "/")
                    asm_srcs.append(rel)
        return c_srcs, asm_srcs

    def generate(self):
        c_srcs, asm_srcs = self.collect_sources()
        inc_flags = " ".join("-I" + i for i in self.includes)
        def_flags = " ".join("-D" + d for d in self.defines)
        ld_script = self.linker_script or ("../" + self.proj_name + ".ld")

        L = []  # lines
        a = L.append

        a("# Auto-generated by cproject_to_makefile.py - DO NOT EDIT")
        a("# Config: " + self.name + " | Project: " + self.proj_name)
        a("")
        a("CC      = arm-none-eabi-gcc")
        a("AS      = arm-none-eabi-gcc -x assembler-with-cpp")
        a("CP      = arm-none-eabi-objcopy")
        a("SZ      = arm-none-eabi-size")
        a("HEX     = $(CP) -O ihex")
        a("BIN     = $(CP) -O binary -S")
        a("")
        a("TARGET    = " + self.proj_name)
        a("BUILD_DIR = " + self.name)
        a("")
        a("CPU     = " + self.cpu_flags)
        a("OPT     = " + self.opt_flag)
        a("DEBUG   = " + self.debug_flag)
        a("")
        a("DEFS     = " + def_flags)
        a("INCS     = " + inc_flags)
        a("LDSCRIPT = " + ld_script)
        a("")
        a("CFLAGS  = $(CPU) $(OPT) $(DEBUG) $(DEFS) $(INCS) \\")
        a("          -Wall -fdata-sections -ffunction-sections")
        a("ASFLAGS = $(CPU) $(DEBUG) $(DEFS) $(INCS) \\")
        a("          -Wall -fdata-sections -ffunction-sections")
        a("LDFLAGS = $(CPU) -specs=nano.specs -T$(LDSCRIPT) \\")
        a("          -lc -lm -lnosys -Wl,-Map=$(BUILD_DIR)/$(TARGET).map,--cref -Wl,--gc-sections")
        a("")
        a("# Sources")
        for src in c_srcs:
            a("C_SOURCES += " + src)
        for src in asm_srcs:
            a("ASM_SOURCES += " + src)
        a("")
        a("OBJECTS  = $(addprefix $(BUILD_DIR)/,$(notdir $(C_SOURCES:.c=.o)))")
        a("OBJECTS += $(addprefix $(BUILD_DIR)/,$(notdir $(ASM_SOURCES:.s=.o)))")
        a("OBJECTS += $(addprefix $(BUILD_DIR)/,$(notdir $(ASM_SOURCES:.S=.o)))")
        a("")
        a("vpath %.c " + " ".join("../" + sd for sd in self.source_dirs))
        for sd in self.source_dirs:
            a("vpath %.c ../" + sd)
            a("vpath %.s ../" + sd + "/Startup ../" + sd)
            a("vpath %.S ../" + sd + "/Startup ../" + sd)
        a("")
        a(".PHONY: all clean")
        a("")
        a("all: $(BUILD_DIR)/$(TARGET).elf $(BUILD_DIR)/$(TARGET).hex $(BUILD_DIR)/$(TARGET).bin")
        a("")
        a("$(BUILD_DIR)/%.o: %.c Makefile | $(BUILD_DIR)")
        a("\t$(CC) -c $(CFLAGS) -Wa,-a,-ad,-alms=$(BUILD_DIR)/$(notdir $(<:.c=.lst)) $< -o $@")
        a("")
        a("$(BUILD_DIR)/%.o: %.s Makefile | $(BUILD_DIR)")
        a("\t$(AS) -c $(ASFLAGS) $< -o $@")
        a("")
        a("$(BUILD_DIR)/%.o: %.S Makefile | $(BUILD_DIR)")
        a("\t$(AS) -c $(ASFLAGS) $< -o $@")
        a("")
        a("$(BUILD_DIR)/$(TARGET).elf: $(OBJECTS) Makefile")
        a("\t$(CC) $(OBJECTS) $(LDFLAGS) -o $@")
        a("\t$(SZ) $@")
        a("")
        a("$(BUILD_DIR)/%.hex: $(BUILD_DIR)/%.elf | $(BUILD_DIR)")
        a("\t$(HEX) $< $@")
        a("")
        a("$(BUILD_DIR)/%.bin: $(BUILD_DIR)/%.elf | $(BUILD_DIR)")
        a("\t$(BIN) $< $@")
        a("")
        a("$(BUILD_DIR):")
        a("\tmkdir -p $@")
        a("")
        a("clean:")
        a("\trm -fR $(BUILD_DIR)")
        a("")
        return "\n".join(L)


def parse_cproject(project_dir):
    cproject_path = project_dir / ".cproject"
    if not cproject_path.exists():
        print("::error::No .cproject found in " + str(project_dir), file=sys.stderr)
        sys.exit(1)

    root = ET.parse(cproject_path).getroot()

    proj_name = project_dir.name
    proj_file = project_dir / ".project"
    if proj_file.exists():
        name_el = ET.parse(proj_file).getroot().find("name")
        if name_el is not None and name_el.text:
            proj_name = name_el.text.strip()

    configs = []
    for cfg_el in root.iter("configuration"):
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
        content = cfg.generate()
        if args.dry_run:
            print("### " + cfg.name + "/Makefile ###")
            print(content)
        else:
            out_dir = project_dir / cfg.name
            out_dir.mkdir(exist_ok=True)
            out_path = out_dir / "Makefile"
            out_path.write_text(content)
            print("Generated " + str(out_path))


if __name__ == "__main__":
    main()

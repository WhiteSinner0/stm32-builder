#!/usr/bin/env python3
import os
import sys
import re
import glob

REQUIRED_KEYS = ["BOARD_NAME", "BOARD_VERSION", "FW_VERSION_MAJOR", "FW_VERSION_MINOR", "FW_VERSION_PATCH"]

def load_env(path):
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env

def check_required(env):
    missing = [k for k in REQUIRED_KEYS if k not in env]
    return missing

def get_project_name_cmake():
    if not os.path.isfile("CMakeLists.txt"):
        return None
    with open("CMakeLists.txt") as f:
        for line in f:
            m = re.search(r'project\(\s*([^\s)]+)', line)
            if m:
                return m.group(1)
    return None

def get_project_name_ioc():
    for path in glob.glob("*.ioc") + glob.glob("*/*.ioc"):
        with open(path) as f:
            for line in f:
                if line.startswith("ProjectName="):
                    return line.strip().split("=", 1)[1], path
    return None, None

def get_project_name_eclipse():
    if os.path.isfile(".project"):
        with open(".project") as f:
            content = f.read()
        m = re.search(r'<name>([^<]+)</name>', content)
        if m:
            return m.group(1).strip()
    return None

def check_name_consistency(env):
    names = {}
    cmake_name = get_project_name_cmake()
    if cmake_name:
        names["CMakeLists.txt"] = cmake_name
    ioc_name, ioc_path = get_project_name_ioc()
    if ioc_name:
        names[ioc_path] = ioc_name
    eclipse_name = get_project_name_eclipse()
    if eclipse_name:
        names[".project"] = eclipse_name

    board = env.get("BOARD_NAME", "")
    unique = set(names.values())
    if len(unique) > 1:
        detail = ", ".join(f"{src}='{n}'" for src, n in names.items())
        print(f"ERROR: project name mismatch: {detail}", file=sys.stderr)
        sys.exit(1)

    project_name = list(unique)[0] if unique else board
    return project_name, names

def firmware_filename(env, project_name, commit_hash, build_type):
    board = env.get("BOARD_NAME", project_name)
    board_ver = env.get("BOARD_VERSION", "")
    fw_major = env.get("FW_VERSION_MAJOR", "0")
    fw_minor = env.get("FW_VERSION_MINOR", "0")
    fw_patch = env.get("FW_VERSION_PATCH", "0")
    version = f"v{fw_major}.{fw_minor}.{fw_patch}"
    parts = [project_name]
    if board_ver:
        parts.append(board_ver)
    parts.append(version)
    parts.append(commit_hash[:7] if len(commit_hash) > 7 else commit_hash)
    parts.append(build_type)
    return "-".join(parts), version

def main():
    parse_only = "--parse-only" in sys.argv
    env_path = "./build.env"
    for i, arg in enumerate(sys.argv):
        if arg == "--env" and i + 1 < len(sys.argv):
            env_path = sys.argv[i + 1]

    if not os.path.isfile(env_path):
        print(f"ERROR: {env_path} not found", file=sys.stderr)
        sys.exit(1)

    env = load_env(env_path)

    for k, v in env.items():
        os.environ.setdefault(k, v)

    if not parse_only:
        missing = check_required(env)
        if missing:
            print(f"ERROR: missing required build.env keys: {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)

    project_name, name_sources = check_name_consistency(env)
    commit_hash = os.environ.get("GIT_COMMIT_HASH", "unknown")
    build_type = os.environ.get("BUILD_TYPE", "Release")
    fw_filename, version = firmware_filename(env, project_name, commit_hash, build_type)

    gh_output = os.environ.get("GITHUB_OUTPUT", "")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"project_name={project_name}\n")
            f.write(f"fw_filename={fw_filename}\n")
            f.write(f"version={version}\n")
            f.write(f"version_major={env.get('FW_VERSION_MAJOR','0')}\n")
            f.write(f"version_minor={env.get('FW_VERSION_MINOR','0')}\n")
            f.write(f"version_patch={env.get('FW_VERSION_PATCH','0')}\n")
            f.write(f"board_name={env.get('BOARD_NAME','')}\n")
            f.write(f"board_version={env.get('BOARD_VERSION','')}\n")
    else:
        print(f"project_name={project_name}")
        print(f"fw_filename={fw_filename}")
        print(f"version={version}")
        print(f"version_major={env.get('FW_VERSION_MAJOR','0')}")
        print(f"version_minor={env.get('FW_VERSION_MINOR','0')}")
        print(f"version_patch={env.get('FW_VERSION_PATCH','0')}")
        print(f"board_name={env.get('BOARD_NAME','')}")
        print(f"board_version={env.get('BOARD_VERSION','')}")

if __name__ == "__main__":
    main()

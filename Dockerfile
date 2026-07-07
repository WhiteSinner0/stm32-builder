FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc-arm-none-eabi \
    binutils-arm-none-eabi \
    libnewlib-arm-none-eabi \
    libstdc++-arm-none-eabi-newlib \
    ninja-build \
    cmake \
    make \
    git \
    python3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY scripts/map_analyzer.py /opt/scripts/map_analyzer.py
COPY scripts/build_env_parser.py /opt/scripts/build_env_parser.py
RUN chmod +x /opt/scripts/map_analyzer.py /opt/scripts/build_env_parser.py

ENV PATH="/opt/scripts:${PATH}"

WORKDIR /workspace

LABEL org.opencontainers.image.source="https://github.com/WhiteSinner0/stm32-builder"
LABEL org.opencontainers.image.description="Universal STM32 firmware build container (CMake + CubeIDE Makefile)"
LABEL org.opencontainers.image.licenses="MIT"

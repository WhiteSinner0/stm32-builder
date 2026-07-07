## 1. Требования к репозиторию прошивки

### 1.1 CMakeLists.txt

Название проекта должно резолвиться в реальную строку (не обязательно, но крайне рекомендуется избегать плейсхолдеров вида `project(${CMAKE_PROJECT_NAME})` без предварительного `set(CMAKE_PROJECT_NAME ...)` выше по файлу):

```cmake
set(CMAKE_PROJECT_NAME UniversalModule)
project(${CMAKE_PROJECT_NAME})
```

Чтобы прошивка знала свой коммит, можно добавить после `add_executable`/`target_...`:

```cmake
target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    GIT_COMMIT_HASH="${GIT_COMMIT_HASH}"
)
```

Без этой строки хеш коммита долетит только до CMake-кэша, но не попадёт в код прошивки.

### 1.2 build.env (обязателен в корне репозитория)

```
BOARD_NAME=UniversalModule
BOARD_VERSION=1.x
FW_VERSION_MAJOR=0
FW_VERSION_MINOR=1
FW_VERSION_PATCH=0
```

Все пять ключей обязательны. Если платы без версионирования - оставить `BOARD_VERSION=` пустым, но саму строку не удалять.

### 1.3 Согласование имён проекта

Если в репозитории есть `.ioc` файл (CubeMX), `ProjectName=` внутри него должен совпадать с именем из `project()` в CMakeLists.txt. При несовпадении сборка падает с явной ошибкой на этапе валидации, до старта компиляции.

---

## 2. Файлы workflow в firmware-репозитории

### 2.1 `.github/workflows/build.yml`

Собирается при пуше/PR в любую ветку, без публикации релиза:

```yaml
name: Build

on:
  push:
    branches: ["*"]
  pull_request:
    branches: ["*"]
  workflow_dispatch:
    inputs:
      build_type:
        description: "Build type"
        required: true
        type: choice
        options: [Debug, Release, Both]
        default: "Both"

jobs:
  build:
    runs-on: ubuntu-latest
    container:
      image: ghcr.io/whitesinner0/stm32-builder:latest

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Build firmware
        id: build
        uses: whitesinner0/stm32-builder/action@main
        with:
          build_configuration: ${{ inputs.build_type || 'Both' }}
          build_system: cmake
          env_path: ./build.env

      - uses: actions/upload-artifact@v4
        with:
          name: firmware-${{ steps.build.outputs.firmware_name }}
          path: |
            *.elf
            *.bin
            *.hex
            *.map
            memory_report.md
          if-no-files-found: error
```

### 2.2 `.github/workflows/release.yml`

Собирается только по тегу `v*.*.*`, публикует draft-релиз с memory_report.md в описании:

```yaml
name: Release on tag

on:
  push:
    tags: ["v*.*.*"]

jobs:
  build-and-release:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    container:
      image: ghcr.io/whitesinner0/stm32-builder:latest

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Build Release firmware
        id: build
        uses: whitesinner0/stm32-builder/action@main
        with:
          build_configuration: Release
          build_system: cmake
          env_path: ./build.env

      - name: Publish GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ github.ref_name }}
          name: "${{ steps.build.outputs.project_name }} ${{ github.ref_name }}"
          body_path: memory_report.md
          draft: true
          generate_release_notes: true
          files: |
            *.elf
            *.bin
            *.hex
            *.map
          fail_on_unmatched_files: false
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

---

## 3. Пошаговая настройка нового firmware-репозитория

1. Скопировать `build.env` из шаблона, заполни `BOARD_NAME`, `BOARD_VERSION`, `FW_VERSION_*`.
2. Скопировать `.github/workflows/build.yml` и `release.yml` из пункта 2.2.
3. Опционально добавить `target_compile_definitions(... GIT_COMMIT_HASH="${GIT_COMMIT_HASH}")` в `CMakeLists.txt`, если нужно видеть коммит в самой прошивке.
4. Push в любую ветку -сработает `build.yml`.
5. Для релиза: `git tag v1.0.0 && git push origin v1.0.0` — сработает `release.yml`.

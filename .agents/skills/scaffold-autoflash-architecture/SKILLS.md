---
name: scaffold-autoflash-architecture
description: Triggers when the user requests to initialize, structure, or build the core Python modules for the AutoFlash Tool, including the CustomTkinter GUI, hardware detection, and fastboot/adb subprocess wrappers.
---

## Prerequisites
* The active workspace must be open in the Antigravity IDE.
* A Python 3.10+ environment must be available.
* Read/write access to the current working directory.

## Execution Steps
1. **Create** the project directory structure: `src/`, `src/ui/`, `src/backend/`, `drivers/`, and `tools/`.
2. **Generate** a `requirements.txt` file containing the core dependencies: `customtkinter`, `wmi`, `pyusb`, and `pyinstaller`.
3. **Execute** `pip install -r requirements.txt` in the integrated terminal to prepare the environment.
4. **Create** `src/backend/hardware_detective.py`. Implement the tiered USB polling logic (ADB, Fastboot, and BROM/EDL VID/PID detection using the `wmi` library). **Validate** that the logic strictly avoids payload injection tools for emergency recovery modes, relying solely on native BROM/EDL polling.
5. **Create** `src/backend/flasher.py`. Implement the `subprocess` wrappers to execute `adb` and `fastboot` commands securely in the background.
6. **Create** `src/backend/driver_manager.py`. Implement the logic to execute `pnputil /add-driver` via `subprocess` for silent driver installation.
7. **Create** `src/ui/main_window.py`. Scaffold the graphical interface using `customtkinter`, including the four-button Launchpad, the Hardware Detective status screen, and the Flashing Hub.
8. **Import** the `threading` module in `src/ui/main_window.py` and **bind** all backend functions (flashing, detection, driver installation) to background threads to prevent UI blocking.

## Failure Handling
* If dependency installation fails, **log** the pip error to the terminal, **prompt** the user to activate a virtual environment, and halt execution.
* If directories or files already exist, **skip** the creation step for those specific files to avoid overwriting the user's existing work.
* If the host OS is not Windows, **warn** the user that `wmi` and `pnputil` functionalities will throw exceptions, and gracefully skip the implementation of `driver_manager.py`.
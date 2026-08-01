# ⚡ AutoFlash

**AutoFlash** is a modern, user-friendly Android flashing utility designed with a clean GUI to eliminate command-line complexity while retaining advanced hardware flashing capabilities.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python)
![CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-darkgreen?style=for-the-badge)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?style=for-the-badge)

---

## ✨ Features

- **📊 Scatter-Loading Partition Grid:** Dynamic SP-Flash-Tool-style partition parser (`scatter.txt` / `rawprogram.xml`). Select, uncheck, or assign specific image files with ease.
- **🔍 Hardware Detective:** Automatic device mode detection (ADB, Fastboot, MTK BROM / Qualcomm EDL) using native Windows WMI polling.
- **⚙️ MediaTek BROM Toolkit:** Direct serial Download Agent (DA) communication for auth bypass (SLA/DA), FRP erase, data wipe, and preloader reboot triggers.
- **🛠️ Driver Manager:** Integrated silent PNP driver installer using `pnputil`.
- **⚡ Threaded Architecture:** Non-blocking asynchronous background execution for long flashing procedures.

---

## 📂 Project Structure

```text
AutoFlash/
├── .agents/          # IDE Skills
├── .gemini/          # Workspace rules
├── drivers/          # Device INF drivers
├── tools/            # adb / fastboot binaries
├── src/
│   ├── main.py       # Application entry point
│   ├── ui/           # CustomTkinter interface layout
│   └── backend/      # Detection, Flasher, BROM, and Parser logic
└── requirements.txt
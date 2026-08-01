========================================================================
                              AUTOFLASH TOOL
========================================================================

AutoFlash Tool is a modern, user-friendly Android flashing utility 
designed with a clean graphical interface to eliminate command-line 
complexity while retaining advanced hardware flashing capabilities.

------------------------------------------------------------------------
                             CORE FEATURES
------------------------------------------------------------------------

* SCATTER-LOADING FLASHING HUB
  Dynamic, SP-Flash-Tool-style partition grid. Parse scatter.txt or 
  rawprogram.xml files to view all partitions. Select, uncheck, or 
  assign specific image files (boot, recovery, super, etc.) manually.

* MTK BROM TOOLKIT
  A dedicated suite for MediaTek low-level recovery using direct serial 
  Download Agent (DA) communication (Standard payload tools are bypassed 
  as they are non-functional in BROM mode).
  - Bypass SLA/DA Authentication
  - Format Data / FRP Erase
  - Dump Boot/Recovery
  - Force Reboot to BROM (via ADB preloader crash or Fastboot)

* HARDWARE DETECTIVE
  Automatic device state detection. Polls native Windows WMI to 
  determine if a device is connected via ADB, Fastboot, MTK BROM, 
  or Qualcomm EDL.

* DRIVER MANAGER
  Integrated silent driver installer utilizing Windows pnputil for 
  seamless INF installation without leaving the application.

------------------------------------------------------------------------
                            SYSTEM REQUIREMENTS
------------------------------------------------------------------------

- OS: Windows 10 or Windows 11
- Python: Version 3.10 or higher
- Dependencies: customtkinter, wmi, pyinstaller, pyserial

------------------------------------------------------------------------
                           INSTALLATION & USAGE
------------------------------------------------------------------------

1. Clone the repository:
   git clone https://github.com/Rafyal/AutoFlash-Tool.git

2. Navigate to the directory:
   cd AutoFlash-Tool

3. Install the required Python libraries:
   pip install -r requirements.txt

4. Launch the application:
   python src/main.py

------------------------------------------------------------------------
                               DISCLAIMER
------------------------------------------------------------------------

WARNING: This tool performs low-level hardware flashing operations. 
Incorrect usage, flashing the wrong preloader, or formatting critical 
partitions (like nvram/nvdata) can result in a hard-bricked device. 
Always back up your partitions before executing write/erase operations. 
The author is not responsible for any damage caused to your device.

========================================================================
Author: Rafyal Dwi Putra
GitHub: https://github.com/Rafyal
========================================================================

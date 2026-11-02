.. raw:: html

   <a href="https://www.zephyrproject.org">
     <p align="center">
       <picture>
         <source media="(prefers-color-scheme: dark)" srcset="doc/_static/images/logo-readme-dark.svg">
         <source media="(prefers-color-scheme: light)" srcset="doc/_static/images/logo-readme-light.svg">
         <img src="doc/_static/images/logo-readme-light.svg">
       </picture>
     </p>
   </a>

   <a href="https://bestpractices.coreinfrastructure.org/projects/74"><img src="https://bestpractices.coreinfrastructure.org/projects/74/badge"></a>
   <a href="https://scorecard.dev/viewer/?uri=github.com/zephyrproject-rtos/zephyr"><img src="https://api.securityscorecards.dev/projects/github.com/zephyrproject-rtos/zephyr/badge"></a>
   <a href="https://github.com/zephyrproject-rtos/zephyr/actions/workflows/twister.yaml?query=branch%3Amain"><img src="https://github.com/zephyrproject-rtos/zephyr/actions/workflows/twister.yaml/badge.svg?event=push"></a>


Zephyr for the Allwinner F101
*****************************

This is a fork of the `Zephyr Project`_ with a port to the Allwinner F101
(``sun252i_f101``): a single T-Head XuanTie C907 core (``rv32imafdcv``, vector
extension, optional Sv32 MMU), internal SRAM and 16 MB PSRAM, no external DDR.

Boards
======

========================  =====================================================
``yuzukineko``            YuzukiHD Neko with the MIPI DSI carrier board: panel,
                          GT967 touch, SD card, USB, audio, AIC8800 WiFi/Bluetooth,
                          G2D and video engine. Console: UART1 (PB0/PB1).
``f101_evb``              The physical F101 EVB: RGB/LVDS/DSI panel options,
                          PWM backlight. Console: UART3 (PE8/PE9).
========================  =====================================================

SoC code is in ``soc/allwinner/sun252i_f101``, the devicetree in
``dts/riscv/allwinner/sun252i_f101.dtsi``, the boards in ``boards/yuzukihd``.

What is ported
==============

Drivers are written for Zephyr's own APIs, with bindings under
``dts/bindings/*/allwinner,sunxi-*.yaml``:

* clock and reset controller, pinctrl, GPIO, DMA, watchdog, hwinfo (SID fuses),
  CPU clock rate
* I2C, SPI, PWM (including panel backlight), ADC, SD/MMC (``sdhc``)
* SPIF SPI NOR flash controller: quad reads at 100 MHz with a tuned sample point,
  saved parameters, XIP window and XIP code sections
* audio: on-chip codec (DAC/ADC with analog part), I2S0, S/PDIF
* display: planes, TCON, RGB/LVDS/DSI encoders, D-PHY, backlight, scaling video
  plane for YUV/RGB pictures; MIPI DBI
* G2D 2D accelerator (``drivers/g2d``, ``include/zephyr/drivers/g2d.h``): fill,
  blit with format conversion, scaling and rotation, blend
* video engine (``drivers/vdec``): H.264, JPEG and PNG decoding
* USB: PHY, and CherryUSB device (CDC ACM, MSC, vendor display class) and host
  (EHCI/OHCI) ports; CherryUSB is a west project
* GT967 capacitive touch controller (``drivers/input``)
* RISC-V: vector extension context saving, a machine-mode Sv32 MMU with demand
  paging (RAM, file and swap backing stores), ``lib/mp4`` and an AAC decoder
  (``lib/opencore_aac``)

Build and run
=============

.. code-block:: console

   cd /path/to/zephyr
   source ./export.sh               # bash or zsh; source again in each new terminal
   f101.py build flash monitor

``f101.py`` defaults to YuzukiNeko and ``samples/hello_world``. It builds the
application, waits up to 60 seconds for FEL, writes SPI NOR, verifies the
image by reading it back, reboots from Flash, and monitors the UART. Hold FEL while
powering on/reconnecting the board when prompted. A single USB UART is selected
automatically; use ``-p`` if more than one is attached. Close any existing
picocom/serial monitor before running the command. The monitor opens before
the firmware starts, so it captures the first boot messages. Exit with ``Ctrl+]``.

Examples::

   f101.py menuconfig                     # configure the application interactively
   f101.py build                          # compile only
   f101.py flash monitor                  # also rebuilds before downloading
   f101.py -p /dev/ttyUSB0 monitor         # attach to an already running board
   f101.py --app samples/drivers/display build flash monitor
   f101.py ram monitor                    # temporary PSRAM test, no Flash writes
   f101.py -b f101_evb build ram monitor   # EVB currently supports RAM downloads

``menuconfig`` creates the build configuration if needed and uses the same
``--app``, ``-b`` and ``-d`` options as ``build``. Settings are saved in the build
directory's ``zephyr/.config``. Use ``f101.py menuconfig build`` to configure then
compile, or run ``f101.py build flash monitor`` afterwards. Copy settings that
should survive a pristine build into the application's ``prj.conf``.

Use ``-d`` for a custom build directory, ``--pristine`` to rebuild from scratch,
``--wait-fel`` to change the connection timeout, and ``--baud`` to change the
monitor baud rate (default 115200). ``flash`` now writes a persistent application
and installs the matching SyterKit loader automatically. This replaces the
factory boot environment. Before the first write, the entire 16 MiB Flash is
read twice and saved with its SHA-256 under ``flash-backups/<chip-SID>/``. The
original backup is retained across subsequent flashes; keep it for restoration.
It is outside ``build/`` and ignored by Git. A corrupt/incomplete backup or any
write verification failure stops the operation before continuing to the next step.

The loader has three copies at ``0``, ``0x10000``, and ``0x20000``. The application
has a 4 KiB header at ``0x200000`` and runs at ``0x40000000`` after boot. The
``0x2f000`` flash-training sector is preserved. No UF2 downloader is installed;
release PD5 at startup to run the application. Use ``ram`` for temporary tests.
Persistent flashing currently supports YuzukiNeko with 16 MiB SPI NOR.

Entering FEL still requires the board's button;
the USB UART's TX/RX wires alone do not provide automatic boot-mode control.

On Linux x86_64, ``export.sh`` prepares the Python environment with uv, west
modules, the XuanTie 900 Newlib V3.2.0 toolchain, xfel, and the pinned SyterKit
SPI NOR loader. It reuses existing
tools under ``.venv/`` and ``build/``. Missing system dependencies are installed
using apt on Debian/Ubuntu. Downloads and compilation run as the normal user.

The first run also installs a udev rule for the Allwinner FEL USB interface
(``1f3a:efe8``); installing system packages or this rule may ask for a sudo
password once. Subsequent ``xfel`` downloads do not need sudo for active desktop
users or members of ``plugdev``. Reconnect the board in FEL mode if necessary.
In a non-interactive terminal the script prints the command to finish USB setup::

   bash scripts/f101/setup.sh --usb-only

Use ``source ./export.sh --no-usb`` to prepare a build-only machine, or
``source ./export.sh --check`` to check existing tools without installing them.
The script does not flash or start firmware when sourced. For the F101 EVB,
replace ``-b yuzukineko`` with ``-b f101_evb`` and use a separate build directory.

The image is linked at ``0x40000000``. Without boot media it is loaded over USB
with ``xfel`` (FEL mode, power cycle before every download)::

   xfel version
   xfel ddr f101-s3
   xfel write 0x40000000 build/neko-hello/zephyr/zephyr.bin
   xfel exec 0x40000000

This runs the image in PSRAM until power-off. Open the UART console before
``exec`` to see the output: YuzukiNeko uses PB0 (TX) / PB1 (RX), F101 EVB uses
PE8 (TX) / PE9 (RX), both at 115200 8N1 with no flow control. USB FEL is not a
serial console.

Or write it to the SPI NOR flash and let the boot loader start it, see
``uf2-downloader`` in the ``zephyr-components`` repository (flash by copying a
``.uf2`` file onto a USB drive).

Samples for the hardware are under ``samples/drivers`` (``display``, ``g2d``,
``audio``, ``flash``, ``usb``, ``mp4_player``, ``vdec``, ``rvv``, ...) and
``samples/subsys`` (``demand_paging_*``, ``llext``). Applications built on this
port (emulators, WiFi, MicroPython, PocketJS, ...) live in ``zephyr-components``.

The rest of this file is the README of upstream Zephyr.

Zephyr Project
**************

The Zephyr Project is a scalable real-time operating system (RTOS) supporting
multiple hardware architectures, optimized for resource constrained devices,
and built with security in mind.

The Zephyr OS is based on a small-footprint kernel designed for use on
resource-constrained systems: from simple embedded environmental sensors and
LED wearables to sophisticated smart watches and IoT wireless gateways.

The Zephyr kernel supports multiple architectures, including ARM (Cortex-A,
Cortex-R, Cortex-M), Intel x86, ARC, Tensilica Xtensa, and RISC-V,
SPARC, MIPS, and a large number of `supported boards`_.

.. below included in doc/introduction/introduction.rst


Getting Started
***************

Welcome to Zephyr! See the `Introduction to Zephyr`_ for a high-level overview,
and the documentation's `Getting Started Guide`_ to start developing.

.. start_include_here

Community Support
*****************

Community support is provided via mailing lists and Discord; see the Resources
below for details.

.. _project-resources:

Resources
*********

Here's a quick summary of resources to help you find your way around:

Getting Started
---------------

  | 📖 `Zephyr Documentation`_
  | 🚀 `Getting Started Guide`_
  | 🙋🏽 `Tips when asking for help`_
  | 💻 `Code samples`_

Code and Development
--------------------

  | 🌐 `Source Code Repository`_
  | 📦 `Releases`_
  | 🤝 `Contribution Guide`_

Community and Support
---------------------

  | 💬 `Discord Server`_ for real-time community discussions
  | 📧 `User mailing list (users@lists.zephyrproject.org)`_
  | 📧 `Developer mailing list (devel@lists.zephyrproject.org)`_
  | 📬 `Other project mailing lists`_
  | 📚 `Project Wiki`_

Issue Tracking and Security
---------------------------

  | 🐛 `GitHub Issues`_
  | 🔒 `Security documentation`_
  | 🛡️ `Security Advisories Repository`_
  | ⚠️ Report security vulnerabilities at vulnerabilities@zephyrproject.org

Additional Resources
--------------------
  | 🌐 `Zephyr Project Website`_
  | 📺 `Zephyr Tech Talks`_

.. _Zephyr Project: https://www.zephyrproject.org
.. _Zephyr Project Website: https://www.zephyrproject.org
.. _Discord Server: https://chat.zephyrproject.org
.. _supported boards: https://docs.zephyrproject.org/latest/boards/index.html
.. _Zephyr Documentation: https://docs.zephyrproject.org
.. _Introduction to Zephyr: https://docs.zephyrproject.org/latest/introduction/index.html
.. _Getting Started Guide: https://docs.zephyrproject.org/latest/develop/getting_started/index.html
.. _Contribution Guide: https://docs.zephyrproject.org/latest/contribute/index.html
.. _Source Code Repository: https://github.com/zephyrproject-rtos/zephyr
.. _GitHub Issues: https://github.com/zephyrproject-rtos/zephyr/issues
.. _Releases: https://github.com/zephyrproject-rtos/zephyr/releases
.. _Project Wiki: https://github.com/zephyrproject-rtos/zephyr/wiki
.. _User mailing list (users@lists.zephyrproject.org): https://lists.zephyrproject.org/g/users
.. _Developer mailing list (devel@lists.zephyrproject.org): https://lists.zephyrproject.org/g/devel
.. _Other project mailing lists: https://lists.zephyrproject.org/g/main/subgroups
.. _Code samples: https://docs.zephyrproject.org/latest/samples/index.html
.. _Security documentation: https://docs.zephyrproject.org/latest/security/index.html
.. _Security Advisories Repository: https://github.com/zephyrproject-rtos/zephyr/security
.. _Tips when asking for help: https://docs.zephyrproject.org/latest/develop/getting_started/index.html#asking-for-help
.. _Zephyr Tech Talks: https://www.zephyrproject.org/tech-talks

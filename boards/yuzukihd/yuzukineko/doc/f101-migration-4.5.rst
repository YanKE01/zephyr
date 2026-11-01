.. SPDX-FileCopyrightText: Copyright (c) 2026 Yuzuki Tsuru
.. SPDX-License-Identifier: Apache-2.0

.. _f101-zephyr-4-5:

F101 on Zephyr 4.5.0
###################

Version set
***********

The ``zephyr-v4.5.0-f101`` branches of Zephyr and zephyr-components use the
``v4.5.0`` release, commit ``41d10b59730406bbab4ca9f1fbbe9e96aafb4966``.
Both ``yuzukineko`` and ``f101_evb`` retain their board-specific pin assignments.
The DTS memory layout remains 16 MiB at ``0x40000000``.

The west manifest follows the release's FatFs, LVGL 9.6, Mbed TLS 4 and
TF-PSA-Crypto revisions. CherryUSB and OpenCORE retain their existing pins.
Update only the projects needed by these boards:

.. code-block:: console

   west update --narrow fatfs lvgl mbedtls tf-psa-crypto tf-psa-crypto-drivers cherryusb opencore

Build environment
*****************

Use Python 3.12 or newer, CMake 3.28 or newer and Ninja. The tested cross
compiler is XuanTie GCC 14.1.1 from the workspace toolchains directory.
The build uses C17; OpenCORE keeps its module-specific C language setting.
Keep the 4.2 environment and old build directories for rollback.

From the workspace root, create a separate Python environment. The
``--without-pip`` path also works on hosts without the optional ensurepip package:

.. code-block:: console

   python3 -m venv --without-pip .venv-zephyr-4.5.0
   python3 -m pip --python .venv-zephyr-4.5.0 install -r zephyr/scripts/requirements-base.txt ninja
   . ./env.sh
   . .venv-zephyr-4.5.0/bin/activate
   export PATH="$WS/tools-local/usr/bin:$PATH"

Activating another virtual environment restores the previous PATH. Re-add
the local tools after activation so dtc and gperf remain available.
Use fresh output directories and check the build's exit status:

.. code-block:: console

   west build -b yuzukineko -d build/zephyr-4.5.0/hello-neko zephyr/samples/hello_world
   west build -b f101_evb -d build/zephyr-4.5.0/hello-evb zephyr/samples/hello_world
   west build -b yuzukineko -d build/zephyr-4.5.0/nekobox zephyr-components/nekobox
   west build -b yuzukineko -d build/zephyr-4.5.0/miracast zephyr-components/miracast/samples/receiver

Port interfaces
***************

* The C907 CPU binding uses ``riscv,isa-base`` and ``riscv,isa-extensions``.
  Cache instructions use the upstream ``RISCV_ISA_EXT_XTHEAD_CMO`` option.
* F101's per-bank GPIO binding is ``allwinner,sun252i-f101-gpio``. This keeps
  the upstream ``allwinner,sunxi-gpio`` binding available to its own driver.
* The display pipeline root inherits the display controller class, which
  LVGL now validates. Audio, SDHC and video decoder APIs use ``DEVICE_API``.
  SDHC reports four-bit support in ``sdhc_host_props``.
* RVV remains optional through ``CONFIG_SUN252I_F101_RVV``. Vector status is
  enabled before C startup, and the SoC exception frame preserves all vector
  registers. Generated offsets use the ``zephyr/`` header namespace.
* ``CONFIG_SUN252I_F101_MMU`` retains the machine-mode Sv32 data translation
  model. It cannot be combined with SMP, PMP userspace or supervisor mode.
  The architecture mapping operations return the status required by 4.5.
  The kernel image stays resident under the new demand-paging layout.
* File and swap backing stores reside in
  ``subsys/mem_mgmt/demand_paging/backing_store``. The sleeping backing-store
  option retains mutex serialization for SD-backed page I/O.
* The pinned CherryUSB OSAL receives the generated version-header include
  directory from the existing USB glue. LVGL custom blend hooks declare
  their descriptor types without recursively loading LVGL configuration.
  The RVV renderer follows LVGL 9.6's masked-fill and alpha-boundary rules.
* The AIC8800 Ethernet capability callback accepts the network interface.
  Its optional SAE backend uses TF-PSA-Crypto's legacy declarations and
  PSA curve configuration. EC multiplication supplies a random callback;
  the removed secp192r1 group is rejected.

Development boot
****************

RAM tests require initialized PSRAM and a verified F101 FEL connection.
The expected chip ID is ``0x00193700``; another ID is not an F101 test target.
Confirm that the USB device disappears when the target loses power.

XIP applications start at NOR offset ``0x80000``. Preserve the NOR parameter
sector at ``0x20000`` and keep the NOR boot area empty so power cycling returns
to FEL. Write and verify the application, then load a current FEL loader at
RAM address ``0x20000`` and execute it separately. The NOR and RAM addresses
refer to different address spaces. Use matching loader sources and verify
uploaded artifact hashes before execution.

Verification
************

The F101 driver/media samples and LVGL applications must compile on both
boards. Compile RVV, RAM paging, SD file paging and XIP configurations
separately. Host protocol checks are:

.. code-block:: console

   sh zephyr-components/dlna/tests/host/run.sh
   sh zephyr-components/nekobox/tests/streaming/run.sh
   sh zephyr-components/miracast/tests/host/run.sh
   sh zephyr-components/aic8800/tests/p2p/run.sh
   sh zephyr-components/nekobox/tests/miracast/run.sh

Build success and host tests do not establish display, touch, audio, SD,
Wi-Fi or Android wireless-display interoperability. Record fresh serial logs
and functional observations for each tested image. Paging needs memory
integrity checks, RVV needs its context-switch self-test, and LVGL's vector
renderer needs its scalar comparison test on the target.

Migration check results
=======================

The following checks passed with XuanTie GCC 14.1.1, Python 3.14.4 and
CMake 4.2.3:

* 53 builds from the 27 F101 driver/media, LVGL and paging samples across
  the two boards. The EVB touch drawing sample is excluded because that
  board has no ``zephyr,touch`` device.
* NekoBox's default XIP build with RVV rendering and the Miracast home app.
* The standalone Miracast receiver in RAM and XIP configurations.
* AIC8800 Wi-Fi scan with WPA3 enabled and the Bluetooth scan sample.
* Combined RVV, Sv32 MMU and XIP with anonymous paging on YuzukiNeko;
  a swap-backed configuration linked on the EVB.
* All five host suites listed above, including the sanitizer checks
  provided by those suites.

Target execution has not been verified for this release. No F101 FEL
target was available during these checks, and the connected board's power
wiring was not confirmed. RVV context switching, the LVGL scalar/vector
comparison, paging integrity, peripherals and Android wireless display
interoperability still require fresh board results.

Rollback
********

The preserved Zephyr branch is ``zephyr-v4.2.2-f101`` at ``839812c7e2b``;
zephyr-components uses ``main`` at ``ed8886e``. After saving any local changes,
switch both repositories and restore the old manifest's populated modules:

.. code-block:: console

   git -C zephyr switch zephyr-v4.2.2-f101
   git -C zephyr-components switch main
   . ./env.sh
   west update --narrow fatfs lvgl mbedtls cherryusb opencore

The additional PSA project checkouts can remain on disk; the old manifest
does not use them. Use the old environment and build directories with the
old branches, and the 4.5 environment and outputs with the new branches.

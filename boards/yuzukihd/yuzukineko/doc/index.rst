.. _yuzukineko:

YuzukiHD YuzukiNeko
###################

Overview
********

The YuzukiNeko is a development board built around the Allwinner F101
(``sun252i_f101``) SoC, which integrates a single T-Head Xuantie C907
RISC-V 32-bit core with floating-point, RVV 1.0 and Sv32 support, a PLIC,
a CLINT, internal SRAM/PSRAM and up to 6 UARTs. The SoC has no external DDR.

The port provides the SoC peripherals: GPIO, pinctrl, UART, I2C, SPI, PWM,
ADC, DMA, watchdog, the on-chip audio codec, I2S and S/PDIF, the USB device
and host controllers, the SD card slot, the 2D accelerator, the video engine
and the RGB, LVDS and MIPI DSI display pipelines. The carrier uses a
1024x768 DSI panel, GT967 touch controller and PWM backlight.

Memory
******

RAM images are linked at ``0x40000000``. The loader must initialize the
PSRAM before loading the image; use the ELF entry point when executing it.
The devicetree exposes 16 MiB, independently of the fitted PSRAM capacity.
UART1 uses PB00/PB01, mux function 4, at 115200 baud.

XIP applications provide their own flash overlay and loader. See
:ref:`f101-zephyr-4-5` for the build environment and development layout.

Build
*****

.. code-block:: console

   west build -b yuzukineko samples/hello_world

The resulting ``build/zephyr/zephyr.bin`` can be loaded into initialized
PSRAM through FEL. Development images do not require installing a NOR
bootloader.

.. toctree::
   :maxdepth: 1

   f101-migration-4.5

References
**********

* `YuzukiHD <https://yuzukihd.top>`_

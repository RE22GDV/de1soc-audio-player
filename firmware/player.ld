/* Програма з адреси 0 у DDR3, стек нижче 1 МБ, трек із 2 МБ.
   Ті самі адреси є і на платі (DDR3 HPS), і в CPUlator. */
ENTRY(_start)

__stack_top = 0x00100000;
__blob_base = 0x00200000;

SECTIONS
{
    . = 0x00000000;
    .text   : { *crt0.o(.text) *(.text*) *(.rodata*) }
    .data   : { *(.data*) }
    . = ALIGN(4);
    .bss    : { __bss_start__ = .; *(.bss*) *(COMMON) . = ALIGN(4); __bss_end__ = .; }
}

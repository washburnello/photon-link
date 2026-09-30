"""Static analysis of the Photon Mono X mainboard firmware.

Finds the function that builds the "getstatus,..." response by locating the
literal-pool entry for the format string and then the Thumb LDR that loads it.
"""
import struct
import sys

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from capstone.arm import ARM_OP_MEM, ARM_REG_PC

FLASH = 0x08000000
data = open(sys.argv[1], "rb").read()
target = int(sys.argv[2], 0) + FLASH  # e.g. 0x903b


def pool_slots(value: int):
    """Addresses of 32-bit literals in the file equal to value."""
    pat = struct.pack("<I", value)
    out, i = [], 0
    while True:
        i = data.find(pat, i)
        if i < 0:
            break
        out.append(i)
        i += 1
    return out


slots = pool_slots(target)
print(f"format string {target:#010x} found in literal pool at: "
      f"{[hex(s + FLASH) for s in slots]}")

if not slots:
    sys.exit("not referenced directly (maybe loaded via a table)")

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
code = data
refs = []
for base in code:
    for insn in md.disasm(code[base:base + 4], base + FLASH, count=1):
        if insn.mnemonic.startswith("ldr") and len(insn.operands) == 2:
            op = insn.operands[1]
            if op.type == ARM_OP_MEM and op.mem.base == ARM_REG_PC:
                # PC-relative literal: compute the pool address it points at
                pc = (insn.address + 4) & ~3
                lit = pc + op.mem.disp
                if lit - FLASH in slots:
                    refs.append(insn.address)
print(f"\nldr sites loading it: {[hex(a) for a in refs]}")

for ref in refs:
    start = max(0, ref - 0x90)
    print(f"\n{'=' * 70}\nfunction around {ref:#010x}\n{'=' * 70}")
    for insn in md.disasm(code[start:ref + 0x100], start + FLASH):
        mark = "  <-- loads fmt" if insn.address == ref else ""
        print(f"  {insn.address:#010x}  {insn.mnemonic:8} "
              f"{insn.op_str}{mark}")

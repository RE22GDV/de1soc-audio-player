# -*- coding: utf-8 -*-
"""Читання шаблону програвача й складання ELF «програма + трек».

Компілятор на комп'ютері користувача не потрібен: програвач уже зібраний
(firmware/build/player.elf), а трек додається окремим сегментом за адресою
__blob_base. Вихідний файл — звичайний 32-розрядний ELF для ARM із
заголовками програми (їх читає CPUlator) і заголовками розділів (за ними
вантажить Monitor Program через GDB).
"""
import struct

EHDR = struct.Struct('<16sHHIIIIIHHHHHH')     # 52 байти
PHDR = struct.Struct('<IIIIIIII')             # 32 байти
SHDR = struct.Struct('<IIIIIIIIII')           # 40 байтів
SYM = struct.Struct('<IIIBBH')                # 16 байтів

PT_LOAD = 1
SHT_PROGBITS, SHT_SYMTAB, SHT_STRTAB, SHT_NOBITS = 1, 2, 3, 8
SHF_WRITE, SHF_ALLOC, SHF_EXEC = 1, 2, 4
EM_ARM = 40


class ElfError(Exception):
    pass


def read(raw):
    """Повертає словник: entry, flags, сегменти LOAD, символи."""
    if raw[:4] != b'\x7fELF' or raw[4] != 1 or raw[5] != 1:
        raise ElfError('це не 32-розрядний ELF із прямим порядком байтів')
    (ident, etype, machine, ver, entry, phoff, shoff, flags, ehsize,
     phentsize, phnum, shentsize, shnum, shstrndx) = EHDR.unpack_from(raw, 0)
    if machine != EM_ARM:
        raise ElfError('ELF не для ARM (e_machine=%d)' % machine)
    segs = []
    for i in range(phnum):
        p = PHDR.unpack_from(raw, phoff + i * phentsize)
        if p[0] == PT_LOAD:
            typ, off, vaddr, paddr, filesz, memsz, pflags, align = p
            segs.append({'vaddr': vaddr, 'filesz': filesz, 'memsz': memsz, 'flags': pflags,
                         'data': raw[off:off + filesz]})
    sects = [SHDR.unpack_from(raw, shoff + i * shentsize) for i in range(shnum)]
    symbols = {}
    for s in sects:
        if s[1] == SHT_SYMTAB:
            strtab = sects[s[6]]
            sbase = strtab[4]
            for k in range(s[5] // SYM.size):
                name, value, size, info, other, shndx = SYM.unpack_from(raw, s[4] + k * SYM.size)
                end = raw.index(b'\0', sbase + name)
                nm = raw[sbase + name:end].decode('ascii', 'replace')
                if nm:
                    symbols[nm] = value
    return {'entry': entry, 'flags': flags, 'segments': segs, 'symbols': symbols}


def template_info(raw):
    t = read(raw)
    if '__blob_base' not in t['symbols']:
        raise ElfError('у шаблоні немає символу __blob_base')
    return t


def build(template_raw, blob):
    """Шаблон програвача + трек -> bytes нового ELF."""
    t = template_info(template_raw)
    base = t['symbols']['__blob_base']
    for s in t['segments']:
        if s['vaddr'] < base + len(blob) and base < s['vaddr'] + s['memsz']:
            raise ElfError('трек перекривається з програмою')

    loads = [(s['vaddr'], s['data'], s['memsz'], s['flags']) for s in t['segments']]
    loads.append((base, blob, len(blob), 4))          # R

    n_ph = len(loads)
    off = EHDR.size + n_ph * PHDR.size
    body = bytearray()
    ph = []
    placed = []
    for vaddr, data, memsz, pflags in loads:
        pad = (-(off + len(body))) % 4
        body += b'\0' * pad
        foff = off + len(body)
        ph.append(PHDR.pack(PT_LOAD, foff, vaddr, vaddr, len(data), memsz, pflags, 4))
        placed.append((foff, vaddr, len(data), memsz))
        body += data

    # таблиця символів: _start і __blob_base
    strtab = b'\0_start\0__blob_base\0'
    shstr = b'\0.text\0.bss\0.blob\0.symtab\0.strtab\0.shstrtab\0'

    def sname(n):
        return shstr.index(n.encode() + b'\0')

    sections = [SHDR.pack(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)]
    text_idx = None
    for k, (foff, vaddr, filesz, memsz) in enumerate(placed[:-1]):
        sections.append(SHDR.pack(sname('.text'), SHT_PROGBITS, SHF_ALLOC | SHF_EXEC | SHF_WRITE,
                                  vaddr, foff, filesz, 0, 0, 4, 0))
        if text_idx is None:
            text_idx = len(sections) - 1
        if memsz > filesz:
            sections.append(SHDR.pack(sname('.bss'), SHT_NOBITS, SHF_ALLOC | SHF_WRITE,
                                      vaddr + filesz, foff + filesz, memsz - filesz, 0, 0, 4, 0))
    foff, vaddr, filesz, _ = placed[-1]
    sections.append(SHDR.pack(sname('.blob'), SHT_PROGBITS, SHF_ALLOC, vaddr, foff, filesz, 0, 0, 4, 0))

    syms = SYM.pack(0, 0, 0, 0, 0, 0)
    syms += SYM.pack(strtab.index(b'_start'), t['entry'], 0, 0x12, 0, text_idx)        # GLOBAL FUNC
    syms += SYM.pack(strtab.index(b'__blob_base'), base, 0, 0x10, 0, 0xFFF1)          # GLOBAL ABS

    tail = bytearray()
    tail_off = off + len(body)

    def put(data):
        nonlocal tail
        tail += b'\0' * ((-(tail_off + len(tail))) % 4)
        o = tail_off + len(tail)
        tail += data
        return o

    sym_off = put(syms)
    str_off = put(strtab)
    shs_off = put(shstr)
    strtab_idx = len(sections) + 1
    sections.append(SHDR.pack(sname('.symtab'), SHT_SYMTAB, 0, 0, sym_off, len(syms),
                              strtab_idx, 1, 4, SYM.size))
    sections.append(SHDR.pack(sname('.strtab'), SHT_STRTAB, 0, 0, str_off, len(strtab), 0, 0, 1, 0))
    sections.append(SHDR.pack(sname('.shstrtab'), SHT_STRTAB, 0, 0, shs_off, len(shstr), 0, 0, 1, 0))
    tail += b'\0' * ((-(tail_off + len(tail))) % 4)
    shoff = tail_off + len(tail)

    ident = b'\x7fELF\x01\x01\x01' + b'\0' * 9
    ehdr = EHDR.pack(ident, 2, EM_ARM, 1, t['entry'], EHDR.size, shoff, t['flags'], EHDR.size,
                     PHDR.size, n_ph, SHDR.size, len(sections), len(sections) - 1)
    return bytes(ehdr + b''.join(ph) + body + tail + b''.join(sections))


def to_srec(elf_raw):
    """Той самий вміст у форматі SREC (запасний варіант для Monitor Program)."""
    t = read(elf_raw)
    lines = ['S0030000FC']                       # порожній заголовний запис
    for s in t['segments']:
        data, addr = s['data'], s['vaddr']
        for i in range(0, len(data), 32):
            chunk = data[i:i + 32]
            a = addr + i
            rec = bytes([len(chunk) + 5]) + a.to_bytes(4, 'big') + chunk
            cs = (~sum(rec)) & 0xFF
            lines.append('S3' + rec.hex().upper() + '%02X' % cs)
    rec = bytes([5]) + t['entry'].to_bytes(4, 'big')
    lines.append('S7' + rec.hex().upper() + '%02X' % ((~sum(rec)) & 0xFF))
    return ('\n'.join(lines) + '\n').encode('ascii')

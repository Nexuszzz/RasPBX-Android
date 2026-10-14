"""Read-only MBR, FAT and ext2/3/4 inspection. Never mounts or executes image code.

This targeted reader does not replay journals or validate ext4 checksums. It is
for offline inspection, not filesystem repair or arbitrary untrusted disk images.
"""
from __future__ import annotations
import json
import math
import os
import stat
import struct
from pathlib import PurePosixPath


def u16(data, offset=0):
    return struct.unpack_from('<H', data, offset)[0]


def u32(data, offset=0):
    return struct.unpack_from('<I', data, offset)[0]


class Disk:
    def __init__(self, path):
        self.path = os.fspath(path)
        self.size = os.path.getsize(path)
        self.handle = open(path, 'rb')
        mbr = self.read(0, 512)
        if mbr[510:512] != b'\x55\xaa':
            raise ValueError('Not a supported MBR image')
        self.partitions = []
        for i in range(4):
            start = 446 + 16 * i
            kind = mbr[start + 4]
            if kind:
                sector, count = u32(mbr, start + 8), u32(mbr, start + 12)
                if (sector + count) * 512 > self.size:
                    raise ValueError('Partition exceeds image')
                self.partitions.append(dict(index=i + 1, type=hex(kind),
                    start_sector=sector, sectors=count, offset=sector * 512,
                    bytes=count * 512))
        self.signature = f'{u32(mbr, 440):08x}'

    def read(self, offset, length):
        if offset < 0 or length < 0 or offset + length > self.size:
            raise ValueError('Read outside disk')
        self.handle.seek(offset)
        result = self.handle.read(length)
        if len(result) != length:
            raise ValueError('Short image read')
        return result

    def close(self):
        self.handle.close()


class Ext:
    def __init__(self, disk, partition):
        self.disk, self.partition = disk, partition
        self.offset = partition['offset']
        sb = self.read(1024, 1024)
        if u16(sb, 56) != 0xef53:
            raise ValueError('Not an ext filesystem')
        self.block_size = 1024 << u32(sb, 24)
        self.inodes_per_group = u32(sb, 40)
        self.inode_size = u16(sb, 88) or 128
        self.incompat = u32(sb, 96)
        self.descriptor_size = max(32, u16(sb, 254)) if self.incompat & 0x80 else 32
        self.block_count = u32(sb, 4) | ((u32(sb, 336) << 32) if self.incompat & 0x80 else 0)
        self.superblock = dict(block_size=self.block_size, blocks=self.block_count,
            free_blocks=u32(sb, 12), inodes=u32(sb, 0), free_inodes=u32(sb, 16),
            inode_size=self.inode_size, label=sb[120:136].split(b'\0')[0].decode('utf-8','replace'),
            uuid=sb[104:120].hex(), state=u16(sb, 58),
            features_compat=hex(u32(sb, 92)), features_incompat=hex(self.incompat),
            features_ro_compat=hex(u32(sb, 100)), last_mount_time=u32(sb, 44),
            last_write_time=u32(sb, 48), last_check_time=u32(sb, 64),
            journal_inode=u32(sb, 224))
        if not (1024 <= self.block_size <= 65536) or not self.inodes_per_group:
            raise ValueError('Unsupported ext geometry')
        if self.incompat & (0x10 | 0x8000 | 0x10000) or u32(sb, 100) & 0x200:
            raise ValueError('Unsupported meta_bg, bigalloc/encryption/inline-data filesystem')
        self._inodes = {}

    def read(self, offset, length):
        if offset < 0 or offset + length > self.partition['bytes']:
            raise ValueError('Read outside partition')
        return self.disk.read(self.offset + offset, length)

    def block(self, number):
        if not 0 < number < self.block_count:
            raise ValueError('Invalid ext block')
        return self.read(number * self.block_size, self.block_size)

    def inode(self, number):
        if number in self._inodes:
            return self._inodes[number]
        if number < 1 or number > self.superblock['inodes']:
            raise ValueError('Invalid inode')
        group, index = divmod(number - 1, self.inodes_per_group)
        desc_start = (2 if self.block_size == 1024 else 1) * self.block_size
        desc = self.read(desc_start + group * self.descriptor_size, self.descriptor_size)
        table = u32(desc, 8) | ((u32(desc, 40) << 32) if self.descriptor_size >= 64 else 0)
        raw = self.read(table * self.block_size + index * self.inode_size, self.inode_size)
        mode = u16(raw)
        size = u32(raw, 4) | ((u32(raw, 108) << 32) if stat.S_ISREG(mode) else 0)
        result = dict(inode=number, mode=mode, size=size, flags=u32(raw, 32),
                      mtime=u32(raw, 16), blocks_512=u32(raw, 28), data=raw[40:100])
        self._inodes[number] = result
        return result

    def _extents(self, raw, expected_depth=None):
        magic, entries, maximum, depth = struct.unpack_from('<HHHH', raw)
        if magic != 0xf30a or entries > maximum or 12 + entries * 12 > len(raw) or depth > 5:
            raise ValueError('Invalid extents')
        if expected_depth is not None and depth != expected_depth:
            raise ValueError('Invalid extent depth')
        for i in range(entries):
            at = 12 + i * 12
            logical = u32(raw, at)
            if depth:
                child = u32(raw, at + 4) | (u16(raw, at + 8) << 32)
                yield from self._extents(self.block(child), depth - 1)
            else:
                length = u16(raw, at + 4)
                uninitialized = length > 32768
                count = length - 32768 if uninitialized else length
                physical = u32(raw, at + 8) | (u16(raw, at + 6) << 32)
                yield logical, count, (0 if uninitialized else physical)

    def _indirect(self, block, depth):
        count = self.block_size // 4
        if not block:
            for _ in range(count ** depth):
                yield 0
            return
        pointers = struct.unpack('<' + 'I' * count, self.block(block))
        for pointer in pointers:
            if depth == 1:
                yield pointer
            else:
                yield from self._indirect(pointer, depth - 1)

    def contents(self, number, max_bytes=16 * 1024 * 1024):
        item = self.inode(number)
        size = item['size']
        if size > max_bytes:
            raise ValueError(f'File exceeds read limit: {size}')
        if stat.S_ISLNK(item['mode']) and size <= 60 and item['blocks_512'] == 0:
            return item['data'][:size]
        output = bytearray(size)
        if item['flags'] & 0x80000:
            for logical, count, physical in self._extents(item['data']):
                begin = logical * self.block_size
                length = min(count * self.block_size, size - begin)
                if length > 0 and physical:
                    output[begin:begin+length] = self.read(physical * self.block_size, length)
        else:
            ptrs = struct.unpack('<15I', item['data'])
            def pointers():
                yield from ptrs[:12]
                for depth, pointer in enumerate(ptrs[12:], 1):
                    yield from self._indirect(pointer, depth)
            for i, pointer in enumerate(pointers()):
                begin = i * self.block_size
                if begin >= size:
                    break
                length = min(self.block_size, size - begin)
                if pointer:
                    output[begin:begin+length] = self.read(pointer * self.block_size, length)
        return bytes(output)

    def entries(self, number):
        if not stat.S_ISDIR(self.inode(number)['mode']):
            raise ValueError('Not a directory')
        raw = self.contents(number)
        offset = 0
        while offset + 8 <= len(raw):
            inode, record_len, name_len, kind = struct.unpack_from('<IHBB', raw, offset)
            if record_len < 8 or offset + record_len > len(raw) or name_len > record_len - 8:
                raise ValueError('Invalid ext directory record')
            if inode and name_len:
                name = raw[offset + 8:offset + 8 + name_len].decode('utf-8', 'surrogateescape')
                if name not in ('.', '..'):
                    yield name, inode, kind
            offset += record_len

    def resolve(self, path, follow_symlinks=True, depth=0):
        if depth > 16:
            raise ValueError('Too many symbolic links')
        parts = PurePosixPath('/' + path.lstrip('/')).parts[1:]
        current = 2
        traversed = []
        for i, part in enumerate(parts):
            if part in ('', '.'):
                continue
            if part == '..':
                raise ValueError('Parent traversal unsupported')
            names = {name: number for name, number, _ in self.entries(current)}
            if part not in names:
                raise FileNotFoundError(path)
            current = names[part]
            if follow_symlinks and stat.S_ISLNK(self.inode(current)['mode']):
                target = self.contents(current).decode('utf-8', 'surrogateescape')
                base = target if target.startswith('/') else '/' + '/'.join(traversed + [target])
                normalized = os.path.normpath(base.replace('/', os.sep)).replace(os.sep, '/')
                return self.resolve(normalized + '/' + '/'.join(parts[i+1:]), True, depth + 1)
            traversed.append(part)
        return current

    def file(self, path, max_bytes=16 * 1024 * 1024):
        return self.contents(self.resolve(path), max_bytes)

    def walk(self, number=2, prefix='', visited=None):
        visited = set() if visited is None else visited
        if number in visited:
            return
        visited.add(number)
        for name, child, kind in self.entries(number):
            path = prefix + '/' + name
            item = self.inode(child)
            yield path, item
            if stat.S_ISDIR(item['mode']):
                yield from self.walk(child, path, visited)


class Fat:
    def __init__(self, disk, partition):
        self.disk, self.partition = disk, partition
        self.offset = partition['offset']
        bpb = disk.read(self.offset, 512)
        self.sector_size, self.cluster_sectors = u16(bpb, 11), bpb[13]
        self.reserved, self.fats, self.root_count = u16(bpb, 14), bpb[16], u16(bpb, 17)
        self.fat_sectors = u16(bpb, 22) or u32(bpb, 36)
        total = u16(bpb, 19) or u32(bpb, 32)
        self.root_sectors = math.ceil(self.root_count * 32 / self.sector_size)
        self.data_sector = self.reserved + self.fats * self.fat_sectors + self.root_sectors
        clusters = (total - self.data_sector) // self.cluster_sectors
        self.bits = 12 if clusters < 4085 else 16 if clusters < 65525 else 32
        if self.bits == 12:
            raise ValueError('FAT12 not supported')
        self.root_cluster = u32(bpb, 44) if self.bits == 32 else 0
        self.cluster_bytes = self.cluster_sectors * self.sector_size
        self.table = disk.read(self.offset + self.reserved * self.sector_size, self.fat_sectors * self.sector_size)

    def chain(self, first):
        seen = set()
        current = first
        maximum = 0xfff8 if self.bits == 16 else 0xffffff8
        while 2 <= current < maximum:
            if current in seen:
                raise ValueError('FAT chain loop')
            seen.add(current)
            position = self.data_sector * self.sector_size + (current - 2) * self.cluster_bytes
            if position + self.cluster_bytes > self.partition['bytes']:
                raise ValueError('Cluster outside partition')
            yield self.disk.read(self.offset + position, self.cluster_bytes)
            current = u16(self.table, current * 2) if self.bits == 16 else u32(self.table, current * 4) & 0xfffffff

    def directory(self, cluster=None):
        if cluster is None and self.bits == 16:
            at = self.offset + (self.reserved + self.fats * self.fat_sectors) * self.sector_size
            raw = self.disk.read(at, self.root_count * 32)
        else:
            raw = b''.join(self.chain(self.root_cluster if cluster is None else cluster))
        lfn = []
        for at in range(0, len(raw), 32):
            rec = raw[at:at+32]
            if rec[0] == 0:
                break
            if rec[0] == 0xe5:
                lfn = []
                continue
            if rec[11] == 0x0f:
                chunk = rec[1:11] + rec[14:26] + rec[28:32]
                lfn.insert(0, chunk)
                continue
            short = rec[:8].decode('ascii', 'replace').rstrip() + ('.' + rec[8:11].decode('ascii','replace').rstrip() if rec[8:11].strip() else '')
            name = b''.join(lfn).decode('utf-16le','replace').split('\0')[0].rstrip('\uffff') if lfn else short
            lfn = []
            if rec[11] & 8 or name in ('.','..'):
                continue
            first = u16(rec, 26) | (u16(rec, 20) << 16 if self.bits == 32 else 0)
            yield dict(name=name, cluster=first, directory=bool(rec[11] & 16), size=u32(rec, 28))

    def file(self, name):
        for entry in self.directory():
            if entry['name'].lower() == name.lower() and not entry['directory']:
                return b''.join(self.chain(entry['cluster']))[:entry['size']]
        raise FileNotFoundError(name)


def open_image(path):
    disk = Disk(path)
    try:
        boot = Fat(disk, next(p for p in disk.partitions if p['type'] in ('0xb','0xc','0x6','0xe')))
        root = Ext(disk, next(p for p in disk.partitions if p['type'] == '0x83'))
        return disk, boot, root
    except Exception:
        disk.close()
        raise

#!/usr/local/bin/python3
"""
Analyze PKZIP file contents

 * scan entire file for PKxy headers
 * do quick scan by locating EOF header
 * can operate on .zip files from a http://URL

(C) 2016 Willem Hengeveld  <itsme@xs4all.nl>
"""

from __future__ import division, print_function, absolute_import, unicode_literals
import sys
import os
import binascii
import struct
import datetime
import zlib
import itertools
if sys.version_info[0] == 2:
    import scandir
    os.scandir = scandir.scandir


def zip_decrypt(data, pw):
    """
    INPUT: data  - an array of bytes
           pw    - either a tuple of 3 dwords, or a byte array.
    OUTPUT: a decrypted array of bytes.

    The very weak 'zip' encryption

    This encryption can be cracked using tools like pkcrack.
    Pkcrack does a known plaintext attack, requiring 13 bytes of plaintext.
    """
    def make_crc_tab(poly):
        def calcentry(v, poly):
            for _ in range(8):
                v = (v>>1) ^ (poly if v&1 else 0)
            return v
        return [ calcentry(byte, poly) for byte in range(256) ]

    crctab = make_crc_tab(0xedb88320)

    def crc32(crc, byte):
        return crctab[(crc^byte)&0xff] ^ (crc>>8)

    def updatekeys(keys, byte):
        keys[0] = crc32(keys[0], byte)
        keys[1] = ((keys[1] + (keys[0]&0xFF)) * 134775813 + 1)&0xFFFFFFFF
        keys[2] = crc32(keys[2], keys[1]>>24)

    keys = [ 0x12345678, 0x23456789, 0x34567890 ]
    if type(pw)==list:
        keys = pw
    else:
        for c in pw:
            updatekeys(keys, c)

    for blk in data:
        u = bytearray()
        for b in bytearray(blk):
            xor = (keys[2] | 2)&0xFFFF
            xor = ((xor * (xor^1))>>8) & 0xFF
            b = b ^ xor
            u.append(b)
            updatekeys(keys, b)
        yield u

def skipbytes(blks, skip, args):
    """
    skip the first <skip> bytes of a stream of byte blocks.
    """
    skipped = b''
    for blk in blks:
        if skip >= len(blk):
            skip -= len(blk)
            skipped += blk
        elif skip:
            skipped += blk[:skip]
            if args.verbose:
                print("CRYPTHEADER: %s" % binascii.b2a_hex(skipped))
                sys.stdout.flush()
            yield blk[skip:]
            skip = 0
        else:
            yield blk

def decode_name(name):
    nonprint = set('\u0009\u000b\u000c\u001c\u001d\u001e\u001f\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2008\u2009\u200a\u2028\u2029\u205f\u3000')
    try:
        utf8 = name.decode('utf-8', 'strict')
        if not nonprint & set(utf8) and utf8.isprintable():
            return utf8
    except:
        pass
    return "hex-%s" % binascii.b2a_hex(name)

class EntryBase(object):
    """ base class for PK headers """
    def loaditems(self, fh):
        """ loads any items refered to by the header """
        pass

def decodedatetime(ts):
    def decode_date(dt):
        if dt==0:
            return datetime.datetime(1980,1,1)
        year, mon, day = (dt>>9), (dt>>5)&15, dt&31
        try:
            return datetime.datetime(year+1980, mon, day)
        except Exception as e:
            print("error decoding date %d-%d-%d" % (year+1980, mon, day))
            return datetime.datetime(1980,1,1)
    def decode_time(tm):
        hour, minute, bisecond = tm>>11, (tm>>5)&63, tm&31
        return datetime.timedelta(hours=hour, minutes=minute, seconds=bisecond*2)

    return decode_date(ts>>16) + decode_time(ts & 0xFFFF)

######################################################
#  Decoder classes
######################################################

class CentralDirEntry(EntryBase):
    HeaderSize = 42
    MagicNumber = b'\x01\x02'

    def __init__(self, baseofs, data, ofs):
        self.pkOffset = baseofs + ofs - 4

        self.createVersion, self.neededVersion, self.flags, self.method, self.timestamp, \
            self.crc32, self.compressedSize, self.originalSize, self.nameLength, self.extraLength, \
            self.commentLength, self.diskNrStart, self.zipAttrs, self.osAttrs, self.dataOfs = \
            struct.unpack_from("<4H4L5HLL", data, ofs)
        ofs += self.HeaderSize

        self.nameOffset = baseofs + ofs
        ofs += self.nameLength

        self.extraOffset = baseofs + ofs
        ofs += self.extraLength

        self.commentOffset = baseofs + ofs
        ofs += self.commentLength

        self.endOffset = baseofs + ofs

        self.name = None
        self.extra = None
        self.comment = None

    def loaditems(self, fh):
        fh.seek(self.nameOffset)
        self.name = decode_name(fh.read(self.nameLength))
        fh.seek(self.extraOffset)
        self.extra = fh.read(self.extraLength)
        fh.seek(self.commentOffset)
        self.comment = fh.read(self.commentLength).decode("utf-8", "ignore")

    def summary(self):
        def flagdesc(fl):
            if fl&64: return "AES"
            if fl&1: return "CRYPT"
            return ""
        return "%10d (%5.1f%%)  %s  %08x [%5s] %s" % (
                self.originalSize,
                100.0*self.compressedSize/self.originalSize if self.originalSize else 0,
                decodedatetime(self.timestamp),
                self.crc32,
                flagdesc(self.flags),
                self.name
                )

    def __repr__(self):
        r = "PK.0102: %04x %04x %04x %04x %08x %08x %08x %08x %04x %04x %04x %04x %04x %08x %08x |  %08x %08x %08x %08x" % (
            self.createVersion, self.neededVersion, self.flags, self.method, self.timestamp,
            self.crc32, self.compressedSize, self.originalSize, self.nameLength, self.extraLength,
            self.commentLength, self.diskNrStart, self.zipAttrs, self.osAttrs, self.dataOfs,
            self.nameOffset, self.extraOffset, self.commentOffset, self.endOffset)
        if self.name:
            r += " - " + self.name
        return r


class LocalFileHeader(EntryBase):
    HeaderSize = 26
    MagicNumber = b'\x03\x04'

    def __init__(self, baseofs, data, ofs):
        self.pkOffset = baseofs + ofs - 4

        self.neededVersion, self.flags, self.method, self.timestamp, self.crc32, \
            self.compressedSize, self.originalSize, self.nameLength, self.extraLength = \
            struct.unpack_from("<3H4LHH", data, ofs)
        ofs += self.HeaderSize

        self.nameOffset = baseofs + ofs
        ofs += self.nameLength

        self.extraOffset = baseofs + ofs
        ofs += self.extraLength

        self.dataOffset = baseofs + ofs
        ofs += self.compressedSize

        self.endOffset = baseofs + ofs

        self.name = None
        self.extra = None
        self.data = None

    def loaditems(self, fh):
        fh.seek(self.nameOffset)
        self.name = decode_name(fh.read(self.nameLength))
        fh.seek(self.extraOffset)
        self.extra = fh.read(self.extraLength)
        # not loading data

    def __repr__(self):
        r = "PK.0304: %04x %04x %04x %08x %08x %08x %08x %04x %04x |  %08x %08x %08x %08x" % (
            self.neededVersion, self.flags, self.method, self.timestamp, self.crc32,
            self.compressedSize, self.originalSize, self.nameLength, self.extraLength,
            self.nameOffset, self.extraOffset, self.dataOffset, self.endOffset)
        if self.name:
            r += " - " + self.name
        return r


class EndOfCentralDir(EntryBase):
    HeaderSize = 18
    MagicNumber = b'\x05\x06'

    def __init__(self, baseofs, data, ofs):
        self.pkOffset = baseofs + ofs - 4

        self.thisDiskNr, self.startDiskNr, self.thisEntries, self.totalEntries, self.dirSize, self.dirOffset, self.commentLength = \
            struct.unpack_from("<4HLLH", data, ofs)
        ofs += self.HeaderSize

        self.commentOffset = baseofs + ofs
        ofs += self.commentLength

        self.endOffset = baseofs + ofs

        self.comment = None

    def loaditems(self, fh):
        if not self.commentLength:
            return
        fh.seek(self.commentOffset)
        self.comment = fh.read(self.commentLength)
        if self.comment.startswith(b'signed by SignApk'):
            self.comment = repr(self.comment[:17]) + str(binascii.b2a_hex(self.comment[18:]), 'ascii')
        else:
            self.comment = self.comment.decode('utf-8', 'ignore')

    def summary(self):
        if self.thisEntries==self.totalEntries:
            r = "EOD: %d entries" % (self.totalEntries)
        else:
            r = "Spanned archive %d .. %d  ( %d of %d entries )" % (self.startDiskNr, self.thisDiskNr, self.thisEntries, self.totalEntries)
        r += ", %d byte directory" % self.dirSize
        return r

    def __repr__(self):
        r = "PK.0506: %04x %04x %04x %04x %08x %08x %04x |  %08x %08x" % (
            self.thisDiskNr, self.startDiskNr, self.thisEntries, self.totalEntries, self.dirSize, self.dirOffset, self.commentLength,
            self.commentOffset, self.endOffset)
        return r


class DataDescriptor(EntryBase):
    HeaderSize = 12
    MagicNumber = b'\x07\x08'

    def __init__(self, baseofs, data, ofs):
        self.pkOffset = baseofs + ofs - 4

        self.crc, self.compSize, self.uncompSize = \
            struct.unpack_from("<3L", data, ofs)
        ofs += self.HeaderSize

        self.endOffset = baseofs + ofs

    def __repr__(self):
        return "PK.0708: %08x %08x %08x |  %08x" % (
            self.crc, self.compSize, self.uncompSize,
            self.endOffset)


# todo
class Zip64EndOfDir(EntryBase):
    HeaderSize = 0
    MagicNumber = b'\x06\x06'

    def __init__(self, baseofs, data, ofs):
        self.pkOffset = baseofs + ofs - 4


class Zip64EndOfDirLocator(EntryBase):
    HeaderSize = 0
    MagicNumber = b'\x06\x07'

    def __init__(self, baseofs, data, ofs):
        self.pkOffset = baseofs + ofs - 4


class ExtraEntry(EntryBase):
    HeaderSize = 0
    MagicNumber = b'\x06\x08'

    def __init__(self, baseofs, data, ofs):
        self.pkOffset = baseofs + ofs - 4


class SpannedArchive(EntryBase):
    HeaderSize = 0
    MagicNumber = b'\x03\x03'

    def __init__(self, baseofs, data, ofs):
        self.pkOffset = baseofs + ofs - 4


class ArchiveSignature(EntryBase):
    HeaderSize = 0
    MagicNumber = b'\x05\x05'

    def __init__(self, baseofs, data, ofs):
        self.pkOffset = baseofs + ofs - 4


def getDecoderClass(typ):
    """ Return Decoder class for the PK type. """
    for cls in (CentralDirEntry, LocalFileHeader, EndOfCentralDir, DataDescriptor, Zip64EndOfDir, Zip64EndOfDirLocator, ExtraEntry, SpannedArchive, ArchiveSignature):
        if cls.MagicNumber == typ:
            return cls


def findPKHeaders(args, fh):
    """ Scan the entire file for PK headers. """

    def processchunk(o, chunk):
        n = -1
        while True:
            n = chunk.find(b'PK', n+1)
            if n == -1 or n+4 > len(chunk):
                break
            cls = getDecoderClass(chunk[n+2:n+4])
            if cls:
                hdrEnd = n+4+cls.HeaderSize
                if hdrEnd > len(chunk):
                    continue

                # todo: skip entries entirely within repeated chunk
                # if n<64 and hdrEnd>64:
                #    continue

                yield cls(o, chunk, n+4)

    prev = b''
    o = 0
    if args.offset:
        fh.seek(args.offset, os.SEEK_SET if args.offset >= 0 else os.SEEK_END)
        o = args.offset
    while args.length is None or o < args.length:
        want = args.chunksize
        if args.length is not None and want > args.length - o:
            want = args.length - o
        fh.seek(o)
        chunk = fh.read(want)
        if len(chunk) == 0:
            break
        for ch in processchunk(o-len(prev), prev+chunk):
            yield ch

        # 64 so all header types would fit, exclusive their variable size parts
        prev = chunk[-64:]
        o += len(chunk)


def quickScanZip(args, fh):
    """ Do a quick scan of the .zip file, starting by locating the EOD marker. """
    # 100 bytes is the smallest .zip possible

    fh.seek(0, 2)
    fsize = fh.tell()
    if fsize==0:
        print("Empty file")
        return
    if fsize<100:
        print("Zip too small: %d bytes, minimum zip is 100 bytes" % fsize)
        return
    fh.seek(-100, 2)

    eoddata = fh.read()
    iEND = eoddata.find(b'PK\x05\x06')
    if iEND==-1:
        # try with larger chunk
        ofs = max(fh.tell()-0x10100, 0)
        fh.seek(ofs, 0)
        eoddata = fh.read()
        iEND = eoddata.find(b'PK\x05\x06')
        if iEND==-1:
            print("expected PK0506 - probably not a PKZIP file")
            return
    else:
        ofs = fh.tell()-0x100
    eod = EndOfCentralDir(ofs, eoddata, iEND+4)
    yield eod

    dirofs = eod.dirOffset
    for _ in range(eod.thisEntries):
        fh.seek(dirofs)
        dirdata = fh.read(46)
        if dirdata[:4] != b'PK\x01\x02':
            print("expected PK0102")
            return
        dirent = CentralDirEntry(dirofs, dirdata, 4)

        yield dirent
        dirofs = dirent.endOffset

def zipraw(fh, ent):
    if isinstance(ent, CentralDirEntry):
        # find LocalFileHeader
        fh.seek(ent.dataOfs)
        data = fh.read(4+LocalFileHeader.HeaderSize)
        dirent = ent
        ent = LocalFileHeader(ent.dataOfs, data, 4)

        ent.loaditems(fh)

    fh.seek(ent.dataOffset)
    nread = 0
    while nread < ent.compressedSize:
        want = min(ent.compressedSize-nread, 0x10000)
        block = fh.read(want)
        if len(block)==0:
            break
        yield block
        nread += len(block)

def blockdump(baseofs, blks):
    o = baseofs
    for blk in blks:
        print("%08x: %s" % (o, binascii.b2a_hex(blk)))
        o += len(blk)

def zipcat(blks, ent):
    if ent.method==8:
        C = zlib.decompressobj(-15)
        for block in blks:
            yield C.decompress(block)
        yield C.flush()
    elif ent.method==0:
        yield from blks
    else:
        print("unknown compression method")


def namegenerator(name):
    yield name
    paths = name.rsplit('/', 1)
    parts = paths[-1].rsplit('.', 1)

    if len(paths)>1:
        part0 = "%s/%s" % ("".join(paths[:-1]), parts[0])
    else:
        part0 = parts[0]

    if len(parts)>1:
        part1 = ".%s" % (parts[1])
    else:
        part1 = ""

    for i in itertools.count(1):
        yield "%s-%d%s" % (part0, i, part1)

def savefile(outdir, name, data):
    os.makedirs(os.path.dirname(os.path.join(outdir, name)), exist_ok=True)
    for namei in namegenerator(name):
        path = os.path.join(outdir, namei)
        if not os.path.exists(path):
            break
    with open(path, "wb") as fh:
        fh.writelines(data)

def getbytes(fh, ofs, size):
    fh.seek(ofs)
    return fh.read(size)
    
def processfile(args, fh):
    """ Process one opened file / url. """
    if args.quick:
        scanner = quickScanZip(args, fh)
    else:
        scanner = findPKHeaders(args, fh)

    def checkarg(arg, ent):
        if not arg:
            return False
        return '*' in arg or  ent.name in arg
    def checkname(a, b):
        if a and '*' in a: return True
        if b and '*' in b: return True
        l = 0
        if a: l += len(a)
        if b: l += len(b)
        return l > 1

    if args.verbose and not (args.cat or args.raw or args.save):
        print("   0304            need flgs  mth    stamp  --crc-- compsize fullsize nlen xlen      namofs     xofs   datofs   endofs")
        print("   0102            crea need flgs  mth    stamp  --crc-- compsize fullsize nlen xlen clen dsk0 attr osattr     datptr      namofs     xofs   cmtofs   endofs")
    for ent in scanner:
        if args.cat or args.raw or args.save:
            if args.quick and isinstance(ent, CentralDirEntry)  or \
                        not args.quick and isinstance(ent, LocalFileHeader):
                ent.loaditems(fh)
                do_cat = checkarg(args.cat, ent)
                do_raw = checkarg(args.raw, ent)
                do_save= checkarg(args.save, ent)

                do_name= checkname(args.cat, args.raw)

                if do_name:
                    print("\n===> " + ent.name + " <===\n")

                sys.stdout.flush()
                blks = zipraw(fh, ent)

                if args.password and ent.flags&1:
                    blks = zip_decrypt(blks, args.password)
                    if do_cat or do_save:
                        blks = skipbytes(blks, 12, args)

                if do_cat:
                    sys.stdout.buffer.writelines(zipcat(blks, ent))
                if do_raw:
                    sys.stdout.buffer.writelines(blks)
                if do_save:
                    savefile(args.outputdir, ent.name, zipcat(blks, ent))
        else:
            ent.loaditems(fh)
            if args.verbose or not args.quick:
                print("%08x: %s" % (ent.pkOffset, ent))
            else:
                print(ent.summary())
                if hasattr(ent, "comment") and ent.comment and not args.dumpraw:
                    print(ent.comment)
            if args.dumpraw and hasattr(ent, "extraLength") and ent.extraLength:
                print("%08x: XTRA: %s" % (ent.extraOffset, binascii.b2a_hex(getbytes(fh, ent.extraOffset, ent.extraLength))))
            if args.dumpraw and hasattr(ent, "comment") and ent.comment:
                print("%08x: CMT: %s" % (ent.commentOffset, binascii.b2a_hex(getbytes(fh, ent.commentOffset, ent.commentLength))))
            if args.dumpraw and isinstance(ent, LocalFileHeader):
                blks = zipraw(fh, ent)
                if args.password and ent.flags&1:
                    blks = zip_decrypt(blks, args.password)

                blockdump(ent.dataOffset, blks)


def DirEnumerator(args, path):
    """
    Enumerate all files / links in a directory,
    optionally recursing into subdirectories,
    or ignoring links.
    """
    for d in os.scandir(path):
        try:
            if d.name == '.' or d.name == '..':
                pass
            elif d.is_symlink() and args.skiplinks:
                pass
            elif d.is_file():
                yield d.path
            elif d.is_dir() and args.recurse:
                for f in DirEnumerator(args, d.path):
                    yield f
        except Exception as e:
            print("EXCEPTION %s accessing %s/%s" % (e, path, d.name))


def EnumeratePaths(args, paths):
    """
    Enumerate all urls, paths, files from the commandline
    optionally recursing into subdirectories.
    """
    for fn in paths:
        try:
            # 3 - for ftp://, 4 for http://, 5 for https://
            if fn.find("://") in (3,4,5):
                yield fn
            if os.path.islink(fn) and args.skiplinks:
                pass
            elif os.path.isdir(fn) and args.recurse:
                for f in DirEnumerator(args, fn):
                    yield f
            elif os.path.isfile(fn):
                yield fn
        except Exception as e:
            print("EXCEPTION %s accessing %s" % (e, fn))


def main():
    import argparse
    parser = argparse.ArgumentParser(description='zipdump - scan file contents for PKZIP data',
                                     epilog='zipdump can quickly scan a zip from an URL without downloading the complete archive')
    parser.add_argument('--verbose', '-v', action='count')
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--cat', '-c', nargs='*', type=str, help='decompress file(s) to stdout')
    parser.add_argument('--raw', '-p', nargs='*', type=str, help='print raw compressed file(s) data to stdout')
    parser.add_argument('--save', '-s', nargs='*', type=str, help='extract file(s) to the output directory')
    parser.add_argument('--outputdir', '-d', type=str, help='the output directory, default = curdir', default='.')
    parser.add_argument('--quick', '-q', action='store_true', help='Quick dir scan. This is quick with URLs as well.')
    parser.add_argument('--recurse', '-r', action='store_true', help='recurse into directories')
    parser.add_argument('--skiplinks', '-L', action='store_true', help='skip symbolic links')
    parser.add_argument('--offset', '-o', type=int, help='start processing at offset')
    parser.add_argument('--length', '-l', type=int, help='max length of data to process')
    parser.add_argument('--chunksize', type=int, default=1024*1024)
    parser.add_argument('--dumpraw', action='store_true', help='hexdump raw compressed data')

    parser.add_argument('--password', type=str, help="Password for pkzip decryption")
    parser.add_argument('--hexpassword', type=str, help="hexadecimal password for pkzip decryption")
    parser.add_argument('--keys', type=str, help="internal key representation for pkzip decryption")

    parser.add_argument('FILES', type=str, nargs='*', help='Files or URLs')
    args = parser.parse_args()

    use_raw = args.cat or args.raw or args.save

    if args.hexpassword:
        args.password = binascii.a2b_hex(args.hexpassword)
    elif args.keys:
        args.password = list(int(_, 0) for _ in args.keys.split(","))
    elif args.password:
        args.password = args.password.encode('utf-8')

    if args.FILES:
        for fn in EnumeratePaths(args, args.FILES):

            if len(args.FILES)>1 and not args.quiet:
                print("\n==> " + fn + " <==\n")
            try:
                if fn.find("://") in (3,4,5):
                    # when argument looks like a url, use urlstream to open
                    import urlstream
                    with urlstream.open(fn) as fh:
                        processfile(args, fh)
                else:
                    with open(fn, "rb") as fh:
                        processfile(args, fh)
            except Exception as e:
                print("ERROR: %s" % e)
                raise
    else:
        processfile(args, sys.stdin.buffer)

if __name__ == '__main__':
    main()

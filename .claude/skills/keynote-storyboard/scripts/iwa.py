import sys, re, struct, os

def snappy_decompress(data):
    # raw snappy block decompress
    pos = 0
    # read varint uncompressed length
    result_len = 0; shift = 0
    while True:
        b = data[pos]; pos += 1
        result_len |= (b & 0x7f) << shift
        if not (b & 0x80): break
        shift += 7
    out = bytearray()
    n = len(data)
    while pos < n:
        tag = data[pos]; pos += 1
        t = tag & 3
        if t == 0:
            l = tag >> 2
            if l < 60:
                l += 1
            else:
                nb = l - 59
                l = int.from_bytes(data[pos:pos+nb], 'little') + 1
                pos += nb
            out += data[pos:pos+l]; pos += l
        elif t == 1:
            l = ((tag >> 2) & 7) + 4
            off = ((tag >> 5) << 8) | data[pos]; pos += 1
            for _ in range(l): out.append(out[-off])
        elif t == 2:
            l = (tag >> 2) + 1
            off = int.from_bytes(data[pos:pos+2], 'little'); pos += 2
            for _ in range(l): out.append(out[-off])
        else:
            l = (tag >> 2) + 1
            off = int.from_bytes(data[pos:pos+4], 'little'); pos += 4
            for _ in range(l): out.append(out[-off])
    return bytes(out)

def iwa_decompress(path):
    data = open(path,'rb').read()
    pos = 0; out = b''
    while pos < len(data):
        typ = data[pos]; ln = int.from_bytes(data[pos+1:pos+4],'little'); pos += 4
        chunk = data[pos:pos+ln]; pos += ln
        out += snappy_decompress(chunk)
    return out

if __name__ == '__main__':
    for p in sys.argv[1:]:
        raw = iwa_decompress(p)
        outp = p + '.bin'
        open(outp,'wb').write(raw)
        print(p, len(raw))

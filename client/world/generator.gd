extends RefCounted
## Bit-for-bit mirror of server/world/generator.py. int64 overflow is intentional.
const SEED := 20261115
const CHUNK := 12
const M1 := -4658895280553007687
const M2 := -7723592293110705685
const RIVER := 0x7269766572

static func _ushr(value: int, shift: int) -> int:
    return (value >> shift) & ((1 << (64 - shift)) - 1)

static func mix64(value: int) -> int:
    value = (value ^ _ushr(value, 30)) * M1
    value = (value ^ _ushr(value, 27)) * M2
    return value ^ _ushr(value, 31)

static func noise(seed: int, x: int, y: int) -> int:
    return mix64(seed ^ mix64(x) ^ (mix64(y) << 1))

static func urem(value: int, divisor: int) -> int:
    var rem := value % divisor
    if value < 0:
        rem = (rem + ((9223372036854775807 % divisor) * 2 + 2) % divisor + divisor) % divisor
    return rem

static func floor_div(a: int, b: int) -> int:
    assert(b > 0)
    var q := a / b
    if a < 0 and a % b != 0:
        q -= 1
    return q

static func terrain(seed: int, x: int, y: int) -> String:
    var y0 := floor_div(y, 24)
    var offset := y - y0 * 24
    var start := urem(noise(seed ^ RIVER, 0, y0), 81) - 40
    var finish := urem(noise(seed ^ RIVER, 0, y0 + 1), 81) - 40
    var river := floor_div(start * (24 - offset) + finish * offset, 24)
    if absi(x - river) <= 2:
        return "water"
    return "tree" if urem(noise(seed, x, y), 13) == 0 else "ground"

static func radius_at_level(base: int, level: int) -> int:
    assert(base > 0 and level >= 1 and level <= 6)
    var radius := base
    for i in range(level - 1):
        radius = floor_div(radius * 125 + 99, 100)
    return radius

static func zone(x: int, y: int, cx: int, cy: int, base: int, level: int) -> String:
    var dx := x - cx
    var dy := y - cy
    var distance := maxi(absi(dx), absi(dy))
    if distance > radius_at_level(base, level):
        return "free"
    if distance <= maxi(1, floor_div(base, 5)):
        return "center"
    for ring in range(1, level + 1):
        var outer := radius_at_level(base, ring)
        if distance <= outer:
            if dx > 0 and absi(dy) * 2 <= dx and distance * 4 >= outer * 3:
                return "industrial"
            return "residential"
    return "free"

static func _decimal_add(a: String, b: String) -> String:
    var i := a.length() - 1
    var j := b.length() - 1
    var carry := 0
    var result := ""
    while i >= 0 or j >= 0 or carry > 0:
        var n := carry
        if i >= 0:
            n += a.substr(i, 1).to_int()
            i -= 1
        if j >= 0:
            n += b.substr(j, 1).to_int()
            j -= 1
        result = str(n % 10) + result
        carry = n / 10
    return result

static func _decimal_mul(a: String, m: int) -> String:
    var carry := 0
    var result := ""
    for i in range(a.length() - 1, -1, -1):
        var n := a.substr(i, 1).to_int() * m + carry
        result = str(n % 10) + result
        carry = n / 10
    while carry > 0:
        result = str(carry % 10) + result
        carry = carry / 10
    return result

static func unsigned_decimal(value: int) -> String:
    if value >= 0:
        return str(value)
    var hi := (value >> 32) & 0xffffffff
    var lo := value & 0xffffffff
    return _decimal_add(_decimal_mul(str(hi), 4294967296), str(lo))

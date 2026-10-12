"""Mask secrets and identity numbers in text before it leaves for the warehouse.

Every ingest job runs each record through mask_record() before it goes to
Kafka, so a card number, private key or password that someone typed into a
chat, a note or a scanned document never reaches ClickHouse, its backups or
an agent that reads them. What is masked is replaced in place - enough of
the value is kept to recognise it (a card's last four digits, a key's first
seven and last four characters), never enough to use it - and the record's
envelope says what was found: `sensitive`, `sensitive_kinds`, and
`sensitive_fingerprints`, a keyed hash per value so the same secret can be
found again across sources without anyone being able to recover it from the
hash. Pod logs get the same treatment in Alloy (clusters/lab/logging/), with
the patterns that need no checksum. pipelines/sensitive.md lists every kind.

Each detector is a pattern plus, where one exists, the checksum the real
thing carries - Luhn for cards, mod 97 for IBANs and Serbian accounts, the
JMBG check digit - so an order number or a timestamp is not mistaken for a
card. Phone numbers, e-mail addresses and usernames are left alone on
purpose: they are how people are told apart.

This file is imported by the ingest jobs and is not one itself, which is why
it never mentions the scheduler by name: the scheduler parses only files
that do.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
from pathlib import Path

KEY_ENV = "SENSITIVE_FINGERPRINT_KEY"
STAR = "*"


# --- Masking helpers ---------------------------------------------------------

def _keep_ends(value: str, head: int = 7, tail: int = 4) -> str:
    """First `head` and last `tail` characters, stars between - for keys."""
    if len(value) <= head + tail + 3:
        return value[:2] + STAR * max(len(value) - 2, 3)
    return value[:head] + STAR * 4 + value[-tail:]


def _keep_last(digits: str, tail: int = 4, group: int = 4) -> str:
    """Only the last digits, in groups: '**** **** **** 4242'."""
    masked = STAR * (len(digits) - tail) + digits[-tail:]
    groups = []
    while masked:
        groups.insert(0, masked[-group:])
        masked = masked[:-group]
    return " ".join(groups)


def _all(value: str) -> str:
    return STAR * max(len(value), 4)


# --- Checksums ---------------------------------------------------------------

def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# Issuer prefixes and lengths of the cards that exist, so that a number that
# merely passes Luhn (one in ten random ones does) is not taken for a card.
_CARD_RANGES = [
    (("4",), (13, 16, 19)),                                   # Visa
    (tuple(str(p) for p in range(51, 56)), (16,)),            # Mastercard
    (tuple(str(p) for p in range(2221, 2721)), (16,)),        # Mastercard 2-series
    (("34", "37"), (15,)),                                    # Amex
    (("6011", "65") + tuple(str(p) for p in range(644, 650)), (16, 17, 18, 19)),  # Discover
    (("62",), (16, 17, 18, 19)),                              # UnionPay
    (tuple(str(p) for p in range(3528, 3590)), (16, 17, 18, 19)),  # JCB
    (("2200", "2201", "2202", "2203", "2204"), (16, 17, 18, 19)),  # Mir
    (("9891",), (16,)),                                       # DinaCard (Serbia)
    (("50",) + tuple(str(p) for p in range(56, 70)), tuple(range(12, 20))),  # Maestro
]


def _is_card(digits: str) -> bool:
    if len(set(digits)) == 1 or not _luhn(digits):
        return False
    return any(digits.startswith(p) and len(digits) in lengths
               for prefixes, lengths in _CARD_RANGES for p in prefixes)


def _iban_ok(iban: str) -> bool:
    s = iban[4:] + iban[:4]
    n = "".join(str(int(c, 36)) for c in s)
    return int(n) % 97 == 1


def _rs_account_ok(bank: str, number: str, control: str) -> bool:
    """Serbian domestic account: 3-digit bank, 13-digit number, 2 check digits."""
    body = bank + number.zfill(13)
    return 98 - (int(body) * 100) % 97 == int(control)


def _jmbg_ok(d: str) -> bool:
    day, month = int(d[0:2]), int(d[2:4])
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return False
    a = [int(c) for c in d]
    s = 7 * (a[0] + a[6]) + 6 * (a[1] + a[7]) + 5 * (a[2] + a[8]) \
        + 4 * (a[3] + a[9]) + 3 * (a[4] + a[10]) + 2 * (a[5] + a[11])
    k = 11 - s % 11
    if k > 9:
        k = 0
    return k == a[12]


def _cpr_date_ok(d: str) -> bool:
    return 1 <= int(d[0:2]) <= 31 and 1 <= int(d[2:4]) <= 12


def _entropy(s: str) -> float:
    counts = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


_BIP39 = frozenset(
    (Path(__file__).with_name("bip39_english.txt")).read_text().split()
)


# --- Detectors -----------------------------------------------------------------
#
# Each one: a kind, a compiled pattern, and a function from the match to its
# replacement, or None when the match turns out not to be the thing (a
# checksum fails). The secret part a fingerprint is taken of is the group
# named `s`, or the whole match.

_KW_SEP = r"\s*(?:[:=]|is|-|—)\s*"
_CODE_SEP = r"\s*(?:[:=]|is|-|—)?\s*"


def _sub_group(m: re.Match, name: str, masked: str) -> str:
    start, end = m.span(name)
    whole_start = m.start()
    text = m.group(0)
    return text[:start - whole_start] + masked + text[end - whole_start:]


def _card(m):
    """The longest run of the matched digit groups that is a real card - the
    pattern is greedy, so `4242 4242 4242 4242 12/27` arrives with the
    expiry's 12 attached."""
    raw = m.group("s")
    parts = re.split(r"([ -])", raw)
    for end in range(len(parts), 0, -1):
        head = "".join(parts[:end])
        if head and head[-1] in " -":
            continue
        digits = re.sub(r"[ -]", "", head)
        if 12 <= len(digits) <= 19 and _is_card(digits):
            return _sub_group(m, "s", _keep_last(digits) + raw[len(head):])
    return None


def _key(m):
    return _sub_group(m, "s", _keep_ends(m.group("s")))


def _hide(m):
    return _sub_group(m, "s", _all(m.group("s")))


def _pem(m):
    return f"-----BEGIN {m.group('label')}----- [masked] -----END {m.group('label')}-----"


def _generic(m):
    v = m.group("s")
    if len(v) < 16 or _entropy(v) < 3.5 or not re.search(r"\d", v) or not re.search(r"[A-Za-z]", v):
        return None
    return _sub_group(m, "s", _keep_ends(v))


def _iban(m):
    raw = m.group("s")
    compact = raw.replace(" ", "").upper()
    if not 15 <= len(compact) <= 34 or not _iban_ok(compact):
        return None
    return _sub_group(m, "s", compact[:2] + STAR * (len(compact) - 6) + compact[-4:])


def _rs_account(m):
    if not _rs_account_ok(m.group("bank"), m.group("num"), m.group("ctl")):
        return None
    full = m.group("s")
    return _sub_group(m, "s", STAR * (len(full) - 4) + full[-4:])


def _jmbg(m):
    if not _jmbg_ok(m.group("s")):
        return None
    return _sub_group(m, "s", STAR * 13)


def _cpr(m):
    if not _cpr_date_ok(m.group("s")):
        return None
    return _sub_group(m, "s", "******-****")


def _seed(m):
    words = re.findall(r"[a-z]+", m.group(0).lower())
    if len(words) not in (12, 15, 18, 21, 24) or not all(w in _BIP39 for w in words):
        return None
    return "[seed phrase masked]"


def _blob(m):
    v = m.group("s")
    # A long word made only of letters is not a payload; a payload mixes
    # cases and digits.
    if not (re.search(r"\d", v) and re.search(r"[a-z]", v) and re.search(r"[A-Z]", v)) \
            and not re.fullmatch(r"(?i)(?:[0-9a-f]{2})+", v):
        return None
    size = len(v) * 3 // 4 if not re.fullmatch(r"(?i)(?:[0-9a-f]{2})+", v) else len(v) // 2
    kind = "hex" if re.fullmatch(r"(?i)(?:[0-9a-f]{2})+", v) else "base64"
    shown = f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"
    return _sub_group(m, "s", f"[{kind} blob, {shown}, masked]")


# Instructions to an AI model, in the household's languages, and the markers
# chat models use for roles - text a person writing to a person has no
# reason to contain.
_INJECTION = re.compile(
    r"(?i)"
    r"\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+|any\s+|the\s+|your\s+|every\s+)*"
    r"(?:previous|prior|above|earlier|preceding|existing|system|original)\s+"
    r"(?:instructions?|prompts?|rules|directions|messages|guidelines|context)\b"
    r"|\b(?:new|updated|real|actual)\s+(?:system\s+)?instructions?\s*:"
    r"|\byou\s+are\s+now\s+(?:a|an|in|the|my|no\s+longer)\b"
    r"|\b(?:reveal|print|show|repeat|output)\s+(?:your|the)\s+(?:system\s+)?(?:prompt|instructions)\b"
    r"|\bsystem\s+prompt\b|\bdeveloper\s+mode\b|\bjailbreak\b"
    r"|\bdo\s+not\s+(?:tell|inform|alert|mention\s+this\s+to)\s+the\s+user\b"
    r"|\b(?:игнорируй|игнорируйте|проигнорируй|забудь|забудьте)\s+(?:все\s+)?(?:предыдущие|прошлые|прежние|старые|системные)?\s*(?:инструкции|указания|правила|промпты?)\b"
    r"|\bновые\s+инструкции\s*:|\bты\s+теперь\b"
    r"|\b(?:ignoriši|ignorisi|ignorišite|zaboravi|zaboravite)\s+(?:sve\s+)?(?:prethodne|prethodna|ranije|stare)?\s*(?:instrukcije|uputstva|naredbe|pravila)\b"
    r"|\b(?:игнориши|игноришите|заборави|заборавите)\s+(?:све\s+)?(?:претходне|претходна|раније|старе)?\s*(?:инструкције|упутства|наредбе|правила)\b"
    r"|\bалдыңғы\s+нұсқауларды\s+(?:елеме|елемеңіз|ұмыт|ұмытыңыз)\b"
    r"|\bignorer\s+(?:alle\s+)?(?:tidligere|forrige)\s+(?:instruktioner|instrukser|regler)\b"
    r"|<\|(?:im_start|im_end|system|endoftext)\|>|\[/?INST\]|<</?SYS>>|</?system>"
)


_PASSWORD_WORDS = (
    r"password|passwd|passphrase|pwd|пароль|лозинка|lozinka|šifra|sifra|шифра"
    r"|құпия\s+сөз|құпиясөз|parol|adgangskode"
)
_SECRET_WORDS = (
    r"api[_ -]?key|apikey|api[_ -]?token|access[_ -]?key|access[_ -]?token|auth[_ -]?token"
    r"|client[_ -]?secret|secret[_ -]?key|secret|token|bearer|private[_ -]?key"
    r"|ключ|кључ|ključ|kljuc|токен"
)
_CODE_WORDS = (
    r"login code|verification code|confirmation code|security code|one[- ]time code|otp|pin"
    r"|код подтверждения|код для входа|код|kod za prijavu|verifikacioni kod|kod|kode|код потврде"
)
_PASSPORT_WORDS = r"passport|pasoš|pasos|пасош|паспорт|pas\.?\s*nr|pas\s*br"


DETECTORS = [
    # Group A - recognised by their exact shape, no false alarms to speak of.
    ("private_key", re.compile(
        r"-----BEGIN (?P<label>(?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?)-----(?P<s>.*?)-----END (?P=label)-----",
        re.S), _pem),
    ("private_key", re.compile(r"(?P<s>PuTTY-User-Key-File-\d+: .*?Private-MAC: \S+)", re.S),
     lambda m: "[PuTTY private key masked]"),
    ("age_key", re.compile(r"(?P<s>AGE-SECRET-KEY-1[0-9A-Z]{58})"), _key),
    ("github_token", re.compile(r"(?P<s>\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{60,255}))"), _key),
    ("gitlab_token", re.compile(r"(?P<s>\bglpat-[A-Za-z0-9_-]{20,})"), _key),
    ("aws_access_key", re.compile(r"(?P<s>\b(?:AKIA|ASIA)[0-9A-Z]{16})\b"), _key),
    ("aws_secret_key", re.compile(r"(?i)aws_?secret_?(?:access_?)?key[\"']?\s*[:=]\s*[\"']?(?P<s>[A-Za-z0-9/+=]{40})"), _key),
    ("google_api_key", re.compile(r"(?P<s>\bAIza[0-9A-Za-z_-]{35})"), _key),
    ("google_oauth", re.compile(r"(?P<s>\b(?:1//0[0-9A-Za-z_-]{40,}|GOCSPX-[A-Za-z0-9_-]{28}|ya29\.[0-9A-Za-z_-]{30,}))"), _key),
    ("slack_token", re.compile(r"(?P<s>\bxox[abposr]-[A-Za-z0-9-]{10,})"), _key),
    ("slack_webhook", re.compile(r"(?P<s>https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,})"), _key),
    ("stripe_key", re.compile(r"(?P<s>\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{20,})"), _key),
    ("anthropic_key", re.compile(r"(?P<s>\bsk-ant-[A-Za-z0-9_-]{20,})"), _key),
    ("openai_key", re.compile(r"(?P<s>\bsk-(?!ant-)(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,})"), _key),
    ("npm_token", re.compile(r"(?P<s>\bnpm_[A-Za-z0-9]{36})"), _key),
    ("pypi_token", re.compile(r"(?P<s>\bpypi-[A-Za-z0-9_-]{50,})"), _key),
    ("sendgrid_key", re.compile(r"(?P<s>\bSG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43})"), _key),
    ("huggingface_token", re.compile(r"(?P<s>\bhf_[A-Za-z0-9]{34,})"), _key),
    ("digitalocean_token", re.compile(r"(?P<s>\bdop_v1_[a-f0-9]{64})"), _key),
    ("tailscale_key", re.compile(r"(?P<s>\btskey-[a-z]+-[A-Za-z0-9-]{20,})"), _key),
    ("telegram_bot_token", re.compile(r"(?P<s>\b\d{8,10}:AA[A-Za-z0-9_-]{33})\b"), _key),
    ("jwt", re.compile(r"(?P<s>\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"), _key),
    ("bearer_token", re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+(?P<s>[A-Za-z0-9._~+/=-]{16,})"), _key),
    ("url_password", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:(?P<s>[^\s@/]{1,})@"), _hide),
    ("card", re.compile(r"(?<![\d+])(?P<s>\d(?:[ -]?\d){11,18})(?!\d)"), _card),
    ("card_security_code", re.compile(r"(?i)\b(?:cvv2?|cvc2?|cvn|cid)\b\s*[:=]?\s*(?P<s>\d{3,4})\b"), _hide),
    ("card_expiry", re.compile(
        r"(?i)\b(?:exp(?:iry|ires|\.)?|valid\s+thru|valid\s+through|срок\s+действия|važi\s+do|важи\s+до)\s*[:.]?\s*(?P<s>(?:0[1-9]|1[0-2])\s*/\s*(?:\d{2}|\d{4}))\b"),
     _hide),
    # Group B - recognised by the words around them, in the household's
    # languages: English, Russian, Serbian in both scripts, Kazakh, Danish.
    ("password", re.compile(rf"(?i)\b(?:{_PASSWORD_WORDS})\b{_KW_SEP}(?P<s>\S{{4,}})"), _hide),
    ("secret", re.compile(rf"(?i)\b(?:{_SECRET_WORDS})\b{_KW_SEP}[\"']?(?P<s>[A-Za-z0-9_\-+/=.]{{16,}})"), _generic),
    ("one_time_code", re.compile(rf"(?i)\b(?:{_CODE_WORDS})\b{_CODE_SEP}(?P<s>\d{{4,8}})\b"), _hide),
    ("one_time_code", re.compile(r"(?i)\b(?P<s>\d{4,8})\s+(?:is your|je vaš|ваш)\b"), _hide),
    ("seed_phrase", re.compile(r"(?i)\b(?:(?:\d{1,2}[.)]\s*)?[a-z]{3,8}[\s,]+){11,23}(?:\d{1,2}[.)]\s*)?[a-z]{3,8}\b"), _seed),
    # Group C - bank accounts and identity numbers, each with its checksum.
    ("iban", re.compile(r"\b(?P<s>[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30})\b"), _iban),
    ("bank_account", re.compile(r"\b(?P<s>(?P<bank>\d{3})-(?P<num>\d{1,13})-(?P<ctl>\d{2}))\b"), _rs_account),
    ("national_id", re.compile(r"(?<![\d+])(?P<s>\d{13})(?!\d)"), _jmbg),
    ("national_id", re.compile(r"(?i)(?:\bcpr(?:-?nr\.?|-?nummer)?\s*[:.]?\s*)?(?<!\d)(?P<s>\d{6}-\d{4})(?!\d)"), _cpr),
    ("passport", re.compile(rf"(?i)\b(?:{_PASSPORT_WORDS})\b(?:\s*(?:no\.?|nr\.?|number|номер|broj|br\.?))?\s*[:#]?\s*(?P<s>[A-Z0-9]{{6,9}})\b"), _hide),
    # Group D - text aimed at whoever reads it next, not at a person:
    # encoded payloads and instructions to an AI model. The first is replaced
    # by a note of what was there; the second by a marker saying something
    # was removed. Neither is a defence against someone determined - a
    # rephrased instruction passes - but it stops the copy-pasted ones and
    # flags the record, so whatever reads it knows to distrust it.
    ("encoded_blob", re.compile(r"(?i)data:[a-z0-9.+/-]+;base64,(?P<s>[A-Za-z0-9+/=]{40,})"), _blob),
    ("encoded_blob", re.compile(r"(?is)(?P<s><script\b.*?</script\s*>)"), lambda m: "[script removed]"),
    ("encoded_blob", re.compile(r"(?i)(?P<s>javascript:[^\s\"'<>]{4,})"), lambda m: "[javascript link removed]"),
    ("encoded_blob", re.compile(r"(?i)-e(?:nc(?:odedcommand)?)?\s+(?P<s>[A-Za-z0-9+/=]{40,})"), _blob),
    ("encoded_blob", re.compile(r"(?<![A-Za-z0-9+/=_-])(?P<s>[A-Za-z0-9+/]{120,}={0,2})(?![A-Za-z0-9+/=_-])"), _blob),
    ("encoded_blob", re.compile(r"(?<![A-Za-z0-9_-])(?P<s>[A-Za-z0-9_-]{160,})(?![A-Za-z0-9_-])"), _blob),
    ("encoded_blob", re.compile(r"(?i)(?<![0-9a-f])(?P<s>(?:[0-9a-f]{2}){64,})(?![0-9a-f])"), _blob),
    ("prompt_injection", _INJECTION, lambda m: "[instruction to an AI removed]"),
]


def _fingerprint_key() -> bytes | None:
    key = os.environ.get(KEY_ENV)
    return key.encode() if key else None


def fingerprint(kind: str, value: str, key: bytes) -> str:
    """A keyed hash: the same secret gives the same 16 hex characters
    everywhere this key is used, and nobody without the key can test a guess
    against it - which matters for a four-digit PIN."""
    return hmac.new(key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:16]


# Characters that are not shown but that a language model reads: the Unicode
# tag block (ASCII smuggled invisibly), zero-width spaces and joiners other
# than the emoji one, and the direction overrides that make text display
# differently from what it says. Removed first, so a phrase split by them
# cannot slip past the detectors below. U+200D, the zero-width joiner, stays:
# family and flag emoji are built with it.
_INVISIBLE = re.compile(
    "[\U000E0000-\U000E007F\u200B\u200C\u2060-\u2064\u202A-\u202E\u2066-\u2069\u180E\u00AD]"
    "|(?<=.)\uFEFF"
)


def _strip_invisible(text: str, found: list[tuple[str, str]]) -> str:
    hidden = _INVISIBLE.findall(text)
    if not hidden:
        return text
    # The smuggled tag characters spell ASCII; keep what they said as the
    # "secret", so the fingerprint can find the same payload elsewhere.
    smuggled = "".join(chr(ord(c) - 0xE0000) for c in hidden if 0xE0020 <= ord(c) <= 0xE007E)
    found.append(("invisible_text", smuggled or "".join(hidden)))
    return _INVISIBLE.sub("", text)


def mask_text(text: str, found: list[tuple[str, str]]) -> str:
    """Every detector over one string, in order; appends (kind, secret)."""
    text = _strip_invisible(text, found)
    for kind, pattern, replace in DETECTORS:
        if kind == "card" and not re.search(r"\d{4}", text):
            continue

        def sub(m, kind=kind, replace=replace):
            out = replace(m)
            if out is None:
                return m.group(0)
            secret = m.group("s") if "s" in m.re.groupindex else m.group(0)
            found.append((kind, secret))
            return out

        text = pattern.sub(sub, text)
    return text


def mask_record(record, key: bytes | None = None):
    """Masks every string in a record, however deep; returns
    (masked record, flags) where flags is the three envelope fields."""
    if key is None:
        key = _fingerprint_key()
    found: list[tuple[str, str]] = []

    def walk(v):
        if isinstance(v, str):
            return mask_text(v, found) if len(v) >= 4 else v
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [walk(x) for x in v]
        return v

    masked = walk(record)
    kinds = sorted({k for k, _ in found})
    prints = sorted({fingerprint(k, s, key) for k, s in found}) if key else []
    return masked, {
        "sensitive": bool(found),
        "sensitive_kinds": kinds,
        "sensitive_fingerprints": prints,
    }

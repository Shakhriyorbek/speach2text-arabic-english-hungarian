"""
Proper names, substituted BEFORE translation.

Why this exists
---------------
NLLB translates the literal meaning of Arabic names instead of carrying them
across. Measured on real khutbah audio:

    أبو لؤلؤة المجوسي  ->  "the father of the magical pearl"  / "a pearl-eyed
                           wizard" / "the magicians' pearl's papa"
    عمر بن الخطاب      ->  "a beszédben"  ("in the speech") — the second Caliph
                           erased from a sentence about his own assassination
    وعلى آله           ->  "the MACHINES of good people"  (آله read as آلة)

This is not a model-size problem: 600M, 1.3B and 3.3B all failed, and 3.3B was
the worst of them. It is a vocabulary problem, and a khutbah's names are a
closed set known in advance — so we simply do not let the model see them.

How it works
------------
Measured which placeholder survives NLLB intact (see the note below): a plain
Latin-script name passes through unchanged, in the right position, and Hungarian
case endings attach to it correctly. So there is no mask/unmask round trip —
we substitute the finished Hungarian form directly and let NLLB copy it.

    "أبو لؤلؤة المجوسي يصنع الرحى"
      -> "Abu Lulua, a zoroasztriánus يصنع الرحى"
      -> "Abu Lulua, a zoroasztriánus malmot készít"

Bracketed or punctuated placeholders ("[[1]]", "#1#") were also tried and are
mangled by the tokenizer, so do not switch to those without re-measuring.

Maintaining this list
---------------------
Entries are matched longest-first, so "عمر بن الخطاب" wins over "عمر". Add the
spellings your khatib actually uses, including ابن/بن variants.

NOTE ON THE HUNGARIAN: these transliterations follow common Hungarian usage as
best I can judge, but I am not the right authority on Hungarian orthography for
Arabic names. A Hungarian speaker should review them — they go on the screen
verbatim, so an awkward spelling here is an awkward spelling in front of the
congregation.
"""

import re
import time

# Arabic surface form -> Hungarian rendering.
NAME_MAP = {
    # --- the Rashidun caliphs ---
    "أبو بكر الصديق": "Abu Bakr asz-Sziddík",
    "أبي بكر الصديق": "Abu Bakr asz-Sziddík",
    "أبو بكر": "Abu Bakr",
    "أبي بكر": "Abu Bakr",
    "عمر بن الخطاب": "Omar ibn al-Hattáb",
    "عمر ابن الخطاب": "Omar ibn al-Hattáb",
    "عثمان بن عفان": "Oszmán ibn Affán",
    "علي بن أبي طالب": "Ali ibn Abi Tálib",

    # --- companions who come up often ---
    "عبد الرحمن بن عوف": "Abdurrahmán ibn Auf",
    "أبو عبيدة بن الجراح": "Abu Ubajda ibn al-Dzsarráh",
    "سعد بن أبي وقاص": "Szaad ibn Abi Vakkász",
    "طلحة بن عبيد الله": "Talha ibn Ubajdulláh",
    "الزبير بن العوام": "Az-Zubajr ibn al-Avvám",
    "عبد الله بن مسعود": "Abdulláh ibn Maszúd",
    "عبد الله بن عباس": "Abdulláh ibn Abbász",
    "عبد الله بن عمر": "Abdulláh ibn Omar",
    "خالد بن الوليد": "Hálid ibn al-Valíd",
    "بلال بن رباح": "Bilál ibn Rabáh",
    "معاذ بن جبل": "Muádz ibn Dzsabal",
    "أنس بن مالك": "Anasz ibn Málik",
    "زيد بن ثابت": "Zajd ibn Szábit",
    "عمار بن ياسر": "Ammár ibn Jászir",
    "سلمان الفارسي": "Szalmán al-Fáriszi",
    "أبو ذر الغفاري": "Abu Dzarr al-Gifári",
    "جعفر بن أبي طالب": "Dzsafar ibn Abi Tálib",
    "أبو هريرة": "Abu Hurajra",
    # Amr, not Omar — different name, one letter apart in Arabic and easy to
    # conflate. Listed explicitly so it is never left to chance.
    "عمرو بن العاص": "Amr ibn al-Ász",
    "أبي بن كعب": "Ubajj ibn Kaab",
    "حذيفة بن اليمان": "Hudzajfa ibn al-Jamán",
    "أسامة بن زيد": "Uszáma ibn Zajd",
    "المقداد بن الأسود": "Al-Mikdád ibn al-Aszvad",
    "صهيب الرومي": "Szuhajb ar-Rúmi",
    "ابن عباس": "Ibn Abbász",
    "ابن مسعود": "Ibn Maszúd",
    "ابن عمر": "Ibn Omar",

    # --- household of the Prophet ---
    "خديجة": "Hadídzsa",
    "عائشة": "Aisa",
    "فاطمة": "Fátima",
    "حمزة": "Hamza",

    # --- prophets (Hungarian uses the biblical forms) ---
    "محمد": "Mohamed",
    "إبراهيم": "Ábrahám",
    "إسماعيل": "Izmael",
    "إسحاق": "Izsák",
    "يعقوب": "Jákob",
    "يوسف": "József",
    "موسى": "Mózes",
    "عيسى": "Jézus",
    "داوود": "Dávid",
    "داود": "Dávid",
    "سليمان": "Salamon",
    "نوح": "Noé",
    "آدم": "Ádám",

    # --- places ---
    "بيت المقدس": "Jeruzsálem",
    "المسجد الحرام": "a Szent Mecset",
    "المسجد النبوي": "a Próféta Mecsete",
    "المدينة المنورة": "Medina",
    "الكعبة": "a Kába",
    "مكة": "Mekka",

    # --- from the khutbah we tested against ---
    "أبو لؤلؤة المجوسي": "Abu Lulua, a zoroasztriánus",
    "أبو لؤلؤة": "Abu Lulua",
    "المجوسي": "a zoroasztriánus",

    # --- the prophets, by their Arabic names ---
    # NLLB renders these as ordinary Hungarian Bible names or, worse, as their
    # literal meanings. A congregation expects the Arabic forms.
    "محمد": "Mohamed",
    "إبراهيم": "Ibráhím",
    "موسى": "Múszá",
    "عيسى": "Ísza",
    "نوح": "Núh",
    "يوسف": "Júszuf",
    "يعقوب": "Jakúb",
    "إسماعيل": "Iszmáíl",
    "إسحاق": "Iszhák",
    "داوود": "Dávúd",
    "سليمان": "Szulejmán",
    "يونس": "Júnusz",
    "أيوب": "Ajjúb",
    "زكريا": "Zakarijjá",
    "يحيى": "Jahjá",
    "هارون": "Hárún",
    "لوط": "Lút",
    "آدم": "Ádám",
    "جبريل": "Dzsibríl",

    # --- the hadith collectors ---
    # These are the single most common thing a khatib names, and Whisper is
    # least sure of them: reported live as "it drops when I speak the scholars'
    # names and their books".
    "البخاري": "al-Buhári",
    "مسلم": "Muszlim",
    "الترمذي": "at-Tirmidzi",
    "أبو داود": "Abu Dávúd",
    "أبي داود": "Abu Dávúd",
    "النسائي": "an-Naszái",
    "ابن ماجه": "Ibn Mádzsa",
    "أحمد بن حنبل": "Ahmad ibn Hanbal",
    "الإمام أحمد": "Ahmad imám",
    "الدارمي": "ad-Dárimi",
    "البيهقي": "al-Bajháki",
    "الطبراني": "at-Tabaráni",
    "الحاكم": "al-Hákim",

    # --- their books ---
    "صحيح البخاري": "Szahíh al-Buhári",
    "صحيح مسلم": "Szahíh Muszlim",
    "سنن الترمذي": "Szunan at-Tirmidzi",
    "سنن أبي داود": "Szunan Abi Dávúd",
    "سنن النسائي": "Szunan an-Naszái",
    "سنن ابن ماجه": "Szunan Ibn Mádzsa",
    "مسند أحمد": "Muszand Ahmad",
    "الموطأ": "al-Muvatta",
    "رياض الصالحين": "Rijád asz-Szálihín",

    # --- the jurists and later scholars ---
    "أبو حنيفة": "Abu Hanífa",
    "الإمام الشافعي": "asz-Sáfii imám",
    "الشافعي": "asz-Sáfii",
    "الإمام مالك": "Málik imám",
    "ابن تيمية": "Ibn Tajmijja",
    "ابن القيم": "Ibn al-Kajjim",
    "ابن كثير": "Ibn Kaszír",
    "النووي": "an-Navavi",
    "الغزالي": "al-Gazáli",
    "ابن حجر": "Ibn Hadzsar",
    "الألباني": "al-Albáni",
    "ابن رجب": "Ibn Radzsab",
    "ابن الجوزي": "Ibn al-Dzsauzi",

    # --- honorifics, which are formulas rather than names ---
    # Left as recognisable Hungarian rather than transliterated Arabic: their
    # meaning is the point, and they occur several times a minute.
    "صلى الله عليه وسلم": "Allah áldja meg és adjon neki békét",
    "رضي الله عنه": "Allah legyen elégedett vele",
    "رضي الله عنها": "Allah legyen elégedett vele",
    "رضي الله عنهم": "Allah legyen elégedett velük",
    "رضي الله عنهما": "Allah legyen elégedett velük",
    "عليه السلام": "béke legyen vele",
    "عليها السلام": "béke legyen vele",
    "عليهم السلام": "béke legyen velük",
    "رحمه الله": "Allah irgalmazzon neki",
    "رحمها الله": "Allah irgalmazzon neki",

    # Whisper mishears المجوسي as these, identically, every time — three
    # occurrences in one sermon, which NLLB then rendered "the councillor",
    # "the sitting one" and "the table". Correcting the known mishearing here is
    # a workaround for an ASR bug, not a translation entry; remove it if the
    # transcription is ever fixed upstream.
    "المجلوسي": "a zoroasztriánus",
    "المجلسي": "a zoroasztriánus",
}

# Longest first, so "عمر بن الخطاب" is consumed before a bare "عمر" could match
# part of it. Ties broken alphabetically for a stable, diffable order.
_ORDERED = sorted(NAME_MAP.items(), key=lambda kv: (-len(kv[0]), kv[0]))

_ARABIC_LETTER = "ء-ي"
_DIACRITIC = "ً-ْ"

# Names carry Arabic case endings: محمد becomes محمدا in the accusative. A plain
# substring replace leaves the ا stranded ("Mohamedا"), so the pattern absorbs an
# optional trailing alif plus any diacritics. The lookahead then refuses to match
# when a real Arabic letter follows, which stops a short name from firing inside
# a longer unrelated word.
_PATTERNS = [
    (
        re.compile(
            re.escape(arabic) + f"[{_DIACRITIC}]*" + "ا?" + f"[{_DIACRITIC}]*"
            + f"(?![{_ARABIC_LETTER}])"
        ),
        hungarian,
    )
    for arabic, hungarian in _ORDERED
]


# ---------------------------------------------------------------------------
# The 99 Names of Allah (asmā' al-ḥusnā)
# ---------------------------------------------------------------------------
# These are handled DIFFERENTLY from the person names above, for two reasons.
#
# 1. They must be TRANSLATED, not transliterated. "الرحمن" carries meaning a
#    Hungarian congregation needs — "a Könyörületes", not "ar-Rahmán".
#
# 2. Most of them are also ORDINARY ARABIC WORDS, so substituting them
#    unconditionally would corrupt normal speech:
#         السلام   divine name, and the everyday greeting (السلام عليكم)
#         الجامع   divine name, and the ordinary word for MOSQUE
#         المؤمن   divine name, and "the believer" — in a khutbah, a human
#         الشهيد   divine name, and "the martyr"
#         الحق     divine name, and simply "the truth"
#    A blanket replace would turn "السلام عليكم" into "a Béke Forrása عليكم".
#
# So a name here is only substituted inside a DIVINE CONTEXT: directly after an
# anchor (الله, اللهم, سبحان, تبارك, or the vocative يا), or chained onto another
# name that already matched. That covers how they actually occur —
# "بسم الله الرحمن الرحيم", "هو الله الملك القدوس السلام المؤمن المهيمن",
# "يا رحمن يا رحيم" — while leaving a bare الجامع or السلام عليكم alone.
#
# As with the person names, a Hungarian speaker should review these renderings.
DIVINE_NAMES = {
    "الرحمن": "a Könyörületes",
    "الرحيم": "az Irgalmas",
    "الملك": "a Király",
    "القدوس": "a Szent",
    "السلام": "a Béke Forrása",
    "المؤمن": "a Biztonság Adományozója",
    "المهيمن": "az Őrző",
    "العزيز": "a Hatalmas",
    "الجبار": "a Mindenható",
    "المتكبر": "a Fenséges",
    "الخالق": "a Teremtő",
    "البارئ": "az Alkotó",
    "المصور": "a Formáló",
    "الغفار": "a Megbocsátó",
    "القهار": "a Legyőzhetetlen",
    "الوهاب": "az Adományozó",
    "الرزاق": "a Gondviselő",
    "الفتاح": "a Megnyitó",
    "العليم": "a Mindentudó",
    "القابض": "a Szűkítő",
    "الباسط": "a Bőkezűen Adó",
    "الخافض": "a Megalázó",
    "الرافع": "a Felemelő",
    "المعز": "a Megtisztelő",
    "المذل": "a Megszégyenítő",
    "السميع": "a Mindent Halló",
    "البصير": "a Mindent Látó",
    "الحكم": "a Bíró",
    "العدل": "az Igazságos",
    "اللطيف": "a Gyengéd",
    "الخبير": "a Mindenről Tudó",
    "الحليم": "a Türelmes",
    "العظيم": "a Magasztos",
    "الغفور": "a Megbocsátó",
    "الشكور": "a Hálát Elfogadó",
    "العلي": "a Magasságos",
    "الكبير": "a Nagy",
    "الحفيظ": "az Oltalmazó",
    "المقيت": "a Fenntartó",
    "الحسيب": "a Számonkérő",
    "الجليل": "a Fenséges",
    "الكريم": "a Nagylelkű",
    "الرقيب": "az Éber Őrző",
    "المجيب": "az Imameghallgató",
    "الواسع": "a Végtelen",
    "الحكيم": "a Bölcs",
    "الودود": "a Szerető",
    "المجيد": "a Dicsőséges",
    "الباعث": "a Feltámasztó",
    "الشهيد": "a Tanú",
    "الحق": "az Igazság",
    "الوكيل": "a Gondviselő",
    "القوي": "az Erős",
    "المتين": "a Rendíthetetlen",
    "الولي": "a Pártfogó",
    "الحميد": "a Dicséretre Méltó",
    "المحصي": "a Számontartó",
    "المبدئ": "a Kezdeményező",
    "المعيد": "az Újrateremtő",
    "المحيي": "az Életet Adó",
    "المميت": "a Halált Adó",
    "الحي": "az Élő",
    "القيوم": "az Önmagában Létező",
    "الواجد": "a Megtaláló",
    "الماجد": "a Nemes",
    "الواحد": "az Egyetlen",
    "الأحد": "az Egy",
    "الصمد": "az Örökkévaló Menedék",
    "القادر": "a Mindenre Képes",
    "المقتدر": "a Korlátlan Hatalmú",
    "المقدم": "az Előrehozó",
    "المؤخر": "a Késleltető",
    "الأول": "az Első",
    "الآخر": "az Utolsó",
    "الظاهر": "a Nyilvánvaló",
    "الباطن": "a Rejtett",
    "الوالي": "a Kormányzó",
    "المتعالي": "a Magasztos",
    "البر": "a Jóságos",
    "التواب": "a Megbocsátást Elfogadó",
    "المنتقم": "a Megtorló",
    "العفو": "az Elnéző",
    "الرؤوف": "a Kegyes",
    "مالك الملك": "a Királyság Ura",
    "ذو الجلال والإكرام": "a Fenség és Nagylelkűség Ura",
    "المقسط": "a Méltányos",
    "الجامع": "az Összegyűjtő",
    "الغني": "az Önellátó",
    "المغني": "a Gazdagító",
    "المانع": "a Visszatartó",
    "الضار": "a Kárt Okozó",
    "النافع": "a Hasznot Adó",
    "النور": "a Fény",
    "الهادي": "az Útmutató",
    "البديع": "a Páratlan Teremtő",
    "الباقي": "az Örökkévaló",
    "الوارث": "az Örökös",
    "الرشيد": "a Helyes Útra Vezető",
    "الصبور": "a Végtelenül Türelmes",
}

# Words that open a divine context. After one of these, a run of divine names is
# substituted. "يا" is the vocative, which drops the article: يا رحمن, not
# يا الرحمن — so bare forms are registered too.
_ANCHORS = {
    "الله", "اللهم", "لله", "بالله", "والله", "تالله", "فالله",
    "سبحان", "سبحانه", "تبارك", "يا",
}

# Joiners that continue a chain without being names themselves.
_CHAIN_GLUE = {"و", "الـ"}

# Names that are ALSO common everyday words. These are substituted only when an
# anchor appears in the SAME utterance — never on a chain carried in from the
# previous one. Carrying is a guess about speech we can no longer see, and
# guessing wrong here rewrites the most common phrase in the mosque: without
# this, an utterance ending mid-formula would turn a following "السلام عليكم"
# into "a Béke Forrása عليكم". The unambiguous names (الرحمن, الصمد, القهار …)
# carry freely, which is what the basmala case actually needs.
_CARRY_UNSAFE = {
    "السلام", "سلام",
    "المؤمن", "مؤمن",
    "الجامع", "جامع",
    "الحق", "حق",
    "النور", "نور",
    "الشهيد", "شهيد",
    "الملك", "ملك",
    "الكريم", "كريم",
    "العظيم", "عظيم",
    "الكبير", "كبير",
    "الواحد", "واحد",
    "الأول", "أول",
    "الآخر", "آخر",
    "العدل", "عدل",
    "الحي", "حي",
    "الغني", "غني",
    "البر", "بر",
    "الوكيل", "وكيل",
    "الولي", "ولي",
    "الهادي", "هادي",
    "الوارث", "وارث",
    "الباقي", "باقي",
}

_DIVINE_LOOKUP = {}
for _ar, _hu in DIVINE_NAMES.items():
    _DIVINE_LOOKUP[_ar] = _hu
    if _ar.startswith("ال") and len(_ar) > 3:
        _DIVINE_LOOKUP[_ar[2:]] = _hu          # vocative / anarthrous form

_STRIP = "،.:؛!؟" + "".join(chr(c) for c in range(0x064B, 0x0653))


def _bare(token: str) -> str:
    """Token without punctuation, diacritics, or a leading conjunction waw."""
    t = token.strip(_STRIP)
    for d in _STRIP:
        t = t.replace(d, "")
    return t


def substitute_divine(text: str, chain_open: bool = False):
    """Translate the 99 Names, but only where they denote God.

    Walks left to right: an anchor opens a chain, consecutive names inside the
    chain are translated, and the first token that is neither a name nor glue
    closes it. Outside a chain the words are left completely alone, so ordinary
    uses of السلام, الجامع, المؤمن and friends survive untouched.

    ``chain_open`` starts the walk already inside a chain, for when the previous
    utterance ended mid-formula. Returns ``(text, chain_open_at_end)``.
    """
    if not text:
        return text, chain_open

    out, in_chain = [], bool(chain_open)
    # True once an anchor is seen in THIS text. Until then any open chain is
    # inherited from the previous utterance, and the ambiguous names are held
    # back — see _CARRY_UNSAFE.
    anchored_here = False

    for token in text.split(" "):
        core = _bare(token)

        # A waw prefix ("والرحيم") keeps the chain and is re-attached below.
        waw = ""
        if in_chain and len(core) > 3 and core.startswith("و") and core[1:] in _DIVINE_LOOKUP:
            waw, core = "و", core[1:]

        if in_chain and core in _DIVINE_LOOKUP:
            if not anchored_here and core in _CARRY_UNSAFE:
                # Too likely to be the ordinary word. Close the inherited chain
                # rather than gamble on a formula we cannot see the start of.
                in_chain = False
                out.append(token)
                continue
            out.append(("és " if waw else "") + _DIVINE_LOOKUP[core])
            continue                       # still in the chain

        if core in _ANCHORS:
            in_chain = True
            anchored_here = True
            out.append(token)
            continue

        if core in _CHAIN_GLUE and in_chain:
            out.append(token)
            continue

        in_chain = False
        out.append(token)

    return " ".join(out), in_chain


# ---------------------------------------------------------------------------
# What to call God in Hungarian
# ---------------------------------------------------------------------------
# An EDITORIAL choice, not a technical one, and it belongs to the community
# rather than to the translation model. Left to NLLB, "الله" comes out as
# "Isten" — the ordinary Hungarian word for God, which is correct Hungarian and
# is not what this congregation asked for. Hungarian Muslim usage is commonly
# "Allah", untransliterated.
#
# Set to "" to stop substituting and let the model decide again.
#
# Only the standalone forms are replaced, and only AFTER the divine-name chain
# has run — that logic anchors on the literal "الله", so substituting it any
# earlier would stop "بسم الله الرحمن الرحيم" being recognised at all.
# Hungarian case endings are left to NLLB, which attaches them correctly to a
# Latin-script name ("Allahnak", "Allahot"); see the note above about
# placeholders surviving translation intact.
ALLAH_HU = "Allah"

_ALLAH_FORMS = {
    "اللهم": "Ó {a}",          # vocative: "O Allah"
    "لله": "{a}nak",            # "to Allah" — الحمد لله
    "بالله": "{a}ban",
    "تالله": "{a}ra",           # oath
    "الله": "{a}",
}
# Longest first, so "اللهم" is consumed before the "الله" inside it.
_ALLAH_PATTERNS = [
    (
        re.compile(
            re.escape(ar) + f"[{_DIACRITIC}]*" + f"(?![{_ARABIC_LETTER}])"
        ),
        hu,
    )
    for ar, hu in sorted(_ALLAH_FORMS.items(), key=lambda kv: -len(kv[0]))
]


def substitute_allah(text: str) -> str:
    """Render the divine name as ALLAH_HU. Run AFTER substitute_divine()."""
    if not ALLAH_HU or not text:
        return text
    for pattern, template in _ALLAH_PATTERNS:
        text = pattern.sub(template.format(a=ALLAH_HU), text)
    return text


def substitute(text: str, chain_open: bool = False):
    """Replace known Arabic names with their Hungarian forms.

    Applied to the SOURCE text, before translation. Returns mixed-script text
    (Hungarian names, Arabic everything else), which is deliberate: NLLB copies
    the Latin run through verbatim and translates the rest.

    Returns ``(text, chain_open_at_end)``; see Substituter for the stateful
    wrapper that carries that flag between utterances.
    """
    if not text:
        return text, chain_open
    for pattern, hungarian in _PATTERNS:
        text = pattern.sub(hungarian, text)
    text, chain_open = substitute_divine(text, chain_open)
    # Last, because substitute_divine anchors on the literal "الله".
    return substitute_allah(text), chain_open


class Substituter:
    """substitute() plus the memory to span an utterance boundary.

    The VAD cuts speech every few seconds without regard for grammar, so a
    formula routinely straddles two utterances. Measured live: "بسم الله الرحمن
    الرحيم" split so that "الله" landed in one chunk and "الرحمن الرحيم" in the
    next — with no anchor in its own chunk the pair went unsubstituted, and NLLB
    rendered it in the WRONG ORDER ("Az irgalmas, a könyörületes"). The same two
    words were correct moments earlier when they arrived with the anchor.

    Carrying the chain is deliberately conservative, because the failure mode in
    the other direction is worse — a stale anchor turning an ordinary
    "السلام عليكم" into "a Béke Forrása عليكم":

      * the carry survives exactly ONE utterance, then lapses;
      * it lapses anyway after CARRY_SECONDS, so a pause ends the formula the
        way a listener would hear it;
      * it only ever matters when the next utterance BEGINS with a divine name,
        since anything else closes the chain on the first token regardless.
    """

    CARRY_SECONDS = 4.0

    def __init__(self, carry_seconds: float | None = None):
        self._carry_seconds = (
            self.CARRY_SECONDS if carry_seconds is None else carry_seconds
        )
        self._chain_open = False
        self._last_at = 0.0

    def reset(self):
        """Forget any open chain — call on mode change or after a long gap."""
        self._chain_open = False
        self._last_at = 0.0

    def apply(self, text: str) -> str:
        now = time.monotonic()
        fresh = (now - self._last_at) <= self._carry_seconds
        carry = self._chain_open and fresh
        out, self._chain_open = substitute(text, chain_open=carry)
        self._last_at = now
        return out

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


def substitute(text: str) -> str:
    """Replace known Arabic names with their Hungarian forms.

    Applied to the SOURCE text, before translation. Returns mixed-script text
    (Hungarian names, Arabic everything else), which is deliberate: NLLB copies
    the Latin run through verbatim and translates the rest.
    """
    if not text:
        return text
    for pattern, hungarian in _PATTERNS:
        text = pattern.sub(hungarian, text)
    return text

"""Numbers, written out so they can be read out loud.

Ming-3.0-tts can normalise numbers with an FST grammar, but the grammar
needs pynini, which has no Windows wheel.  So the numbers are written out
here instead, before the text reaches the model.

Without this, "6,451" comes out as "six four fifty one" -- three numbers
where there should be one -- and a child listening learns that a fact about
planets is a sequence of digits rather than a quantity.
"""

from __future__ import annotations

import re

#: The units, indexed by place.
_UNITS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)

_TENS = (
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)

_SCALES = (
    (10**12, "trillion"),
    (10**9, "billion"),
    (10**6, "million"),
    (1000, "thousand"),
)


def _under_hundred(number: int) -> str:
    if number < 20:
        return _UNITS[number]
    tens, ones = divmod(number, 10)
    if ones:
        return f"{_TENS[tens]}-{_UNITS[ones]}"
    return _TENS[tens]


def _under_thousand(number: int) -> str:
    hundreds, rest = divmod(number, 100)
    if not hundreds:
        return _under_hundred(rest)
    if not rest:
        return f"{_UNITS[hundreds]} hundred"
    return f"{_UNITS[hundreds]} hundred and {_under_hundred(rest)}"


def _whole(number: int) -> str:
    """A whole number, in words."""
    if number < 0:
        return "minus " + _whole(-number)
    if number < 1000:
        return _under_thousand(number)
    if number < 10**6:
        thousands, rest = divmod(number, 1000)
        words = f"{_whole(thousands)} thousand"
        if rest:
            words += f" {_under_thousand(rest)}"
        return words
    if number < 10**9:
        millions, rest = divmod(number, 10**6)
        words = f"{_whole(millions)} million"
        if rest:
            words += f" {_whole(rest)}"
        return words
    if number < 10**12:
        billions, rest = divmod(number, 10**9)
        words = f"{_whole(billions)} billion"
        if rest:
            words += f" {_whole(rest)}"
        return words
    trillions, rest = divmod(number, 10**12)
    words = f"{_whole(trillions)} trillion"
    if rest:
        words += f" {_whole(rest)}"
    return words


def _year(number: int) -> str | None:
    """Years are said the way people say them.

    Only the range a discovery could fall in is treated this way.  A
    catalogue number like 1257 is not a year, and saying it as one turns
    "B one thousand two hundred and fifty-seven" into nonsense.
    """
    if 1900 <= number <= 1999:
        high, low = divmod(number, 100)
        if low == 0:
            return f"{_whole(high)} hundred"
        if low < 10:
            return f"{_whole(high)} oh {_UNITS[low]}"
        return f"{_whole(high)} {_under_hundred(low)}"
    if number == 2000:
        return "two thousand"
    if 2001 <= number <= 2009:
        return f"two thousand and {_UNITS[number - 2000]}"
    if 2010 <= number <= 2029:
        # "twenty sixteen", not "twenty six" -- which is twenty-six.
        return f"twenty {_under_hundred(number % 100)}"
    return None


#: How a letter is said on its own, as in "B" in "PSR B1257".
_LETTER_NAMES = {
    "A": "ay",
    "B": "bee",
    "C": "see",
    "D": "dee",
    "E": "ee",
    "F": "eff",
    "G": "gee",
    "H": "aitch",
    "I": "eye",
    "J": "jay",
    "K": "kay",
    "L": "ell",
    "M": "em",
    "N": "en",
    "O": "oh",
    "P": "pee",
    "Q": "cue",
    "R": "ar",
    "S": "ess",
    "T": "tee",
    "U": "you",
    "V": "vee",
    "W": "double you",
    "X": "ex",
    "Y": "why",
    "Z": "zee",
}


def _digit_by_digit(digits: str) -> str:
    """Digits said one at a time, the way a catalogue number is said.

    "1257" is one thousand two hundred and fifty-seven when it is a
    quantity, and "one two five seven" when it is the name of a star.
    """
    return " ".join(_UNITS[int(digit)] for digit in digits)


def _number_to_words(text: str) -> str:
    """One number, in words."""
    negative = text.startswith("-")
    if negative:
        text = text[1:]

    if "." in text:
        whole, _, fraction = text.partition(".")
        whole = whole or "0"
        words = f"{_whole(int(whole))} point"
        for digit in fraction:
            words += f" {_UNITS[int(digit)]}"
        return ("minus " + words) if negative else words

    number = int(text)
    if 1900 <= number <= 2029:
        year = _year(number)
        if year:
            return ("minus " + year) if negative else year
    words = _whole(number)
    return ("minus " + words) if negative else words


#: A number, possibly with a sign, a comma, a decimal point or a percent.
_NUMBER_RE = re.compile(
    r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w])"
    r"|(?<![\w.])-?\d+(?:\.\d+)?(?![\w])"
)

#: A catalogue prefix followed by a number, as in "HD 189733", "GJ 1214" or
#: "TOI-700".
#:
#: A short prefix is an acronym said letter by letter -- "H D one eight
#: nine seven three three".  A long one is a word -- TRAPPIST is said
#: "trap-ist", not "tee ar ay pee pee eye ess tee", so prefixes of more
#: than three letters are left alone.
_PREFIX_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Z]{2,3})[ -](\d{1,3}(?:,\d{3})+|\d+)(?![A-Za-z0-9])"
)

#: A number that follows a capital letter, as in "B1257" or "PSR B12".
#:
#: These are names, not measurements.  The digits are said one at a time,
#: the way anybody says a catalogue number, and the letter is said as a
#: letter -- "PSR B one two five seven", not "PSR Bone thousand".
_NAME_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9.])([A-Z])(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![A-Za-z0-9])"
)

#: Dimensions, as in 16x16.
_DIMENSION_RE = re.compile(r"(?<![\w.])(\d+)\s*[x×]\s*(\d+)(?![\w])")

#: Percentages.
_PERCENT_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*%")

#: The common fractions, and the word for them.
_FRACTION_WORDS = {
    2: "half",
    3: "third",
    4: "quarter",
    5: "fifth",
    8: "eighth",
    10: "tenth",
    16: "sixteenth",
}

_FRACTION_RE = re.compile(r"(?<![\w.])(\d+)\s*/\s*(\d+)(?![\w])")

#: Full-width digits and punctuation, which some models produce.
_FULLWIDTH = {ord(c): chr(i) for i, c in enumerate("０１２３４５６７８９，．－")}


def spell_numbers(text: str) -> str:
    """Rewrite the numbers in a text so they can be read out loud."""
    if not text:
        return text
    text = text.translate(_FULLWIDTH)

    def dimensions(match: re.Match[str]) -> str:
        width, height = match.group(1), match.group(2)
        return f"{_number_to_words(width)} by {_number_to_words(height)}"

    def percentages(match: re.Match[str]) -> str:
        return f"{_number_to_words(match.group(1))} per cent"

    def fractions(match: re.Match[str]) -> str:
        numerator, denominator = match.group(1), match.group(2)
        name = _FRACTION_WORDS.get(int(denominator))
        if name is None:
            return match.group(0)
        if int(numerator) != 1:
            name += "s" if name.endswith("h") else "s"
        return f"{_number_to_words(numerator)} {name}"

    def prefixed(match: re.Match[str]) -> str:
        prefix, digits = match.group(1), match.group(2).replace(",", "")
        try:
            spoken = " ".join(
                _LETTER_NAMES.get(letter, letter.lower()) for letter in prefix
            )
            if len(digits) > 3:
                return f"{spoken} {_digit_by_digit(digits)}"
            return f"{spoken} {_number_to_words(digits)}"
        except (ValueError, IndexError):
            return match.group(0)

    def named(match: re.Match[str]) -> str:
        letter, digits = match.group(1), match.group(2)
        name = _LETTER_NAMES.get(letter, letter.lower())
        try:
            return f"{name} {_digit_by_digit(digits.replace(',', ''))}"
        except (ValueError, IndexError):
            return match.group(0)
    def numbers(match: re.Match[str]) -> str:
        raw = match.group(0).replace(",", "")
        try:
            return _number_to_words(raw)
        except (ValueError, IndexError):
            return match.group(0)

    out = _DIMENSION_RE.sub(dimensions, text)
    out = _PERCENT_RE.sub(percentages, out)
    out = _FRACTION_RE.sub(fractions, out)
    out = _PREFIX_NUMBER_RE.sub(prefixed, out)
    out = _NAME_NUMBER_RE.sub(named, out)
    out = _NUMBER_RE.sub(numbers, out)
    return out


__all__ = ["spell_numbers"]

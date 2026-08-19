# -*- coding: utf-8 -*-
"""JARVIS brain extension: ~200 more day-to-day skills plus the offline
conversational chat engine used when the Groq LLM is unreachable.

Everything here registers into the main Brain via register_extra() and can
talk to the user through local_chat() when no API key is available."""

import datetime
import getpass
import hashlib
import json
import math
import os
import platform
import random
import re
import shutil
import string
import subprocess
import time
import uuid
import zoneinfo

from brain import _llm, _int_nums, _nums, open_path, run_cmd, osascript, \
    osascript_out, FOLDER_PATHS, MONTH_NUM, MONTH_ABBR

MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "jarvis_memory.json")


def _int_to_words(n):
    """Convert an integer to English words."""
    if n < 0:
        return "Negative " + _int_to_words(abs(n))
    if n == 0:
        return "Zero"
    ones = ["", "one", "two", "three", "four", "five", "six", "seven",
            "eight", "nine", "ten", "eleven", "twelve", "thirteen",
            "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
            "nineteen"]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty",
            "seventy", "eighty", "ninety"]
    if n < 20:
        return ones[n].title()
    if n < 100:
        return (tens[n // 10] +
                ("-" + ones[n % 10] if n % 10 else "")).title()
    if n < 1000:
        rest = _int_to_words(n % 100).lower()
        return ("%s hundred%s" %
                (ones[n // 100],
                 " and " + rest if n % 100 else "")).title()
    if n < 1000000:
        rest = _int_to_words(n % 1000).lower()
        return ("%s thousand %s" %
                (_int_to_words(n // 1000).lower(),
                 rest)).title().strip()
    if n < 1000000000:
        rest = _int_to_words(n % 1000000).lower()
        return ("%s million %s" %
                (_int_to_words(n // 1000000).lower(),
                 rest)).title().strip()
    return str(n)


# ---------------------------------------------------------------------------
# LOCAL KNOWLEDGE BASE  (used by the offline chat brain)
# ---------------------------------------------------------------------------

COUNTRIES = {
    "india": ("New Delhi", "1.4 billion", "Indian rupee", "Hindi", "Asia"),
    "united states": ("Washington D.C.", "335 million", "US dollar",
                      "English", "North America"),
    "usa": ("Washington D.C.", "335 million", "US dollar",
            "English", "North America"),
    "america": ("Washington D.C.", "335 million", "US dollar",
                "English", "North America"),
    "uk": ("London", "67 million", "pound sterling", "English", "Europe"),
    "united kingdom": ("London", "67 million", "pound sterling",
                       "English", "Europe"),
    "britain": ("London", "67 million", "pound sterling", "English", "Europe"),
    "france": ("Paris", "68 million", "euro", "French", "Europe"),
    "germany": ("Berlin", "84 million", "euro", "German", "Europe"),
    "japan": ("Tokyo", "125 million", "yen", "Japanese", "Asia"),
    "china": ("Beijing", "1.41 billion", "yuan", "Mandarin", "Asia"),
    "russia": ("Moscow", "144 million", "ruble", "Russian", "Europe"),
    "brazil": ("Brasilia", "215 million", "real", "Portuguese",
               "South America"),
    "canada": ("Ottawa", "39 million", "Canadian dollar", "English",
               "North America"),
    "australia": ("Canberra", "26 million", "Australian dollar", "English",
                  "Oceania"),
    "italy": ("Rome", "59 million", "euro", "Italian", "Europe"),
    "spain": ("Madrid", "48 million", "euro", "Spanish", "Europe"),
    "mexico": ("Mexico City", "128 million", "peso", "Spanish",
               "North America"),
    "south korea": ("Seoul", "52 million", "won", "Korean", "Asia"),
    "korea": ("Seoul", "52 million", "won", "Korean", "Asia"),
    "singapore": ("Singapore", "5.9 million", "Singapore dollar", "English",
                  "Asia"),
    "uae": ("Abu Dhabi", "10 million", "dirham", "Arabic", "Asia"),
    "united arab emirates": ("Abu Dhabi", "10 million", "dirham", "Arabic",
                             "Asia"),
    "saudi arabia": ("Riyadh", "36 million", "riyal", "Arabic", "Asia"),
    "egypt": ("Cairo", "110 million", "pound", "Arabic", "Africa"),
    "south africa": ("Pretoria", "60 million", "rand", "English", "Africa"),
    "nigeria": ("Abuja", "218 million", "naira", "English", "Africa"),
    "kenya": ("Nairobi", "55 million", "shilling", "English", "Africa"),
    "turkey": ("Ankara", "85 million", "lira", "Turkish", "Europe"),
    "indonesia": ("Jakarta", "275 million", "rupiah", "Indonesian", "Asia"),
    "thailand": ("Bangkok", "71 million", "baht", "Thai", "Asia"),
    "vietnam": ("Hanoi", "98 million", "dong", "Vietnamese", "Asia"),
    "philippines": ("Manila", "115 million", "peso", "Filipino", "Asia"),
    "pakistan": ("Islamabad", "235 million", "rupee", "Urdu", "Asia"),
    "bangladesh": ("Dhaka", "170 million", "taka", "Bengali", "Asia"),
    "sri lanka": ("Colombo", "22 million", "rupee", "Sinhala", "Asia"),
    "nepal": ("Kathmandu", "30 million", "rupee", "Nepali", "Asia"),
    "new zealand": ("Wellington", "5.1 million", "New Zealand dollar",
                    "English", "Oceania"),
    "argentina": ("Buenos Aires", "46 million", "peso", "Spanish",
                  "South America"),
    "chile": ("Santiago", "19 million", "peso", "Spanish", "South America"),
    "colombia": ("Bogota", "52 million", "peso", "Spanish", "South America"),
    "portugal": ("Lisbon", "10 million", "euro", "Portuguese", "Europe"),
    "netherlands": ("Amsterdam", "17 million", "euro", "Dutch", "Europe"),
    "belgium": ("Brussels", "11 million", "euro", "Dutch", "Europe"),
    "sweden": ("Stockholm", "10 million", "krona", "Swedish", "Europe"),
    "norway": ("Oslo", "5.4 million", "kroner", "Norwegian", "Europe"),
    "finland": ("Helsinki", "5.5 million", "euro", "Finnish", "Europe"),
    "switzerland": ("Bern", "8.7 million", "Swiss franc", "German", "Europe"),
    "austria": ("Vienna", "9 million", "euro", "German", "Europe"),
    "greece": ("Athens", "10 million", "euro", "Greek", "Europe"),
    "ireland": ("Dublin", "5 million", "euro", "English", "Europe"),
    "poland": ("Warsaw", "38 million", "zloty", "Polish", "Europe"),
    "morocco": ("Rabat", "37 million", "dirham", "Arabic", "Africa"),
    "ghana": ("Accra", "33 million", "cedi", "English", "Africa"),
    "ethiopia": ("Addis Ababa", "120 million", "birr", "Amharic", "Africa"),
    "iran": ("Tehran", "88 million", "rial", "Persian", "Asia"),
    "israel": ("Jerusalem", "9.5 million", "shekel", "Hebrew", "Asia"),
    "qatar": ("Doha", "2.8 million", "riyal", "Arabic", "Asia"),
    "oman": ("Muscat", "4.6 million", "rial", "Arabic", "Asia"),
    "kuwait": ("Kuwait City", "4.3 million", "dinar", "Arabic", "Asia"),
    "jordan": ("Amman", "11 million", "dinar", "Arabic", "Asia"),
    "lebanon": ("Beirut", "5.5 million", "pound", "Arabic", "Asia"),
    "cuba": ("Havana", "11 million", "peso", "Spanish", "North America"),
    "peru": ("Lima", "34 million", "sol", "Spanish", "South America"),
    "venezuela": ("Caracas", "28 million", "bolivar", "Spanish",
                  "South America"),
    "czech republic": ("Prague", "10 million", "koruna", "Czech", "Europe"),
    "hungary": ("Budapest", "9.7 million", "forint", "Hungarian", "Europe"),
    "romania": ("Bucharest", "19 million", "leu", "Romanian", "Europe"),
    "ukraine": ("Kyiv", "37 million", "hryvnia", "Ukrainian", "Europe"),
    "afghanistan": ("Kabul", "41 million", "afghani", "Pashto", "Asia"),
    "algeria": ("Algiers", "45 million", "dinar", "Arabic", "Africa"),
    "angola": ("Luanda", "35 million", "kwanza", "Portuguese", "Africa"),
    "azerbaijan": ("Baku", "10 million", "manat", "Azerbaijani", "Asia"),
    "bahrain": ("Manama", "1.5 million", "dinar", "Arabic", "Asia"),
    "belarus": ("Minsk", "9.4 million", "ruble", "Belarusian", "Europe"),
    "bolivia": ("Sucre", "12 million", "boliviano", "Spanish", "South America"),
    "cambodia": ("Phnom Penh", "17 million", "riel", "Khmer", "Asia"),
    "cameroon": ("Yaounde", "28 million", "CFA franc", "French", "Africa"),
    "costa rica": ("San Jose", "5.2 million", "colon", "Spanish", "North America"),
    "croatia": ("Zagreb", "3.9 million", "euro", "Croatian", "Europe"),
    "denmark": ("Copenhagen", "5.9 million", "krone", "Danish", "Europe"),
    "dominican republic": ("Santo Domingo", "11 million", "peso", "Spanish",
                           "North America"),
    "ecuador": ("Quito", "18 million", "US dollar", "Spanish", "South America"),
    "el salvador": ("San Salvador", "6.5 million", "US dollar", "Spanish",
                    "North America"),
    "eritrea": ("Asmara", "3.6 million", "nakfa", "Tigrinya", "Africa"),
    "estonia": ("Tallinn", "1.3 million", "euro", "Estonian", "Europe"),
    "georgia": ("Tbilisi", "3.7 million", "lari", "Georgian", "Europe"),
    "guatemala": ("Guatemala City", "18 million", "quetzal", "Spanish",
                  "North America"),
    "honduras": ("Tegucigalpa", "10 million", "lempira", "Spanish",
                 "North America"),
    "iceland": ("Reykjavik", "380 thousand", "króna", "Icelandic", "Europe"),
    "iraq": ("Baghdad", "43 million", "dinar", "Arabic", "Asia"),
    "ivory coast": ("Yamoussoukro", "28 million", "CFA franc", "French",
                    "Africa"),
    "jamaica": ("Kingston", "3 million", "Jamaican dollar", "English",
                "North America"),
    "kazakhstan": ("Astana", "19 million", "tenge", "Kazakh", "Asia"),
    "kyrgyzstan": ("Bishkek", "7 million", "som", "Kyrgyz", "Asia"),
    "laos": ("Vientiane", "7.5 million", "kip", "Lao", "Asia"),
    "latvia": ("Riga", "1.8 million", "euro", "Latvian", "Europe"),
    "libya": ("Tripoli", "7 million", "dinar", "Arabic", "Africa"),
    "lithuania": ("Vilnius", "2.8 million", "euro", "Lithuanian", "Europe"),
    "luxembourg": ("Luxembourg City", "660 thousand", "euro", "Luxembourgish",
                   "Europe"),
    "madagascar": ("Antananarivo", "29 million", "ariary", "Malagasy",
                   "Africa"),
    "malawi": ("Lilongwe", "20 million", "kwacha", "English", "Africa"),
    "malaysia": ("Kuala Lumpur", "33 million", "ringgit", "Malay", "Asia"),
    "maldives": ("Male", "520 thousand", "rufiyaa", "Dhivehi", "Asia"),
    "mali": ("Bamako", "22 million", "CFA franc", "French", "Africa"),
    "mauritius": ("Port Louis", "1.3 million", "Mauritian rupee", "English",
                  "Africa"),
    "mongolia": ("Ulaanbaatar", "3.4 million", "tugrik", "Mongolian", "Asia"),
    "mozambique": ("Maputo", "33 million", "metical", "Portuguese", "Africa"),
    "myanmar": ("Naypyidaw", "54 million", "kyat", "Burmese", "Asia"),
    "nicaragua": ("Managua", "6.9 million", "córdoba", "Spanish",
                  "North America"),
    "palestine": ("Ramallah", "5.4 million", "Israeli shekel", "Arabic",
                  "Asia"),
    "panama": ("Panama City", "4.4 million", "balboa", "Spanish",
               "North America"),
    "paraguay": ("Asuncion", "7.4 million", "guaraní", "Spanish",
                 "South America"),
    "republic of the congo": ("Brazzaville", "6 million", "CFA franc",
                              "French", "Africa"),
    "senegal": ("Dakar", "17 million", "CFA franc", "French", "Africa"),
    "serbia": ("Belgrade", "6.6 million", "dinar", "Serbian", "Europe"),
    "slovakia": ("Bratislava", "5.4 million", "euro", "Slovak", "Europe"),
    "slovenia": ("Ljubljana", "2.1 million", "euro", "Slovenian", "Europe"),
    "somalia": ("Mogadishu", "17 million", "Somali shilling", "Somali",
                "Africa"),
    "sudan": ("Khartoum", "47 million", "Sudanese pound", "Arabic", "Africa"),
    "swaziland": ("Mbabane", "1.2 million", "lilangeni", "English", "Africa"),
    "taiwan": ("Taipei", "24 million", "New Taiwan dollar", "Mandarin",
               "Asia"),
    "tanzania": ("Dodoma", "65 million", "Tanzanian shilling", "English",
                 "Africa"),
    "tunisia": ("Tunis", "12 million", "dinar", "Arabic", "Africa"),
    "uganda": ("Kampala", "48 million", "Ugandan shilling", "English",
               "Africa"),
    "uruguay": ("Montevideo", "3.4 million", "peso", "Spanish",
                "South America"),
    "uzbekistan": ("Tashkent", "35 million", "som", "Uzbek", "Asia"),
    "zambia": ("Lusaka", "20 million", "kwacha", "English", "Africa"),
    "zimbabwe": ("Harare", "16 million", "US dollar", "English", "Africa"),
}

COUNTRY_TZ = {
    "india": "Asia/Kolkata", "japan": "Asia/Tokyo",
    "china": "Asia/Shanghai", "uk": "Europe/London",
    "britain": "Europe/London", "usa": "America/New_York",
    "united states": "America/New_York", "france": "Europe/Paris",
    "germany": "Europe/Berlin", "australia": "Australia/Sydney",
    "canada": "America/Toronto", "brazil": "America/Sao_Paulo",
    "russia": "Europe/Moscow", "italy": "Europe/Rome",
    "spain": "Europe/Madrid", "mexico": "America/Mexico_City",
    "south korea": "Asia/Seoul", "singapore": "Asia/Singapore",
    "uae": "Asia/Dubai", "united arab emirates": "Asia/Dubai",
    "saudi arabia": "Asia/Riyadh", "egypt": "Africa/Cairo",
    "south africa": "Africa/Johannesburg", "nigeria": "Africa/Lagos",
    "kenya": "Africa/Nairobi", "turkey": "Europe/Istanbul",
    "indonesia": "Asia/Jakarta", "thailand": "Asia/Bangkok",
    "vietnam": "Asia/Ho_Chi_Minh", "philippines": "Asia/Manila",
    "pakistan": "Asia/Karachi", "bangladesh": "Asia/Dhaka",
    "sri lanka": "Asia/Colombo", "nepal": "Asia/Kathmandu",
    "new zealand": "Pacific/Auckland", "argentina": "America/Argentina/Buenos_Aires",
    "portugal": "Europe/Lisbon", "netherlands": "Europe/Amsterdam",
    "sweden": "Europe/Stockholm", "switzerland": "Europe/Zurich",
    "greece": "Europe/Athens", "ireland": "Europe/Dublin",
    "poland": "Europe/Warsaw", "morocco": "Africa/Casablanca",
    "israel": "Asia/Jerusalem", "iran": "Asia/Tehran",
}

ELEMENTS = {
    "hydrogen": ("H", 1, 1.008, "the lightest element, makes up about 75% "
                 "of the universe's mass"),
    "helium": ("He", 2, 4.003, "named after the sun because it was first "
               "found in the solar spectrum"),
    "lithium": ("Li", 3, 6.94, "used in rechargeable batteries"),
    "carbon": ("C", 6, 12.011, "the basis of all known life"),
    "nitrogen": ("N", 7, 14.007, "makes up 78% of the air we breathe"),
    "oxygen": ("O", 8, 15.999, "essential for breathing, 21% of the air"),
    "sodium": ("Na", 11, 22.99, "half of table salt; violently reacts "
               "with water"),
    "aluminium": ("Al", 13, 26.98, "the most abundant metal in Earth's crust"),
    "aluminum": ("Al", 13, 26.98, "the most abundant metal in Earth's crust"),
    "silicon": ("Si", 14, 28.085, "the backbone of computer chips"),
    "phosphorus": ("P", 15, 30.974, "glows in the dark; needed for DNA"),
    "sulfur": ("S", 16, 32.06, "smells like rotten eggs in compounds"),
    "sulphur": ("S", 16, 32.06, "smells like rotten eggs in compounds"),
    "chlorine": ("Cl", 17, 35.45, "used to disinfect water"),
    "potassium": ("K", 19, 39.098, "bananas are rich in it"),
    "calcium": ("Ca", 20, 40.078, "keeps your bones and teeth strong"),
    "iron": ("Fe", 26, 55.845, "gives blood its red color"),
    "nickel": ("Ni", 28, 58.693, "found in coins and batteries"),
    "copper": ("Cu", 29, 63.546, "excellent electrical conductor"),
    "zinc": ("Zn", 30, 65.38, "essential for the immune system"),
    "silver": ("Ag", 47, 107.87, "best electrical conductor of all metals"),
    "gold": ("Au", 79, 196.97, "one of the least reactive metals, "
             "does not tarnish"),
    "mercury": ("Hg", 80, 200.59, "the only metal that is liquid at room "
                "temperature"),
    "lead": ("Pb", 82, 207.2, "heavy and toxic, once used in pipes"),
    "uranium": ("U", 92, 238.03, "used as fuel in nuclear reactors"),
    "titanium": ("Ti", 22, 47.867, "strong, light, and used in airplanes"),
    "chromium": ("Cr", 24, 51.996, "gives stainless steel its shine"),
    "manganese": ("Mn", 25, 54.938, "essential for making steel"),
    "cobalt": ("Co", 27, 58.933, "gives blue color to glass"),
    "arsenic": ("As", 33, 74.922, "famous poison; also used in electronics"),
    "bromine": ("Br", 35, 79.904, "one of only two elements liquid at room "
                "temperature"),
    "tin": ("Sn", 50, 118.71, "used to make bronze and solder"),
    "iodine": ("I", 53, 126.9, "essential for your thyroid"),
    "tungsten": ("W", 74, 183.84, "has the highest melting point of all "
                 "metals"),
    "platinum": ("Pt", 78, 195.08, "used in catalytic converters"),
    "beryllium": ("Be", 4, 9.012, "extremely lightweight yet stronger than steel"),
    "boron": ("B", 5, 10.81, "used in heat-resistant glass like Pyrex"),
    "fluorine": ("F", 9, 18.998, "the most reactive element of all"),
    "neon": ("Ne", 10, 20.18, "gives neon signs their distinctive red-orange glow"),
    "magnesium": ("Mg", 12, 24.305, "burns with a brilliant white flame"),
    "aluminium": ("Al", 13, 26.982, "the most abundant metal in Earth's crust"),
    "argon": ("Ar", 18, 39.948, "the third most abundant gas in the atmosphere"),
    "scandium": ("Sc", 21, 44.956, "used in aerospace alloys for fighter jets"),
    "vanadium": ("V", 23, 50.942, "makes steel axles and springs incredibly tough"),
    "gallium": ("Ga", 31, 69.723, "melts in your hand at just 29.76 degrees C"),
    "germanium": ("Ge", 32, 72.63, "used in fiber optics and infrared optics"),
    "arsenic": ("As", 33, 74.922, "a notorious poison also used in semiconductors"),
    "selenium": ("Se", 34, 78.971, "essential in small amounts but toxic in large doses"),
    "krypton": ("Kr", 36, 83.798, "named after a fictional element in Superman"),
    "rubidium": ("Rb", 37, 85.468, "ignites spontaneously in air"),
    "strontium": ("Sr", 38, 87.62, "makes fireworks display bright red colors"),
    "yttrium": ("Y", 39, 88.906, "used in LEDs and camera lenses"),
    "zirconium": ("Zr", 40, 91.224, "used in nuclear reactors and ceramics"),
    "niobium": ("Nb", 41, 92.906, "used in MRI magnets and jet engines"),
    "molybdenum": ("Mo", 42, 95.95, "has one of the highest melting points of any element"),
    "ruthenium": ("Ru", 44, 101.07, "a rare platinum metal used in electronics"),
    "rhodium": ("Rh", 45, 102.91, "the most expensive precious metal in the world"),
    "palladium": ("Pd", 46, 106.42, "absorbs 900 times its own volume of hydrogen"),
    "indium": ("In", 49, 114.82, "so soft you can cut it with a knife"),
    "antimony": ("Sb", 51, 121.76, "used in flame retardants and batteries"),
    "xenon": ("Xe", 54, 131.29, "used in spacecraft ion engines"),
    "cesium": ("Cs", 55, 132.91, "so reactive it explodes on contact with water"),
    "barium": ("Ba", 56, 137.33, "gives a white color to fireworks"),
    "lanthanum": ("La", 57, 138.91, "named after the Greek word for to hide"),
    "cerium": ("Ce", 58, 140.12, "the most abundant rare earth element"),
    "praseodymium": ("Pr", 59, 140.91, "used in aircraft engines and magnets"),
    "neodymium": ("Nd", 60, 144.24, "used to make the world's strongest permanent magnets"),
    "promethium": ("Pm", 61, 145, "the only radioactive rare earth with no stable isotopes"),
    "samarium": ("Sm", 62, 150.36, "used in nuclear reactor control rods"),
    "europium": ("Eu", 63, 151.96, "gives euro banknotes their red fluorescent glow"),
    "gadolinium": ("Gd", 64, 157.25, "used as contrast agent in MRI scans"),
    "terbium": ("Tb", 65, 158.93, "used in green phosphors for screens"),
    "dysprosium": ("Dy", 66, 162.5, "has one of the highest magnetic susceptibilities"),
    "holmium": ("Ho", 67, 164.93, "has the highest magnetic moment of any element"),
    "erbium": ("Er", 68, 167.26, "used in fiber optic amplifiers"),
    "thulium": ("Tm", 69, 168.93, "the rarest of the rare earth elements"),
    "ytterbium": ("Yb", 70, 173.05, "used in atomic clocks and stress gauges"),
    "lutetium": ("Lu", 71, 174.97, "the hardest and densest of the rare earth elements"),
    "hafnium": ("Hf", 72, 178.49, "used in nuclear reactor control rods"),
    "tantalum": ("Ta", 73, 180.95, "highly corrosion resistant and used in phones"),
    "rhenium": ("Re", 75, 186.21, "one of the rarest elements in Earth's crust"),
    "osmium": ("Os", 76, 190.23, "the densest naturally occurring element"),
    "iridium": ("Ir", 77, 192.22, "layer at the K-Pg boundary suggests asteroid impact"),
    "thallium": ("Tl", 81, 204.38, "once a popular poison because it is colorless and odorless"),
    "bismuth": ("Bi", 83, 208.98, "forms beautiful rainbow-colored crystals when it oxidizes"),
    "polonium": ("Po", 84, 209, "discovered by Marie Curie, named after her homeland Poland"),
    "radon": ("Rn", 86, 222, "a radioactive gas that can accumulate in basements"),
    "francium": ("Fr", 87, 223, "the most unstable naturally occurring element"),
    "radium": ("Ra", 88, 226, "glows faintly blue due to its radioactivity"),
    "actinium": ("Ac", 89, 227, "glows in the dark because of its intense radioactivity"),
    "thorium": ("Th", 90, 232.04, "a potential nuclear fuel safer than uranium"),
    "protactinium": ("Pa", 91, 231.04, "one of the rarest and most expensive natural elements"),
    "neptunium": ("Np", 93, 237, "the first synthetic transuranium element"),
    "plutonium": ("Pu", 94, 244, "used in nuclear weapons and deep-space probes"),
    "americium": ("Am", 95, 243, "used in household smoke detectors"),
    "curium": ("Cm", 96, 247, "named after Marie and Pierre Curie"),
    "berkelium": ("Bk", 97, 247, "named after Berkeley, California"),
    "californium": ("Cf", 98, 251, "used to detect gold and silver in ore"),
    "einsteinium": ("Es", 99, 252, "discovered in debris from the first hydrogen bomb"),
    "fermium": ("Fm", 100, 257, "named after Enrico Fermi"),
    "mendelevium": ("Md", 101, 258, "named after Dmitri Mendeleev who created the periodic table"),
    "nobelium": ("No", 102, 259, "named after Alfred Nobel"),
    "lawrencium": ("Lr", 103, 266, "named after Ernest Lawrence who invented the cyclotron"),
    "rutherfordium": ("Rf", 104, 267, "named after Ernest Rutherford"),
    "dubnium": ("Db", 105, 268, "named after the Russian town of Dubna"),
    "seaborgium": ("Sg", 106, 269, "named after Glenn Seaborg"),
    "bohrium": ("Bh", 107, 270, "named after Niels Bohr"),
    "hassium": ("Hs", 108, 277, "named after the German state of Hesse"),
    "meitnerium": ("Mt", 109, 278, "named after Lise Meitner"),
    "darmstadtium": ("Ds", 110, 281, "named after the German city of Darmstadt"),
    "roentgenium": ("Rg", 111, 282, "named after Wilhelm Röntgen who discovered X-rays"),
    "copernicium": ("Cn", 112, 285, "named after Nicolaus Copernicus"),
    "nihonium": ("Nh", 113, 286, "named after Japan meaning the land of the rising sun"),
    "flerovium": ("Fl", 114, 289, "named after the Flerov Laboratory of Nuclear Reactions"),
    "moscovium": ("Mc", 115, 290, "named after Moscow"),
    "livermorium": ("Lv", 116, 293, "named after Livermore, California"),
    "tennessine": ("Ts", 117, 294, "named after the state of Tennessee"),
    "oganesson": ("Og", 118, 294, "named after Yuri Oganessian, newest named element"),
}

PLANETS = {
    "mercury": ("the smallest planet", 4879, 0,
                "a year there is just 88 Earth days"),
    "venus": ("the hottest planet", 12104, 0,
              "a day on Venus is longer than its year"),
    "earth": ("our home planet", 12756, 1,
              "the only known planet with life"),
    "mars": ("the red planet", 6792, 2,
             "home to the tallest volcano in the solar system, Olympus Mons"),
    "jupiter": ("the largest planet", 142984, 95,
                "its Great Red Spot is a storm bigger than Earth"),
    "saturn": ("the ringed planet", 120536, 146,
               "its rings are made of ice and rock"),
    "uranus": ("the sideways planet", 51118, 28,
               "it rotates on its side"),
    "neptune": ("the windiest planet", 49528, 16,
                "winds there reach 2,000 km/h"),
}

ANIMALS = {
    "octopus": ("Octopuses have three hearts, blue blood, and nine brains, "
                "sir."),
    "penguin": ("Penguins propose to their partners with a pebble, sir."),
    "elephant": ("Elephants are the only animals that cannot jump, sir."),
    "giraffe": ("A giraffe's neck has only seven bones, same as a human's, "
                "sir."),
    "sloth": ("Sloths can hold their breath longer than dolphins, sir."),
    "ant": ("Ants can lift 50 times their own body weight, sir."),
    "bee": ("A bee can recognize human faces, sir."),
    "shark": ("Sharks existed before trees, sir."),
    "dolphin": ("Dolphins call each other by name, sir."),
    "cow": ("Cows have best friends and get stressed when separated, sir."),
    "kangaroo": ("Kangaroos cannot walk backwards, sir."),
    "butterfly": ("Butterflies taste with their feet, sir."),
    "eagle": ("Eagles can see a rabbit from three kilometers away, sir."),
    "frog": ("Some frogs can freeze solid and survive the winter, sir."),
    "whale": ("The blue whale's heart is as big as a small car, sir."),
    "panda": ("A newborn panda is smaller than a stick of butter, sir."),
    "camel": ("Camels can drink 40 gallons of water in one go, sir."),
    "snake": ("Snakes smell with their tongues, sir."),
    "spider": ("Spiders can produce seven different kinds of silk, sir."),
    "lion": ("A lion's roar can be heard eight kilometers away, sir."),
    "tiger": ("Tiger stripes are like fingerprints, unique to each one, "
              "sir."),
    "horse": ("Horses can sleep standing up, sir."),
    "rabbit": ("Rabbits can see almost 360 degrees around them, sir."),
    "owl": ("Owls can rotate their heads almost all the way around, sir."),
    "cheetah": ("Cheetahs can go from zero to 100 km/h in three seconds, "
                "sir."),
}

FOODS = {
    "banana": ("A medium banana has about 105 calories and 27g of carbs, "
               "sir."),
    "apple": ("A medium apple has about 95 calories and plenty of fiber, "
              "sir."),
    "orange": ("An orange has about 62 calories and a full day's vitamin C, "
               "sir."),
    "mango": ("A mango has about 150 calories and is rich in vitamins A and "
              "C, sir."),
    "rice": ("One cup of cooked rice is about 200 calories, sir."),
    "bread": ("A slice of bread is about 80 calories, sir."),
    "egg": ("One large egg has about 72 calories and 6g of protein, sir."),
    "milk": ("A glass of milk has about 150 calories and 8g of protein, "
             "sir."),
    "chicken": ("100g of cooked chicken breast has about 165 calories and "
                "31g of protein, sir."),
    "paneer": ("100g of paneer has about 265 calories and 18g of protein, "
               "sir."),
    "cheese": ("A slice of cheddar has about 113 calories, sir."),
    "chocolate": ("100g of dark chocolate has about 550 calories, sir."),
    "coffee": ("A plain black coffee has about 2 calories, sir."),
    "tea": ("A cup of plain tea has about 2 calories, sir."),
    "pizza": ("One slice of pizza has about 285 calories, sir."),
    "burger": ("A single cheeseburger has about 300 calories, sir."),
    "pasta": ("One cup of cooked pasta has about 220 calories, sir."),
    "potato": ("A medium potato has about 160 calories, sir."),
    "tomato": ("A medium tomato has about 22 calories, sir."),
    "watermelon": ("100g of watermelon has just 30 calories, sir."),
}

CAFFEINE = {
    "coffee": ("A standard 240ml cup of coffee has about 95mg of caffeine, "
               "sir."),
    "espresso": ("A single espresso shot has about 63mg of caffeine, sir."),
    "tea": ("A cup of black tea has about 47mg of caffeine, sir."),
    "green tea": ("A cup of green tea has about 28mg of caffeine, sir."),
    "cola": ("A can of cola has about 34mg of caffeine, sir."),
    "energy drink": ("An energy drink can have 80 to 200mg of caffeine, "
                     "sir."),
    "dark chocolate": ("100g of dark chocolate has about 43mg of caffeine, "
                       "sir."),
}

CONCEPTS = {
    "black hole": "a region of space where the gravitational pull is so "
                  "strong that nothing, not even light, can escape it",
    "gravity": "the force that pulls objects with mass toward each other",
    "dna": "the molecule that carries the genetic instructions for life",
    "photosynthesis": "how plants turn sunlight, water, and carbon dioxide "
                      "into food and oxygen",
    "quantum": "the world of atoms and particles, where energy comes in "
               "tiny, fixed packets",
    "internet": "a global network of computers connected so they can share "
                "information",
    "wifi": "a technology that lets devices connect to a network wirelessly",
    "algorithm": "a step-by-step recipe for solving a problem",
    "api": "a set of rules that lets software programs talk to each other",
    "cloud": "computers and services you use over the internet instead of "
             "on your own machine",
    "encryption": "scrambling data so only the right key can read it",
    "machine learning": "teaching computers to learn patterns from data "
                        "instead of explicit instructions",
    "gpt": "a language model trained to predict and generate human-like "
           "text",
    "romance": "romantic love, or stories about it",
    "economics": "the study of how people and societies make choices about "
                 "scarce resources",
    "philosophy": "the study of big questions about existence, knowledge, "
                  "and values",
    "psychology": "the scientific study of the mind and behavior",
    "history": "the record of past events and how they shaped today",
    "metaverse": "a shared virtual world where people can interact",
    "blockchain": "a shared digital ledger that records transactions "
                  "securely",
    "crypto": "digital money that uses cryptography to secure transactions",
    "big bang": "the event about 13.8 billion years ago when the universe "
                "began expanding",
    "evolution": "how species change over generations through natural "
                 "selection",
    "atom": "the smallest unit of an element that keeps its properties",
    "cell": "the basic building block of all living things",
    "gene": "a segment of DNA that carries instructions for a trait",
    "vaccine": "a treatment that trains your immune system to fight a "
               "disease",
    "solar system": "the sun and everything that orbits it, including eight "
                    "planets",
    "galaxy": "a huge collection of stars, gas, and dust held together by "
              "gravity",
    "artificial intelligence": "computer systems that can perform tasks "
                              "requiring human-like intelligence",
    "deep learning": "a subset of machine learning using neural networks "
                     "with many layers",
    "neural network": "a computing system inspired by the human brain's "
                      "structure",
    "quantum computing": "computing that uses quantum bits which can be in "
                         "multiple states at once",
    "quantum entanglement": "a phenomenon where two particles become linked "
                            "and affect each other instantly across any "
                            "distance",
    "neutrino": "a tiny subatomic particle that barely interacts with matter",
    "dark matter": "invisible matter that makes up about 27% of the universe "
                   "but cannot be seen directly",
    "dark energy": "a mysterious force causing the universe to expand faster",
    "supernova": "the explosive death of a massive star",
    "wormhole": "a theoretical shortcut through space-time",
    "string theory": "a theory that the universe's fundamental building blocks "
                     "are tiny vibrating strings",
    "relativity": "Einstein's theory describing how space and time are linked "
                  "and affected by gravity",
    "thermodynamics": "the branch of physics dealing with heat, work, and "
                      "energy",
    "entropy": "a measure of disorder in a system; it always increases",
    "cryptography": "the practice of secure communication in the presence "
                    "of adversaries",
    "hashing": "converting data into a fixed-size string using a mathematical "
               "function",
    "blockchain": "a decentralized digital ledger that records transactions "
                  "across many computers",
    "cryptocurrency": "a digital currency using cryptography for security "
                      "and operating on a blockchain",
    "machine learning": "teaching computers to learn patterns from data "
                        "without explicit programming",
    "natural language processing": "teaching computers to understand and "
                                   "generate human language",
    "computer vision": "teaching computers to interpret and understand "
                       "visual information",
    "robotics": "the branch of technology dealing with the design and "
                "use of robots",
    "genetic engineering": "directly modifying an organism's genes using "
                           "biotechnology",
    "crispr": "a gene-editing tool that can cut and modify DNA with precision",
    "mRNA": "messenger RNA carries genetic instructions from DNA to build "
            "proteins in cells",
    "protein": "a complex molecule made of amino acids that does most of "
               "the work in cells",
    "microbiome": "the community of trillions of microorganisms living in "
                  "and on your body",
    "quantum mechanics": "the physics of very small particles like atoms "
                         "and subatomic particles",
    "semiconductor": "a material whose electrical conductivity is between "
                     "that of a conductor and an insulator",
    "transistor": "a tiny electronic switch that is the building block of "
                  "all modern computers",
    "circuit": "a path through which electric current can flow",
    "voltage": "the electrical pressure that pushes current through a circuit",
    "resistance": "the opposition to the flow of electric current",
    "capacitor": "a device that stores electrical energy in an electric field",
    "battery": "a device that stores chemical energy and converts it to "
               "electrical energy",
    "solar panel": "a device that converts sunlight directly into electricity "
                   "using photovoltaic cells",
    "renewable energy": "energy from sources that naturally replenish like "
                        "sun, wind, and water",
    "carbon footprint": "the total greenhouse gases caused by an individual's "
                        "actions",
    "climate change": "long-term shifts in global temperatures and weather "
                      "patterns",
    "biodiversity": "the variety of all living things on Earth",
    "ecosystem": "a community of living organisms interacting with their "
                 "environment",
    "photosynthesis": "the process plants use to convert sunlight into food",
    "mitosis": "cell division that produces two identical daughter cells",
    "meiosis": "cell division that produces gametes like sperm and egg cells",
    "osmosis": "the movement of water through a semipermeable membrane",
    "inertia": "the tendency of an object to resist changes in its state "
               "of motion",
    "momentum": "the product of an object's mass and velocity",
    "centripetal force": "a force that keeps an object moving in a circular path",
    "electromagnetic spectrum": "the range of all electromagnetic radiation "
                                "from radio waves to gamma rays",
    "frequency": "the number of wave cycles that pass a point per second",
    "decibel": "a unit used to measure the intensity of sound",
}

PEOPLE = {
    "einstein": ("Albert Einstein, the father of modern physics, developed "
                 "the theory of relativity and won the Nobel Prize in 1921, "
                 "sir."),
    "newton": ("Isaac Newton formulated the laws of motion and gravity, "
               "sir."),
    "tesla": ("Nikola Tesla pioneered alternating current electricity, "
              "sir."),
    "edison": ("Thomas Edison invented the practical light bulb and founded "
               "General Electric, sir."),
    "da vinci": ("Leonardo da Vinci was a painter, inventor, and scientist, "
                 "famous for the Mona Lisa, sir."),
    "shakespeare": ("William Shakespeare wrote about 37 plays including "
                    "Hamlet and Romeo and Juliet, sir."),
    "gandhi": ("Mahatma Gandhi led India's independence movement through "
               "nonviolent resistance, sir."),
    "turing": ("Alan Turing is considered the father of computer science "
               "and AI, sir."),
    "jobs": ("Steve Jobs co-founded Apple and shaped the modern smartphone "
             "era, sir."),
    "gates": ("Bill Gates co-founded Microsoft and later became a "
              "philanthropist, sir."),
    "musk": ("Elon Musk founded Tesla, SpaceX, and works on AI and "
             "neurotech, sir."),
    "curie": ("Marie Curie discovered radium and won two Nobel Prizes, "
              "sir."),
    "hawking": ("Stephen Hawking was a physicist who studied black holes "
                "and cosmology, sir."),
    "darwin": ("Charles Darwin proposed the theory of evolution by natural "
               "selection, sir."),
    "socrates": ("Socrates was a Greek philosopher famous for questioning "
                 "everything, sir."),
    "kalam": ("A. P. J. Abdul Kalam was an Indian scientist and the "
              "11th President of India, sir."),
    "raman": ("C. V. Raman won the Nobel Prize for the scattering of light "
              "named after him, sir."),
    "tagore": ("Rabindranath Tagore was a poet who won the Nobel Prize for "
               "Gitanjali, sir."),
    "nobel": ("Alfred Nobel invented dynamite and founded the Nobel Prizes, "
              "sir."),
    "feynman": ("Richard Feynman was a Nobel-winning physicist known for "
                "his work on quantum electrodynamics, sir."),
    "planck": ("Max Planck founded quantum theory and won the Nobel Prize "
               "in 1918, sir."),
    "bohr": ("Niels Bohr explained atomic structure and won the Nobel Prize "
             "in 1922, sir."),
    "dirac": ("Paul Dirac predicted antimatter and won the Nobel Prize, sir."),
    "faraday": ("Michael Faraday discovered electromagnetic induction, "
                "sir."),
    "maxwell": ("James Clerk Maxwell unified electricity and magnetism into "
                "electromagnetism, sir."),
    "pascal": ("Blaise Pascal invented an early mechanical calculator and "
               "contributed to probability theory, sir."),
    "euler": ("Leonhard Euler made groundbreaking contributions to "
              "mathematics and physics, sir."),
    "gauss": ("Carl Gauss was a mathematician who made contributions to "
              "number theory and statistics, sir."),
    "napoleon": ("Napoleon Bonaparte was a French military leader and "
                 "emperor who reshaped Europe, sir."),
    "lincoln": ("Abraham Lincoln was the 16th US president who abolished "
                "slavery, sir."),
    "churchill": ("Winston Churchill led Britain through World War II and "
                  "won the Nobel Prize in Literature, sir."),
    "mandela": ("Nelson Mandela fought apartheid and became South Africa's "
                "first Black president, sir."),
    "mlk": ("Martin Luther King Jr. led the American civil rights movement "
            "with nonviolent protest, sir."),
    "obama": ("Barack Obama was the 44th US president and the first "
              "African American to hold the office, sir."),
    "beethoven": ("Ludwig van Beethoven composed nine symphonies even after "
                  "going deaf, sir."),
    "mozart": ("Wolfgang Amadeus Mozart was a musical prodigy who composed "
               "over 600 works, sir."),
    "michael jordan": ("Michael Jordan is considered the greatest basketball "
                       "player of all time, sir."),
    "sachin tendulkar": ("Sachin Tendulkar is widely regarded as the "
                         "greatest cricketer of all time, sir."),
    "messi": ("Lionel Messi is an Argentine footballer considered one of "
              "the greatest ever, sir."),
    "ronaldo": ("Cristiano Ronaldo is a Portuguese footballer and one of "
                "the all-time top scorers, sir."),
    "virat kohli": ("Virat Kohli is one of the most celebrated cricket "
                    "batsmen in history, sir."),
    "neil armstrong": ("Neil Armstrong was the first person to walk on the "
                       "Moon in 1969, sir."),
    "amelia earhart": ("Amelia Earhart was the first woman to fly solo "
                       "across the Atlantic Ocean, sir."),
    "bill bryson": ("Bill Bryson is a popular author known for humorous "
                    "travel and science writing, sir."),
    "jane austen": ("Jane Austen wrote classic novels like Pride and "
                    "Prejudice, sir."),
    "tolkien": ("J. R. R. Tolkien wrote The Lord of the Rings and "
                "created entire languages for his world, sir."),
    "orwell": ("George Orwell wrote 1984 and Animal Farm, warning about "
               "totalitarianism, sir."),
    "bram stoker": ("Bram Stoker wrote Dracula and helped define the "
                    "vampire genre, sir."),
    "lee kuan yew": ("Lee Kuan Yew was the founding father of modern "
                     "Singapore, sir."),
    "sundar pichai": ("Sundar Pichai is the CEO of Alphabet and Google, "
                      "sir."),
    "satya nadella": ("Satya Nadella is the CEO of Microsoft who "
                      "transformed its culture, sir."),
    "jeff bezos": ("Jeff Bezos founded Amazon and Blue Origin, sir."),
    "mark zuckerberg": ("Mark Zuckerberg co-founded and runs Meta, "
                        "sir."),
    "sam altman": ("Sam Altman is the CEO of OpenAI and a leading figure "
                   "in the AI industry, sir."),
    "oppenheimer": ("J. Robert Oppenheimer led the Manhattan Project that "
                    "built the first atomic bomb, sir."),
    "ada lovelace": ("Ada Lovelace wrote the first computer algorithm in "
                     "the 1840s, sir."),
    "grace hopper": ("Grace Hopper invented the first compiler and "
                     "helped create COBOL, sir."),
    "linus torvalds": ("Linus Torvalds created Linux and Git, two of the "
                       "most important tools in software, sir."),
    "tim berners-lee": ("Tim Berners-lee invented the World Wide Web in "
                        "1989, sir."),
}

EVENTS = {
    "big bang": "the universe began about 13.8 billion years ago, sir.",
    "world war 2": "World War II lasted from 1939 to 1945, sir.",
    "world war 1": "World War I lasted from 1914 to 1918, sir.",
    "cold war": "the Cold War lasted from 1947 to 1991, sir.",
    "first moon landing": "Apollo 11 landed on the Moon on July 20, 1969, "
                          "sir.",
    "internet created": "the internet's foundations were laid in the late "
                        "1960s with ARPANET, sir.",
    "first computer": "ENIAC, one of the first electronic computers, ran in "
                      "1945, sir.",
    "industrial revolution": "the Industrial Revolution began in Britain "
                             "around 1760, sir.",
    "french revolution": "the French Revolution began in 1789, sir.",
    "american revolution": "the American Revolution began in 1775, sir.",
    "indian independence": "India gained independence on August 15, 1947, "
                           "sir.",
    "fall of berlin wall": "the Berlin Wall fell on November 9, 1989, sir.",
    "covid pandemic": "COVID-19 became a global pandemic in early 2020, "
                      "sir.",
    "smartphone invented": "the first iPhone launched in 2007, sir.",
    "ai boom": "modern AI took off after ChatGPT launched in November 2022, "
               "sir.",
    "moon landing": "Apollo 11 landed on the Moon on July 20, 1969, sir.",
    "hubble telescope": "the Hubble Space Telescope launched in 1990 and "
                        "revolutionized astronomy, sir.",
    "world wide web invented": "Tim Berners-Lee invented the World Wide Web "
                               "in 1989, sir.",
    "first cell phone call": "the first handheld cell phone call was made "
                             "in 1973 by Martin Cooper, sir.",
    "manhattan project": "the secret US project during WWII that developed "
                         "the first atomic bomb, sir.",
    "hiroshima": "the US dropped the first atomic bomb on Hiroshima on "
                 "August 6, 1945, sir.",
    "fall of berlin wall": "the Berlin Wall fell on November 9, 1989, "
                           "symbolizing the end of the Cold War, sir.",
    "indian independence": "India gained independence from Britain on "
                           "August 15, 1947, sir.",
    "chinese revolution": "the Chinese Communist Revolution succeeded in "
                          "1949, sir.",
    "russian revolution": "the Russian Revolution of 1917 led to the "
                          "formation of the Soviet Union, sir.",
    "civil rights act": "the US Civil Rights Act was signed in 1964, sir.",
    "womens suffrage": "women gained the right to vote in the US in 1920 "
                       "with the 19th Amendment, sir.",
    "end of apartheid": "apartheid officially ended in South Africa in "
                        "1994, sir.",
    "brexit": "the United Kingdom voted to leave the European Union in "
              "2016 and officially exited in 2020, sir.",
    "september 11": "the September 11 attacks in 2001 changed global "
                    "security forever, sir.",
    "tsunami 2004": "the 2004 Indian Ocean tsunami killed over 230,000 "
                    "people, sir.",
    "chernobyl": "the Chernobyl nuclear disaster occurred on April 26, "
                 "1986 in Ukraine, sir.",
    "hiv aids discovered": "HIV was identified as the cause of AIDS in "
                           "1983, sir.",
    "dna structure discovered": "Watson and Crick discovered the double "
                                "helix structure of DNA in 1953, sir.",
    "penicillin discovered": "Alexander Fleming discovered penicillin in "
                             "1928, sir.",
    "first flight": "the Wright brothers made the first powered flight on "
                    "December 17, 1903, sir.",
    "telephone invented": "Alexander Graham Bell patented the telephone in "
                          "1876, sir.",
    "printing press": "Johannes Gutenberg invented the printing press "
                      "around 1440, sir.",
    "television invented": "the first electronic television was demonstrated "
                           "by Philo Farnsworth in 1927, sir.",
    "first satellite": "Sputnik 1, the first artificial satellite, was "
                       "launched by the Soviet Union in 1957, sir.",
    "space station": "the International Space Station has been continuously "
                     "inhabited since November 2000, sir.",
    "columbus discovered america": "Christopher Columbus reached the "
                                   "Americas in 1492, sir.",
    "magna carta": "the Magna Carta was signed in 1215, limiting the "
                   "power of the English king, sir.",
    "renaissance": "the Renaissance began in Italy around the 14th century, "
                   "reviving art and science, sir.",
    "black death": "the Black Death killed about one-third of Europe's "
                   "population in the 14th century, sir.",
    "golden age of islam": "the Islamic Golden Age from the 8th to 14th "
                           "century advanced science and mathematics, sir.",
    "covid pandemic": "COVID-19 became a global pandemic in early 2020, "
                      "sir.",
    "online education boom": "the pandemic in 2020 accelerated remote "
                             "learning worldwide, sir.",
    "spacex reusable rocket": "SpaceX successfully landed a reusable rocket "
                              "in 2015, revolutionizing space travel, sir.",
    "first image of a black hole": "the first image of a black hole was "
                                   "captured in 2019, sir.",
    "deep blue defeats kasparov": "IBM's Deep Blue defeated chess champion "
                                  "Garry Kasparov in 1997, sir.",
    "alphago defeats": "DeepMind's AlphaGo defeated world Go champion "
                       "Lee Sedol in 2016, sir.",
    "titanic sank": "the RMS Titanic sank on April 15, 1912, sir.",
}

SYNONYMS = {
    "happy": ["glad", "joyful", "cheerful", "delighted", "content"],
    "sad": ["unhappy", "sorrowful", "gloomy", "melancholy"],
    "big": ["large", "huge", "enormous", "massive", "gigantic"],
    "small": ["little", "tiny", "miniature", "compact", "petite"],
    "good": ["excellent", "great", "fine", "superb", "wonderful"],
    "bad": ["poor", "awful", "terrible", "terrible", "dreadful"],
    "fast": ["quick", "rapid", "swift", "speedy"],
    "slow": ["gradual", "sluggish", "leisurely", "unhurried"],
    "smart": ["intelligent", "clever", "brilliant", "bright", "sharp"],
    "funny": ["humorous", "amusing", "comical", "witty", "hilarious"],
    "beautiful": ["pretty", "lovely", "gorgeous", "stunning", "attractive"],
    "strong": ["powerful", "robust", "sturdy", "tough"],
    "weak": ["feeble", "frail", "fragile", "delicate"],
    "easy": ["simple", "effortless", "straightforward", "uncomplicated"],
    "difficult": ["hard", "tough", "challenging", "demanding", "arduous"],
    "important": ["significant", "crucial", "vital", "essential", "key"],
    "interesting": ["fascinating", "engaging", "captivating", "compelling"],
    "rich": ["wealthy", "affluent", "prosperous", "well-off"],
    "poor": ["needy", "impoverished", "destitute"],
    "angry": ["mad", "furious", "irritated", "annoyed", "livid"],
    "tired": ["exhausted", "weary", "drained", "fatigued"],
    "brave": ["courageous", "fearless", "bold", "valiant"],
    "quiet": ["silent", "calm", "peaceful", "hushed"],
    "loud": ["noisy", "boisterous", "deafening"],
    "nice": ["pleasant", "kind", "agreeable", "friendly"],
}

ANTONYMS = {
    "happy": ["sad", "unhappy", "miserable"],
    "big": ["small", "tiny", "little"],
    "fast": ["slow", "sluggish"],
    "hot": ["cold", "cool", "chilly"],
    "cold": ["hot", "warm", "boiling"],
    "easy": ["difficult", "hard", "tough"],
    "strong": ["weak", "feeble", "fragile"],
    "light": ["dark", "heavy"],
    "dark": ["light", "bright"],
    "rich": ["poor", "needy"],
    "poor": ["rich", "wealthy"],
    "good": ["bad", "evil", "poor"],
    "bad": ["good", "excellent", "virtuous"],
    "up": ["down"], "down": ["up"],
    "open": ["closed", "shut"], "closed": ["open"],
    "win": ["lose", "losing"], "lose": ["win", "winning"],
    "love": ["hate", "hatred"], "hate": ["love"],
    "begin": ["end", "finish"], "end": ["begin", "start"],
    "increase": ["decrease", "reduce"], "decrease": ["increase"],
    "ancient": ["modern", "new"], "modern": ["ancient", "old"],
}

HOWTO = {
    "study": "break work into 25-minute focus blocks with 5-minute breaks, "
             "teach back what you learn, and test yourself often, sir.",
    "sleep better": "keep a fixed bedtime, avoid screens an hour before "
                    "sleep, and keep your room cool and dark, sir.",
    "save money": "pay yourself first, track every expense, and use the "
                  "50-30-20 rule, sir.",
    "be productive": "plan your top three tasks each morning and start with "
                     "the hardest one, sir.",
    "learn a language": "practice 15 minutes daily, learn the top 100 "
                        "words, and speak from day one, sir.",
    "lose weight": "eat in a small calorie deficit, prioritize protein and "
                   "vegetables, and walk daily, sir.",
    "gain muscle": "train each muscle twice a week, eat enough protein, "
                   "and sleep 7-9 hours, sir.",
    "code": "pick one language, build tiny projects, read others' code, "
            "and debug with print statements, sir.",
    "interview": "research the company, practice your stories, and "
                 "prepare questions to ask them, sir.",
    "write better": "write a messy first draft fast, then edit; read it "
                    "aloud to catch awkward lines, sir.",
    "negotiate": "aim higher than you expect, let the other side speak "
                 "first, and be ready to walk away, sir.",
    "meditate": "sit comfortably, focus on your breath for five minutes, "
                "and gently return when your mind wanders, sir.",
    "tie a tie": "place the wide end on the right and long, cross it over "
                 "the narrow end, wrap it behind and across the front, "
                 "tuck it up and down through the knot, then tighten, sir.",
    "make coffee": "use 1 to 2 tablespoons of ground coffee per 6 ounces "
                   "of water, brew at 195 to 205 degrees Fahrenheit, sir.",
    "cook rice": "rinse the rice, use a 1 to 1.5 water-to-rice ratio, "
                 "bring to a boil, then cover and simmer for 15 minutes, sir.",
    "boil an egg": "place eggs in cold water, bring to a boil, then cover "
                   "and remove from heat; let sit 9 to 12 minutes, sir.",
    "make tea": "boil water, steep a tea bag or loose leaves for 3 to 5 "
                "minutes, then remove and add milk or sweetener to taste, sir.",
    "do a push-up": "place hands shoulder-width apart, keep your body "
                    "straight, lower your chest to the floor and push "
                    "back up, sir.",
    "do a squat": "stand with feet shoulder-width apart, push hips back "
                  "and lower until thighs are parallel to the floor, then "
                  "stand back up, sir.",
    "plank": "rest on your forearms and toes, keep your body in a straight "
             "line from head to heels, and hold for 30 to 60 seconds, sir.",
    "stretch": "hold each stretch for 20 to 30 seconds without bouncing, "
               "breathe deeply, and never stretch to the point of pain, sir.",
    "build a resume": "start with a strong summary, list experience in "
                      "reverse order, highlight skills and achievements, "
                      "and keep it to one page, sir.",
    "write an email": "use a clear subject line, greet politely, state "
                      "your purpose in the first sentence, and close "
                      "with a call to action, sir.",
    "manage time": "use the Eisenhower matrix to prioritize tasks by "
                   "urgency and importance, and batch similar tasks "
                   "together, sir.",
    "make a budget": "track income and expenses, allocate 50 percent to "
                     "needs, 30 percent to wants, and 20 percent to "
                     "savings, sir.",
    "invest": "start early, diversify your portfolio, invest consistently, "
              "keep fees low, and never invest money you cannot afford "
              "to lose, sir.",
    "cook pasta": "use plenty of salted boiling water, cook until al dente, "
                  "reserve some pasta water, and toss with your sauce, sir.",
    "bake a cake": "preheat the oven, cream butter and sugar, add eggs one "
                   "at a time, fold in flour gently, and bake at 350 "
                   "degrees Fahrenheit, sir.",
    "make an omelette": "beat two or three eggs with salt and pepper, pour "
                        "into a buttered non-stick pan over medium heat, "
                        "add fillings, and fold when set, sir.",
    "clean a room": "start by decluttering, dust from top to bottom, vacuum "
                    "last, and put things back where they belong, sir.",
    "do laundry": "sort by color and fabric, use the right detergent and "
                  "water temperature, and dry on low heat to prevent "
                  "shrinkage, sir.",
    "take good notes": "write key ideas in your own words, use headings "
                       "and bullet points, and review within 24 hours, sir.",
    "give a presentation": "start with a hook, structure with a clear "
                           "beginning middle and end, use visuals, and "
                           "practice beforehand, sir.",
    "learn to code": "start with a beginner-friendly language like Python, "
                     "build small projects, practice daily, and join "
                     "online communities, sir.",
    "set goals": "make goals specific, measurable, achievable, relevant, "
                 "and time-bound using the SMART framework, sir.",
    "wake up early": "set a consistent bedtime, avoid screens before sleep, "
                     "place your alarm across the room, and have a "
                     "morning routine, sir.",
}

WORDS_OF_DAY = [
    "serendipity (finding something good without looking for it)",
    "ephemeral (lasting for a very short time)",
    "ubiquitous (present everywhere)",
    "meticulous (very careful and precise)",
    "resilient (able to recover quickly)",
    "eloquent (fluent and persuasive in speech)",
    "pragmatic (dealing with things sensibly)",
    "ambiguous (open to more than one interpretation)",
    "mellow (soft, relaxed, and pleasant)",
    "zephyr (a gentle breeze)",
    "luminous (bright and glowing)",
    "quintessential (the perfect example)",
    "voracious (having a huge appetite)",
    "melancholy (a deep, thoughtful sadness)",
    "effervescent (lively and enthusiastic)",
    "ineffable (too great to be described in words)",
]

RIDDLES = [
    ("What has keys but cannot open locks?", "A piano."),
    ("What gets wetter the more it dries?", "A towel."),
    ("What has a face and two hands but no arms or legs?", "A clock."),
    ("What has many teeth but cannot bite?", "A comb."),
    ("What goes up but never comes down?", "Your age."),
    ("The more you take, the more you leave behind. What are they?",
     "Footsteps."),
    ("What has one eye but cannot see?", "A needle."),
    ("What has ears but cannot hear?", "Corn."),
    ("I am not alive, but I grow. I do not breathe, but I need air. "
     "What am I?", "Fire."),
]

COMPUTER_FACTS = [
    "The first computer bug was an actual moth found in a relay in 1947.",
    "More than 90% of the world's currency has only ever existed on "
    "computers.",
    "The first 1GB hard drive weighed over 500 pounds.",
    "There are about 3 billion lines of code in the universe of software.",
    "CAPTCHA stands for Completely Automated Public Turing test to tell "
    "Computers and Humans Apart.",
    "The Apollo 11 guidance computer had less computing power than a "
    "modern calculator.",
    "Java and JavaScript have almost nothing in common despite the name.",
    "The first email was sent by Ray Tomlinson to himself in 1971.",
    "Qwerty keyboards were designed to slow typists down.",
]

FACTS = [
    "Honey never spoils; archaeologists have found 3,000-year-old pots "
    "of honey that are still edible.",
    "Octopuses have three hearts and blue blood.",
    "A day on Venus is longer than a year on Venus.",
    "Bananas are berries, but strawberries are not.",
    "The Eiffel Tower grows about 15 cm taller in summer due to heat "
    "expansion.",
    "Water can boil and freeze at the same time, a state called the "
    "triple point.",
    "Sharks existed before trees did.",
    "Your brain uses about 20% of your body's energy.",
    "There are more possible chess games than atoms in the observable "
    "universe.",
    "A single bolt of lightning carries enough energy to toast about "
    "100,000 slices of bread.",
]

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _after(cmd, *pats):
    for p in pats:
        m = re.search(p, cmd, re.I)
        if m:
            return cmd[m.end():].strip().strip(" .:;")
    return None


def _fmt(n):
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    return "{:,}".format(n)


def _find_file(name, budget=0.4):
    name = (name or "").strip().strip('"\' .')
    if not name:
        return None
    if name.startswith("~"):
        name = os.path.expanduser(name)
    if os.path.exists(name):
        return name
    base = os.path.basename(name)
    dirs = [os.getcwd(),
            os.path.expanduser("~/Desktop"),
            os.path.expanduser("~/Documents"),
            os.path.expanduser("~/Downloads"),
            os.path.expanduser("~")]
    seen = set()
    start = time.monotonic()
    for d in dirs:
        if not d or not os.path.isdir(d) or d in seen:
            continue
        seen.add(d)
        try:
            for root, _dirs, files in os.walk(d):
                if time.monotonic() - start > budget:
                    return None
                for f in files:
                    if f == base or (len(base) > 2 and base in f):
                        return os.path.join(root, f)
        except Exception:
            continue
    return None


def _resolve(path):
    path = (path or "").strip().strip('"\' .')
    if path.startswith("~"):
        path = os.path.expanduser(path)
    return path


FILE_EXT = {
    "pdf", "txt", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "py", "pyw",
    "js", "ts", "jsx", "tsx", "html", "htm", "css", "json", "csv", "md",
    "markdown", "jpg", "jpeg", "png", "gif", "svg", "webp", "bmp", "ico",
    "mp3", "wav", "mp4", "mov", "avi", "mkv", "zip", "tar", "gz", "rar",
    "7z", "sql", "db", "sqlite", "sh", "bash", "yaml", "yml", "toml", "ini",
    "cfg", "log", "cpp", "cc", "c", "h", "hpp", "java", "rb", "go", "rs",
    "php", "swift", "kt", "scala", "dart", "lua", "r", "pl", "ps1", "bat",
    "cmd", "exe", "app", "dmg", "pkg", "numbers", "pages", "key", "psd",
    "ai", "xd", "sketch", "ipynb", "pkl", "pickle", "jsonl", "ics", "vcf",
    "webloc", "epub", "mobi", "rtf", "odt", "ods", "odp",
}

TLD = {
    "com", "org", "net", "io", "gov", "edu", "co", "me", "dev", "app", "ai",
    "in", "uk", "us", "ca", "au", "de", "fr", "info", "biz", "xyz", "online",
    "site", "tech", "store", "blog", "news", "ru", "cn", "jp", "tv", "fm",
    "gg", "to", "pro",
}


def _looks_like_file(rest):
    r = (rest or "").strip().strip('"\' .')
    if not r:
        return False
    if "/" in r or r.startswith("~"):
        exp = os.path.expanduser(r)
        if os.path.exists(exp):
            return True
        m = re.search(r"\.([a-zA-Z0-9]{1,6})$", r)
        return bool(m and m.group(1).lower() not in TLD)
    m = re.search(r"\.([a-zA-Z0-9]{1,6})$", r)
    if m and m.group(1).lower() in FILE_EXT:
        return True
    return _find_file(r) is not None


def _is_explicit_file(rest):
    r = (rest or "").strip().strip('"\' .')
    if not r:
        return False
    if "/" in r or r.startswith("~"):
        exp = os.path.expanduser(r)
        if os.path.exists(exp):
            return True
        m = re.search(r"\.([a-zA-Z0-9]{1,6})$", r)
        return bool(m and m.group(1).lower() not in TLD)
    if os.path.exists(r):
        return True
    m = re.search(r"\.([a-zA-Z0-9]{1,6})$", r)
    return bool(m and m.group(1).lower() in FILE_EXT)


def _load_state():
    try:
        with open(MEMORY_FILE) as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_state(state):
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(state, f, indent=2)
        return True
    except Exception:
        return False


def _state_get(state, key):
    return state.setdefault(key, [])


def _say_list(items, label, numbered=False):
    if not items:
        return "Your %s list is empty, sir." % label
    parts = []
    for i, it in enumerate(items, 1):
        if isinstance(it, dict):
            t = it.get("text", "")
            if it.get("done"):
                t += " (done)"
            parts.append(("  %d. %s" % (i, t)) if numbered else t)
        else:
            parts.append(("  %d. %s" % (i, it)) if numbered else it)
    return "Your %s:\n%s" % (label, "\n".join(parts))


WORD2NUM = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "eleven": 11, "twelve": 12, "half": 0.5}


def _math_eval(text):
    t = " " + text.lower() + " "
    t = re.sub(r"\bx\b", "*", t)
    t = re.sub(r"\btimes\b", "*", t)
    t = re.sub(r"\bmultiplied by\b", "*", t)
    t = re.sub(r"\bplus\b|\band\b", "+", t)
    t = re.sub(r"\bminus\b|\bless\b", "-", t)
    t = re.sub(r"\bdivided by\b|\bover\b|\bper\b", "/", t)
    t = re.sub(r"\bpercent\b", "/100", t)
    for w, n in WORD2NUM.items():
        t = re.sub(r"\b%s\b" % w, str(n), t)
    t = re.sub(r"what is\b|whats\b|what's\b|calculate\b|compute\b|equals\b|"
               r"is\b|\bto the power of\b", "", t)
    t = t.replace("^", "**")
    t = re.sub(r"[^0-9+\-*/().%\s]", "", t)
    t = t.replace("(", "(").replace(")", ")")
    if not re.search(r"\d", t):
        return None
    try:
        expr = re.sub(r"\s+", "", t)
        if not expr or not re.fullmatch(r"[0-9+\-*/().]+", expr):
            return None
        return eval(expr, {"__builtins__": {}}, {})
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CODE TEMPLATES (used when the LLM is offline)
# ---------------------------------------------------------------------------

def _py_template(topic):
    name = "main"
    return ("# %s\n"
            "def main():\n"
            "    # TODO: implement %s\n"
            "    pass\n\n"
            "if __name__ == '__main__':\n"
            "    main()\n" % (topic or "Python script", topic or "the task"))


def _js_template(topic):
    return ("// %s\n"
            "function main() {\n"
            "  // TODO: implement %s\n"
            "}\n\n"
            "main();\n" % (topic or "JavaScript", topic or "the task"))


def _html_template(topic):
    t = topic or "My Page"
    return ("<!DOCTYPE html>\n"
            "<html lang=\"en\">\n"
            "<head>\n"
            "  <meta charset=\"UTF-8\">\n"
            "  <meta name=\"viewport\" content=\"width=device-width, "
            "initial-scale=1.0\">\n"
            "  <title>%s</title>\n"
            "  <style>\n"
            "    body { font-family: sans-serif; max-width: 800px; "
            "margin: 40px auto; padding: 0 20px; }\n"
            "  </style>\n"
            "</head>\n"
            "<body>\n"
            "  <h1>%s</h1>\n"
            "  <p>Start building here.</p>\n"
            "</body>\n"
            "</html>\n" % (t, t))


def _css_template(topic):
    return ("/* %s */\n"
            ":root { --primary: #2563eb; }\n"
            "body { margin: 0; font-family: system-ui, sans-serif; }\n"
            ".container { max-width: 960px; margin: 0 auto; padding: 24px; }\n"
            % (topic or "styles"))


def _sh_template(topic):
    return ("#!/usr/bin/env bash\n"
            "# %s\n"
            "set -euo pipefail\n\n"
            "echo \"Running...\"\n" % (topic or "shell script"))


def _sql_template(topic):
    return ("-- %s\n"
            "CREATE TABLE IF NOT EXISTS items (\n"
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "  name TEXT NOT NULL,\n"
            "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n"
            ");\n" % (topic or "SQL"))


LANG_EXT = {"python": "py", "py": "py", "javascript": "js", "js": "js",
            "typescript": "ts", "ts": "ts", "html": "html", "css": "css",
            "bash": "sh", "shell": "sh", "sql": "sql", "java": "java",
            "c": "c", "cpp": "cpp", "c++": "cpp", "go": "go", "rust": "rs",
            "ruby": "rb", "php": "php", "swift": "swift", "kotlin": "kt",
            "json": "json", "markdown": "md", "md": "md", "text": "txt",
            "txt": "txt"}

LANG_TEMPLATE = {
    "py": _py_template, "js": _js_template, "html": _html_template,
    "css": _css_template, "sh": _sh_template, "sql": _sql_template,
}

GIT_HELP = {
    "stage": "git add .",
    "stage files": "git add <file>",
    "commit": "git commit -m \"your message\"",
    "push": "git push origin <branch>",
    "pull": "git pull",
    "clone a repo": "git clone <url>",
    "check status": "git status",
    "see changes": "git diff",
    "make a branch": "git checkout -b <branch>",
    "switch branch": "git checkout <branch>",
    "merge": "git merge <branch>",
    "see log": "git log --oneline",
    "undo last commit": "git reset --soft HEAD~1",
    "discard changes": "git checkout -- .",
    "stash": "git stash",
    "apply stash": "git stash pop",
}

DOCKER_HELP = {
    "list running": "docker ps",
    "list all": "docker ps -a",
    "list images": "docker images",
    "run a container": "docker run <image>",
    "run detached": "docker run -d <image>",
    "build image": "docker build -t <name> .",
    "stop container": "docker stop <id>",
    "remove container": "docker rm <id>",
    "remove image": "docker rmi <image>",
    "logs": "docker logs <id>",
    "shell inside": "docker exec -it <id> sh",
    "pull image": "docker pull <image>",
}

BASH_HELP = {
    "list files": "ls -la",
    "change directory": "cd <path>",
    "find a file": "find . -name \"<name>\"",
    "search text": "grep -r \"<text>\" <path>",
    "zip a folder": "zip -r out.zip <folder>",
    "unzip": "unzip file.zip",
    "copy": "cp source destination",
    "move": "mv source destination",
    "delete": "rm <file>",
    "delete folder": "rm -rf <folder>",
    "see running processes": "ps aux | head",
    "kill process": "kill <pid>",
    "check disk": "df -h",
    "check memory": "vm_stat",
    "who is logged in": "who",
    "edit a file": "nano <file>",
}

BIG_O = {
    "loop": "O(n) - linear: the work grows with the input size",
    "nested loop": "O(n^2) - quadratic: two nested loops",
    "binary search": "O(log n) - logarithmic: halves the input each step",
    "hash lookup": "O(1) - constant: dictionary lookups",
    "merge sort": "O(n log n) - efficient for large lists",
    "bubble sort": "O(n^2) - slow on big inputs",
    "linear search": "O(n) - checks each item",
    "quick sort": "O(n log n) on average",
}

PYTHON_TRICKS = {
    "swap variables": "a, b = b, a",
    "reverse a string": "s[::-1]",
    "list comprehension": "[x * 2 for x in nums]",
    "read a file": "with open('f.txt') as f: data = f.read()",
    "write a file": "with open('f.txt', 'w') as f: f.write('hi')",
    "default dict": "from collections import defaultdict; d = defaultdict(int)",
    "count items": "from collections import Counter; Counter(items)",
    "merge dicts": "d = {**a, **b}",
    "random choice": "import random; random.choice(items)",
    "sleep": "import time; time.sleep(2)",
    "today's date": "import datetime; datetime.date.today()",
    "download a file": "import requests; r = requests.get(url)",
}

AIRPORT_CODES = {
    "new york (jfk)": "JFK", "new york (newark)": "EWR", "london heathrow": "LHR",
    "london gatwick": "LGW", "paris": "CDG", "tokyo narita": "NRT",
    "tokyo haneda": "HND", "delhi": "DEL", "mumbai": "BOM", "bangalore": "BLR",
    "hyderabad": "HYD", "chennai": "MAA", "kolkata": "CCU", "dubai": "DXB",
    "singapore": "SIN", "hong kong": "HKG", "beijing": "PEK", "shanghai": "PVG",
    "sydney": "SYD", "melbourne": "MEL", "frankfurt": "FRA", "amsterdam": "AMS",
    "munich": "MUC", "madrid": "MAD", "barcelona": "BCN", "rome": "FCO",
    "milan": "MXP", "istanbul": "IST", "doha": "DOH", "toronto": "YYZ",
    "vancouver": "YVR", "los angeles": "LAX", "san francisco": "SFO",
    "chicago": "ORD", "miami": "MIA", "atlanta": "ATL", "seattle": "SEA",
    "boston": "BOS", "washington": "IAD", "las vegas": "LAS", "denver": "DEN",
    "mexico city": "MEX", "sao paulo": "GRU", "buenos aires": "EZE",
    "cape town": "CPT", "nairobi": "NBO", "doha": "DOH",
}

PHONE_CODES = {
    "india": "+91", "usa": "+1", "united states": "+1", "uk": "+44",
    "france": "+33", "germany": "+49", "japan": "+81", "china": "+86",
    "australia": "+61", "canada": "+1", "brazil": "+55", "russia": "+7",
    "italy": "+39", "spain": "+34", "mexico": "+52", "south korea": "+82",
    "singapore": "+65", "uae": "+971", "saudi arabia": "+966", "egypt": "+20",
    "south africa": "+27", "nigeria": "+234", "kenya": "+254", "turkey": "+90",
    "indonesia": "+62", "thailand": "+66", "vietnam": "+84", "pakistan": "+92",
    "bangladesh": "+880", "sri lanka": "+94", "nepal": "+977", "netherlands": "+31",
    "sweden": "+46", "switzerland": "+41", "poland": "+48", "greece": "+30",
    "portugal": "+351", "ireland": "+353", "new zealand": "+64",
}

EMERGENCY = {
    "india": "112", "usa": "911", "united states": "911", "uk": "999",
    "france": "112", "germany": "112", "japan": "119", "china": "120",
    "australia": "000", "canada": "911", "brazil": "190", "russia": "112",
    "italy": "112", "spain": "112", "mexico": "911", "south korea": "119",
    "singapore": "995", "uae": "999", "saudi arabia": "911", "egypt": "122",
    "south africa": "10111", "nigeria": "112", "turkey": "112",
}

AREA_UNITS = {"square meter": 1.0, "square meters": 1.0, "sq m": 1.0,
              "m2": 1.0, "square foot": 0.092903, "square feet": 0.092903,
              "sq ft": 0.092903, "ft2": 0.092903, "square kilometer": 1e6,
              "square kilometers": 1e6, "km2": 1e6, "hectare": 10000.0,
              "hectares": 10000.0, "acre": 4046.86, "acres": 4046.86,
              "square yard": 0.836127, "square yards": 0.836127,
              "sq yd": 0.836127, "square mile": 2589988.11,
              "square miles": 2589988.11, "sq mi": 2589988.11,
              "square centimeter": 0.0001, "square centimeters": 0.0001,
              "sq cm": 0.0001, "square inch": 0.00064516,
              "square inches": 0.00064516, "sq in": 0.00064516}

VOLUME_UNITS = {"liter": 1.0, "liters": 1.0, "litre": 1.0, "litres": 1.0,
                "l": 1.0, "milliliter": 0.001, "milliliters": 0.001,
                "ml": 0.001, "gallon": 3.78541, "gallons": 3.78541,
                "gal": 3.78541, "quart": 0.946353, "quarts": 0.946353,
                "pint": 0.473176, "pints": 0.473176, "cup": 0.24, "cups": 0.24,
                "fluid ounce": 0.0295735, "fluid ounces": 0.0295735,
                "fl oz": 0.0295735, "cubic meter": 1000.0, "cubic meters": 1000.0,
                "cubic foot": 28.3168, "cubic feet": 28.3168,
                "tablespoon": 0.0147868, "tablespoons": 0.0147868,
                "teaspoon": 0.00492892, "teaspoons": 0.00492892}

PRESSURE_UNITS = {"pascal": 1.0, "pa": 1.0, "kilopascal": 1000.0,
                  "kpa": 1000.0, "bar": 100000.0, "psi": 6894.76,
                  "atmosphere": 101325.0, "atm": 101325.0,
                  "torr": 133.322, "mmhg": 133.322}

ENERGY_UNITS = {"joule": 1.0, "joules": 1.0, "j": 1.0, "kilojoule": 1000.0,
                "kilojoules": 1000.0, "kj": 1000.0, "calorie": 4.184,
                "calories": 4.184, "cal": 4.184, "kilocalorie": 4184.0,
                "kilocalories": 4184.0, "kcal": 4184.0, "watt hour": 3600.0,
                "watt hours": 3600.0, "wh": 3600.0, "kilowatt hour": 3600000.0,
                "kilowatt hours": 3600000.0, "kwh": 3600000.0}

POWER_UNITS = {"watt": 1.0, "watts": 1.0, "w": 1.0, "kilowatt": 1000.0,
               "kilowatts": 1000.0, "kw": 1000.0, "megawatt": 1e6,
               "megawatts": 1e6, "mw": 1e6, "horsepower": 745.7,
               "hp": 745.7}

ANGLE_UNITS = {"degree": 1.0, "degrees": 1.0, "deg": 1.0, "radian": 57.2958,
               "radians": 57.2958, "rad": 57.2958, "gradian": 0.9,
               "gradians": 0.9, "revolution": 360.0, "revolutions": 360.0,
               "turn": 360.0, "turns": 360.0}

ZODIAC = {("capricorn", 1, 19): "Capricorn",
          ("aquarius", 2, 18): "Aquarius",
          ("pisces", 3, 20): "Pisces",
          ("aries", 4, 19): "Aries",
          ("taurus", 5, 20): "Taurus",
          ("gemini", 6, 20): "Gemini",
          ("cancer", 7, 22): "Cancer",
          ("leo", 8, 22): "Leo",
          ("virgo", 9, 22): "Virgo",
          ("libra", 10, 22): "Libra",
          ("scorpio", 11, 21): "Scorpio",
          ("sagittarius", 12, 21): "Sagittarius"}


def _zodiac(month, day):
    for (_sname, m, d), sign in ZODIAC.items():
        if month == m and day <= d:
            return sign
    return "Sagittarius"


ZODIAC_PERSONALITY = {
    "aries": "bold, energetic, and love to lead, sir.",
    "taurus": "steady, loyal, and appreciate the good things, sir.",
    "gemini": "curious, witty, and love to communicate, sir.",
    "cancer": "intuitive, caring, and fiercely protective, sir.",
    "leo": "confident, generous, and love the spotlight, sir.",
    "virgo": "meticulous, practical, and always helpful, sir.",
    "libra": "charming, fair-minded, and love balance, sir.",
    "scorpio": "passionate, mysterious, and deeply loyal, sir.",
    "sagittarius": "adventurous, optimistic, and love freedom, sir.",
    "capricorn": "ambitious, disciplined, and dependable, sir.",
    "aquarius": "inventive, independent, and think big, sir.",
    "pisces": "dreamy, empathetic, and wonderfully creative, sir.",
}

COLOR_PALETTES = {
    "sunset": ["#ff7e67", "#ffb563", "#ffd166", "#06d6a0", "#073b4c"],
    "ocean": ["#003049", "#d62828", "#f77f00", "#fcbf49", "#eae2b7"],
    "forest": ["#1b4332", "#2d6a4f", "#40916c", "#52b788", "#95d5b2"],
    "midnight": ["#0f172a", "#1e293b", "#334155", "#475569", "#94a3b8"],
    "candy": ["#ef476f", "#f78c6b", "#ffd166", "#83d483", "#06d6a0"],
    "royal": ["#4a0e4e", "#8338ec", "#9d4edd", "#c77dff", "#e0aaff"],
}

WORKOUTS = {
    "push": ["10 push-ups", "20 jumping jacks", "10 diamond push-ups",
             "30-sec plank", "15 incline push-ups"],
    "pull": ["5 pull-ups or 15-sec hangs", "15 superman rows",
             "20 band rows", "10 chin-ups or holds", "20 reverse flies"],
    "legs": ["20 squats", "15 lunges each side", "20 glute bridges",
             "15 calf raises", "30-sec wall sit"],
    "core": ["30-sec plank", "20 crunches", "15 leg raises", "20 bicycle "
             "crunches", "30-sec side plank each side"],
    "full body": ["10 burpees", "15 squats", "10 push-ups", "15 lunges",
                  "30-sec plank"],
}

HASHTAG_BASE = ["#tech", "#coding", "#daily", "#vibes", "#goals", "#life",
                "#work", "#fun", "#mood", "#insta", "#fyp", "#motivation",
                "#family", "#fitness", "#travel", "#food", "#art", "#news"]

USERS = ["wolf", "tiger", "falcon", "phoenix", "pixel", "nova", "ranger",
         "storm", "sage", "echo", "quantum", "zen", "cobra", "falcon",
         "orbit", "drift", "forge", "ember", "lumen", "axiom"]


def _llm_reply(app, prompt):
    r = _llm(app, prompt)
    if not r:
        return "I could not reach my language model for that, sir."
    return r


# ---------------------------------------------------------------------------
# REGISTRATION
# ---------------------------------------------------------------------------

def register_extra(brain):
    def reg(name, patterns, fn=None, priority=False):
        if fn is None and isinstance(patterns, str):
            # Simple form: reg("trigger phrase", "response text")
            _reply = patterns
            patterns = [name]

            def fn(app, cmd):
                return _reply

        def detect(cmd):
            for p in patterns:
                if re.search(r"\b" + re.escape(p) + r"\b", cmd, re.I):
                    return {"cmd": cmd}
            return None

        def execute(app, ctx):
            try:
                return fn(app, ctx["cmd"])
            except Exception as e:
                print("SKILL ERROR %s: %r" % (name, e))
                return None
        brain.register(name, detect, execute, priority=priority)

    def reg_re(name, pattern, fn, priority=False):
        def detect(cmd):
            if re.search(pattern, cmd, re.I):
                return {"cmd": cmd}
            return None

        def execute(app, ctx):
            try:
                return fn(app, ctx["cmd"])
            except Exception as e:
                print("SKILL ERROR %s: %r" % (name, e))
                return None
        brain.register(name, detect, execute, priority=priority)

    def reg_llm(name, patterns, prompt, priority=False):
        def fn(app, cmd):
            return _llm_reply(app, prompt(cmd))
        reg(name, patterns, fn, priority=priority)

    def reg_num(name, patterns, fn, priority=False):
        def fn2(app, cmd):
            nums = _nums(cmd)
            if not nums:
                return None
            return fn(app, nums)
        reg(name, patterns, fn2, priority=priority)

    def reg_fn(name, detect, fn, priority=False):
        def wrapped_detect(cmd):
            result = detect(cmd)
            if result is True:
                return {"cmd": cmd, "m": cmd}
            if isinstance(result, dict):
                if "cmd" not in result:
                    result["cmd"] = cmd
                if "m" not in result:
                    result["m"] = cmd
                return result
            return result
        def execute(app, ctx):
            try:
                return fn(app, ctx["cmd"])
            except Exception as e:
                print("SKILL ERROR %s: %r" % (name, e))
                return None
        brain.register(name, wrapped_detect, execute, priority=priority)

    # ---- A. PRIORITY FILE / DESKTOP SKILLS (run before main.py intents) ----

    def _open_file_fn(app, cmd):
        rest = cmd
        rest = re.sub(r"^(?:please\s+)?(?:open|open up|launch|start)\s*",
                      "", rest, flags=re.I)
        rest = re.sub(r"^(?:the|a|an|file)\s+", "", rest, flags=re.I).strip()
        rest = rest.strip('"\' .')
        if not rest or not _looks_like_file(rest):
            return None
        found = _find_file(rest) or _resolve(rest)
        if found and os.path.exists(found):
            if open_path(found):
                return "Opening %s, sir." % os.path.basename(found)
        return None

    def _open_file_detect(cmd):
        m = re.match(r"^(?:please\s+)?(?:open|open up|launch|start)\b(.*)$",
                     cmd, re.I)
        if not m:
            return None
        rest = m.group(1).strip()
        if not rest:
            return None
        if _is_explicit_file(rest):
            return {"cmd": cmd}
        return None

    def _read_file_fn(app, cmd):
        rest = cmd
        for p in [r"\b(?:read|show me|display|open)\s+(?:the\s+)?(?:file|"
                  r"contents of)\s+", r"\b(?:read|show me|display)\s+",
                  r"\bshow\s+(?:me\s+)?(?:the\s+)?contents\s+of\s+",
                  r"\bwhat does\s+(?:the\s+)?(?:file\s+)?",
                  r"\bwhat is in\s+(?:the\s+)?(?:file\s+)?"]:
            m = re.search(p, rest, re.I)
            if m:
                rest = rest[m.end():]
                break
        rest = rest.strip().strip('"\' .?')
        found = _find_file(rest)
        if not found:
            return "I could not find that file, sir."
        try:
            with open(found, encoding="utf-8", errors="replace") as f:
                content = f.read(3000)
        except Exception:
            return "I could not read that file, sir."
        lines = content.splitlines()
        if len(lines) > 25:
            body = "\n".join(lines[:25])
            return ("Here are the first 25 lines of %s:\n%s"
                    % (os.path.basename(found), body))
        return content or "That file is empty, sir."

    def _read_file_detect(cmd):
        if re.search(r"\b(?:read|show me|display)\s+(?:the\s+)?(?:file\s+)?"
                     r"[^\s]+\.\w+\b", cmd) or \
           re.search(r"\bwhat (?:does|is in)\s+(?:the\s+)?(?:file\s+)?"
                     r"[^\s]+\b", cmd) or \
           re.search(r"\b(?:read|show me)\s+(?:the\s+)?(?:contents of\s+)?"
                     r"(?:file\s+)?", cmd):
            rest = re.sub(r"^(?:please\s+)?(?:read|show me|display)\s*"
                          r"(?:the\s+)?(?:file\s+)?(?:contents of\s+)?",
                          "", cmd, flags=re.I).strip().strip('"\' .?')
            if rest and _is_explicit_file(rest):
                return {"cmd": cmd}
        return None

    def _find_target(cmd):
        rest = re.sub(r"^(?:please\s+)?(?:write|save|put|append|add|create|"
                      r"make|write down|store)\s*", "", cmd, flags=re.I)
        rest = re.sub(r"\b(?:that|this|down)\s*", "", rest, flags=re.I).strip()
        m = re.search(r"\b(?:to|into|in|at|as|as\s+file)\s+([^\n]+)$",
                      rest, re.I)
        if m:
            target = m.group(1).strip().strip('"\' .')
            content = rest[:m.start()].strip()
            return content, target
        return None, None

    def _write_file_fn(app, cmd):
        content, target = _find_target(cmd)
        if content is None or not target:
            return None
        path = _resolve(target)
        if not os.path.isabs(path):
            path = os.path.join(os.getcwd(), path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return "Saved to %s, sir." % path
        except Exception:
            return "I could not write that file, sir."

    def _write_file_detect(cmd):
        if re.search(r"\b(?:write|save|put)\s+.*\b(?:to|into|in)\s+.*\.\w+",
                     cmd, re.I):
            content, target = _find_target(cmd)
            if content and target:
                return {"cmd": cmd}
        return None

    def _append_file_fn(app, cmd):
        content, target = _find_target(cmd)
        if content is None or not target:
            return None
        path = _resolve(target)
        if not os.path.isabs(path):
            path = os.path.join(os.getcwd(), path)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n" + content)
            return "Appended to %s, sir." % os.path.basename(path)
        except Exception:
            return "I could not append to that file, sir."

    def _append_file_detect(cmd):
        if re.search(r"\b(?:append|add)\s+.*\b(?:to)\s+.*\.\w+", cmd, re.I):
            content, target = _find_target(cmd)
            if content and target:
                return {"cmd": cmd}
        return None

    def _create_file_fn(app, cmd):
        m = re.search(r"\b(?:create|make|new)\s+(?:a\s+|an\s+)?(?:empty\s+)?"
                      r"file\s+(?:called|named|as|:)?\s*(.+)$", cmd, re.I)
        if not m:
            m = re.search(r"\b(?:create|make)\s+(?:a\s+|an\s+)?(?:file)\s*"
                          r"(?:called|named|as|:)?\s*(.+)$", cmd, re.I)
        if not m:
            return None
        name = m.group(1).strip().strip('"\' .')
        path = _resolve(name)
        if not os.path.isabs(path):
            path = os.path.join(os.getcwd(), path)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if not os.path.exists(path):
                open(path, "w").close()
            return "Created %s, sir." % os.path.basename(path)
        except Exception:
            return "I could not create that file, sir."

    def _create_file_detect(cmd):
        if re.search(r"\b(?:create|make)\s+(?:a\s+|an\s+)?file\b", cmd, re.I):
            m = re.search(r"\b(?:create|make)\s+(?:a\s+|an\s+)?(?:file)\s*"
                          r"(?:called|named|as|:)?\s*(.+)$", cmd, re.I)
            return {"cmd": cmd} if m else None
        return None

    def _create_folder_fn(app, cmd):
        m = re.search(r"\b(?:create|make|new)\s+(?:a\s+|an\s+)?(?:folder|"
                      r"directory)\s+(?:called|named|as|:)?\s*(.+)$",
                      cmd, re.I)
        if not m:
            return None
        name = m.group(1).strip().strip('"\' .')
        path = _resolve(name)
        if not os.path.isabs(path):
            path = os.path.join(os.getcwd(), path)
        try:
            os.makedirs(path, exist_ok=True)
            return "Created the folder %s, sir." % os.path.basename(path)
        except Exception:
            return "I could not create that folder, sir."

    def _create_folder_detect(cmd):
        if re.search(r"\b(?:create|make)\s+(?:a\s+|an\s+)?(?:folder|"
                     r"directory)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _delete_file_fn(app, cmd):
        m = re.search(r"\b(?:delete|remove|erase|trash)\s+(?:the\s+)?"
                      r"(?:file\s+)?(.+)$", cmd, re.I)
        if not m:
            return None
        found = _find_file(m.group(1).strip().strip('"\' .'))
        if not found:
            return "I could not find that file to delete, sir."
        try:
            os.remove(found)
            return "Deleted %s, sir." % os.path.basename(found)
        except Exception:
            return "I could not delete that file, sir."

    def _delete_file_detect(cmd):
        if re.search(r"\b(?:delete|remove|erase|trash)\s+(?:the\s+)?"
                     r"file\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _delete_folder_fn(app, cmd):
        m = re.search(r"\b(?:delete|remove|erase)\s+(?:the\s+)?(?:folder|"
                      r"directory)\s+(?:called|named)?\s*(.+)$", cmd, re.I)
        if not m:
            return None
        name = _resolve(m.group(1).strip().strip('"\' .'))
        if not os.path.exists(name) and os.path.sep not in name:
            name = os.path.join(os.getcwd(), name)
        if not os.path.isdir(name):
            return "I could not find that folder, sir."
        try:
            shutil.rmtree(name)
            return "Deleted the folder, sir."
        except Exception:
            return "I could not delete that folder, sir."

    def _delete_folder_detect(cmd):
        if re.search(r"\b(?:delete|remove|erase)\s+(?:the\s+)?(?:folder|"
                     r"directory)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _rename_file_fn(app, cmd):
        m = re.search(r"\brename\s+(?:file\s+)?(.+?)\s+(?:to|as)\s+(.+)$",
                      cmd, re.I)
        if not m:
            return None
        old = _find_file(m.group(1).strip().strip('"\' .'))
        if not old:
            return "I could not find the file to rename, sir."
        new = m.group(2).strip().strip('"\' .')
        new_path = os.path.join(os.path.dirname(old), new)
        try:
            os.rename(old, new_path)
            return "Renamed to %s, sir." % new
        except Exception:
            return "I could not rename that file, sir."

    def _rename_file_detect(cmd):
        if re.search(r"\brename\s+", cmd, re.I) and \
                re.search(r"\b(?:to|as)\s+", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _copy_file_fn(app, cmd):
        m = re.search(r"\bcopy\s+(?:file\s+)?(.+?)\s+(?:to|into|as)\s+(.+)$",
                      cmd, re.I)
        if not m:
            return None
        src = _find_file(m.group(1).strip().strip('"\' .'))
        if not src:
            return "I could not find the file to copy, sir."
        dst = _resolve(m.group(2).strip().strip('"\' .'))
        try:
            if os.path.isdir(dst) or dst.endswith(os.sep):
                os.makedirs(dst, exist_ok=True)
                shutil.copy2(src, dst)
            else:
                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                shutil.copy2(src, dst)
            return "Copied %s, sir." % os.path.basename(src)
        except Exception:
            return "I could not copy that file, sir."

    def _copy_file_detect(cmd):
        if re.search(r"\bcopy\s+(?:the\s+)?(?:file\s+)?", cmd, re.I) and \
                re.search(r"\b(?:to|into|as)\s+", cmd, re.I) and \
                re.search(r"\.\w+\b", cmd):
            return {"cmd": cmd}
        return None

    def _move_file_fn(app, cmd):
        m = re.search(r"\bmove\s+(?:file\s+)?(.+?)\s+(?:to|into|as)\s+(.+)$",
                      cmd, re.I)
        if not m:
            return None
        src = _find_file(m.group(1).strip().strip('"\' .'))
        if not src:
            return "I could not find the file to move, sir."
        dst = _resolve(m.group(2).strip().strip('"\' .'))
        try:
            if os.path.isdir(dst) or dst.endswith(os.sep):
                os.makedirs(dst, exist_ok=True)
                shutil.move(src, os.path.join(dst, os.path.basename(src)))
            else:
                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                shutil.move(src, dst)
            return "Moved %s, sir." % os.path.basename(src)
        except Exception:
            return "I could not move that file, sir."

    def _move_file_detect(cmd):
        if re.search(r"\bmove\s+(?:the\s+)?(?:file\s+)?", cmd, re.I) and \
                re.search(r"\b(?:to|into|as)\s+", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _list_files_fn(app, cmd):
        folder = None
        m = re.search(r"\b(?:in|of|inside)\s+(?:the\s+)?(.+)$", cmd, re.I)
        if m:
            name = m.group(1).strip().strip('"\' .')
            cand = _find_file(name) or _resolve(name)
            if cand and os.path.isdir(cand):
                folder = cand
        if folder is None:
            for key in FOLDER_PATHS:
                if re.search(r"\b%s\b" % key, cmd, re.I):
                    folder = os.path.expanduser(FOLDER_PATHS[key])
                    break
        if folder is None:
            folder = os.getcwd()
        try:
            names = sorted(os.listdir(folder))
        except Exception:
            return "I could not list that folder, sir."
        files = [n for n in names if not n.startswith(".")]
        if not files:
            return "That folder is empty, sir."
        shown = files[:30]
        body = "\n".join("  " + n for n in shown)
        more = " and %d more" % (len(files) - 30) if len(files) > 30 else ""
        return "Contents of %s:\n%s%s" % (folder, body, more)

    def _list_files_detect(cmd):
        if re.search(r"\b(?:list|show|see)\s+(?:me\s+)?(?:the\s+)?(?:files|"
                     r"contents)\b", cmd, re.I) or \
           re.search(r"\bwhat files\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _find_file_fn(app, cmd):
        rest = re.sub(r"^(?:please\s+)?(?:find|locate|search for|where is|"
                      r"where's|where are)\s*(?:the\s+)?(?:file\s+)?",
                      "", cmd, flags=re.I).strip().strip('"\' .?')
        if not rest:
            return None
        found = _find_file(rest)
        if found:
            return "I found it at %s, sir." % found
        return "I could not find a file named %s, sir." % rest

    def _find_file_detect(cmd):
        if re.search(r"\b(?:find|locate|where is|where's|where are)\s+"
                     r"(?:the\s+)?(?:file\s+)?", cmd, re.I):
            rest = re.sub(r"^(?:please\s+)?(?:find|locate|where "
                          r"is|where's|where are)\s*(?:the\s+)?(?:file\s+)?",
                          "", cmd, flags=re.I).strip().strip('"\' .?')
            return {"cmd": cmd} if rest else None
        return None

    def _file_info_fn(app, cmd):
        rest = cmd
        for p in [r"\b(?:size|info|details|info about|details of)\s+(?:of\s+)?"
                  r"(?:the\s+)?(?:file\s+)?",
                  r"\bhow big is\s+(?:the\s+)?(?:file\s+)?"]:
            m = re.search(p, rest, re.I)
            if m:
                rest = rest[m.end():]
                break
        rest = rest.strip().strip('"\' .?')
        if not rest:
            return None
        found = _find_file(rest)
        if not found:
            return "I could not find that file, sir."
        st = os.stat(found)
        size = st.st_size
        if size >= 1048576:
            sz = "%.2f MB" % (size / 1048576)
        elif size >= 1024:
            sz = "%.2f KB" % (size / 1024)
        else:
            sz = "%d bytes" % size
        modified = datetime.datetime.fromtimestamp(st.st_mtime).strftime(
            "%b %d, %Y %I:%M %p")
        return ("%s is %s and was last modified on %s, sir."
                % (os.path.basename(found), sz, modified))

    def _file_info_detect(cmd):
        if re.search(r"\b(?:size|info|details|how big|info about|details of)"
                     r"\b", cmd, re.I) and \
                re.search(r"\b(?:file|\.\w+)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _open_with_app_fn(app, cmd):
        m = re.search(r"\bopen\s+(.+?)\s+(?:with|using|in)\s+([a-z ]+)$",
                      cmd, re.I)
        if not m:
            return None
        target = _find_file(m.group(1).strip().strip('"\' .'))
        if not target:
            return None
        app_name = m.group(2).strip()
        try:
            subprocess.run(["open", "-a", app_name, target],
                           capture_output=True)
            return "Opening %s with %s, sir." % (
                os.path.basename(target), app_name)
        except Exception:
            return "I could not open it with that app, sir."

    def _open_with_app_detect(cmd):
        if re.search(r"\bopen\s+.+\s+(?:with|using|in)\s+[a-z ]+$",
                     cmd, re.I):
            return {"cmd": cmd}
        return None

    def _recent_files_fn(app, cmd):
        try:
            paths = []
            for d in (os.path.expanduser("~/Desktop"),
                      os.path.expanduser("~/Documents"),
                      os.path.expanduser("~/Downloads")):
                if not os.path.isdir(d):
                    continue
                for f in os.listdir(d):
                    p = os.path.join(d, f)
                    if os.path.isfile(p) and not f.startswith("."):
                        paths.append((os.path.getmtime(p), p))
            paths.sort(reverse=True)
            recent = ["  " + os.path.basename(p) for _, p in paths[:8]]
            return ("Your most recent files:\n%s"
                    % "\n".join(recent)) if recent else \
                "No recent files found, sir."
        except Exception:
            return "I could not scan for recent files, sir."

    def _recent_files_detect(cmd):
        if re.search(r"\b(?:recent|latest|last opened|newest)\s+files?\b",
                     cmd, re.I):
            return {"cmd": cmd}
        return None

    def _open_home_fn(app, cmd):
        if open_path(os.path.expanduser("~")):
            return "Opening your home folder, sir."
        return "I could not open the home folder, sir."

    def _open_home_detect(cmd):
        if re.search(r"\bopen\s+(?:the\s+)?home\s+(?:folder|directory)?\b"
                     r"|home folder|my home", cmd, re.I):
            return {"cmd": cmd}
        return None

    reg_fn("open_file", _open_file_detect, _open_file_fn,
                   priority=True)
    reg_fn("read_file", _read_file_detect, _read_file_fn,
                   priority=True)
    reg_fn("write_file", _write_file_detect, _write_file_fn,
                   priority=True)
    reg_fn("append_file", _append_file_detect, _append_file_fn,
                   priority=True)
    reg_fn("create_file", _create_file_detect, _create_file_fn,
                   priority=True)
    reg_fn("create_folder", _create_folder_detect,
                   _create_folder_fn, priority=True)
    reg_fn("delete_file", _delete_file_detect, _delete_file_fn,
                   priority=True)
    reg_fn("delete_folder", _delete_folder_detect,
                   _delete_folder_fn, priority=True)
    reg_fn("rename_file", _rename_file_detect, _rename_file_fn,
                   priority=True)
    reg_fn("copy_file", _copy_file_detect, _copy_file_fn,
                   priority=True)
    reg_fn("move_file", _move_file_detect, _move_file_fn,
                   priority=True)
    reg_fn("list_files", _list_files_detect, _list_files_fn,
                   priority=True)
    reg_fn("find_file", _find_file_detect, _find_file_fn,
                   priority=True)
    reg_fn("file_info", _file_info_detect, _file_info_fn,
                   priority=True)
    reg_fn("open_with_app", _open_with_app_detect,
                   _open_with_app_fn, priority=True)
    reg_fn("recent_files", _recent_files_detect, _recent_files_fn,
                   priority=True)
    reg_fn("open_home", _open_home_detect, _open_home_fn,
                   priority=True)

    # ---- B. CODING SKILLS ----

    def _code_to_file_fn(app, cmd):
        langs = sorted(LANG_EXT, key=len, reverse=True)
        lang = None
        for l in langs:
            if re.search(r"\b" + re.escape(l) + r"\b", cmd, re.I):
                lang = l
                break
        if not lang:
            return None
        ext = LANG_EXT[lang]
        m = re.search(r"\b(?:to|into|in|at|as|save it as|called|named)\s+"
                      r"([^\n]+?\.%s)\b" % ext, cmd, re.I)
        target = None
        if m:
            target = m.group(1).strip().strip('"\' .')
        topic = re.sub(r"^(?:please\s+)?(?:write|create|generate|code|make|"
                       r"build)\s*(?:a|an|the)?\s*%s\s*(?:script|program|"
                       r"code|file|function|app|page|file)?\s*"
                       % re.escape(lang), "", cmd, flags=re.I)
        topic = re.sub(r"\b(?:that|to|which)\b.*$", "", topic, flags=re.I)
        topic = re.sub(r"\b(?:to|into|in|at|as|save it as|called|named)"
                       r"\s+[\w./~-]+\.\w+$", "", topic)
        topic = topic.strip().strip(" .:;-")
        if not target:
            name = re.sub(r"\W+", "_", topic.lower())[:20] or "code"
            target = os.path.join(os.getcwd(), "%s.%s" % (name, ext))
        else:
            target = _resolve(target)
            if not os.path.isabs(target):
                target = os.path.join(os.getcwd(), target)
        prompt = ("Write production-ready %s code for this task: %s. "
                  "Output ONLY the code, no explanations, no markdown "
                  "fences." % (lang, topic or cmd))
        code = _llm(app, prompt)
        if not code:
            tpl = LANG_TEMPLATE.get(ext)
            code = tpl(topic) if tpl else ("# %s\n# TODO: implement %s\n"
                                           % (lang, topic or cmd))
        try:
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(code)
            open_path(os.path.dirname(target) or ".")
            return ("Wrote %s code to %s, sir." % (lang, target))
        except Exception:
            return "I could not write the code file, sir."

    def _code_to_file_detect(cmd):
        for l in LANG_EXT:
            if re.search(r"\b(?:write|create|generate|code|make|build)\s+"
                         r"(?:a|an|the)?\s*%s\b" % re.escape(l), cmd, re.I):
                return {"cmd": cmd}
        return None

    def _generate_code_fn(app, cmd):
        m = re.search(r"\b(?:generate|write|create|give me|show me)\s+"
                      r"(?:a|an|the)?\s*(.+?)\s+(?:code|snippet|function|"
                      r"script)\b(.*)$", cmd, re.I)
        topic = cmd
        if m:
            topic = (m.group(1) + " " + m.group(2)).strip()
        topic = re.sub(r"\b(?:for|about)\s*$", "", topic).strip()
        return _llm_reply(app, "Write a short, useful code snippet for: "
                               "%s. Include a one-line comment explaining it."
                               % topic)

    def _generate_code_detect(cmd):
        if re.search(r"\b(?:airport|country|postal|zip|area)\s+code\b",
                     cmd, re.I):
            return None
        if re.search(r"\b(?:generate|write|give me|show me)\s+.+\bcode\b",
                     cmd, re.I) or \
           re.search(r"\bcode\s+(?:for|to|that)\b", cmd, re.I):
            if not _code_to_file_detect(cmd):
                return {"cmd": cmd}
        return None

    def _explain_code_fn(app, cmd):
        code = _after(cmd, r"\bexplain\s+(?:this|the)?\s*(?:code|script)?"
                      r"\s*[:]?\s*", r"\bexplain\s+this\s+code\b")
        if not code:
            return None
        return _llm_reply(app, "Explain this code simply, line by line: "
                               "%s" % code)

    def _explain_code_detect(cmd):
        if re.search(r"\bexplain\s+(?:this|the)?\s*(?:code|script)\b",
                     cmd, re.I):
            code = _after(cmd, r"\bexplain\s+(?:this|the)?\s*(?:code|script)"
                          r"?\s*[:]?\s*", r"\bexplain\s+this\s+code\b")
            return {"cmd": cmd} if code else None
        return None

    def _debug_code_fn(app, cmd):
        code = _after(cmd, r"\b(?:debug|fix|why doesn't|why is this broke)"
                      r"\s+(?:this|my|the)?\s*(?:code|script)?\s*[:]?\s*")
        if not code:
            return None
        return _llm_reply(app, "Find the bug in this code and give the "
                               "fixed version with a short explanation: "
                               "%s" % code)

    def _debug_code_detect(cmd):
        if re.search(r"\b(?:debug|fix)\s+(?:this|my|the)?\s*(?:code|"
                     r"script)\b", cmd, re.I):
            code = _after(cmd, r"\b(?:debug|fix)\s+(?:this|my|the)?\s*"
                         r"(?:code|script)?\s*[:]?")
            return {"cmd": cmd} if code else None
        return None

    def _refactor_code_fn(app, cmd):
        code = _after(cmd, r"\brefactor\s+(?:this|the)?\s*(?:code|script)?"
                      r"\s*[:]?\s*")
        if not code:
            return None
        return _llm_reply(app, "Refactor this code to be cleaner and more "
                               "readable. Explain the improvements: "
                               "%s" % code)

    def _refactor_code_detect(cmd):
        if re.search(r"\brefactor\b", cmd, re.I):
            code = _after(cmd, r"\brefactor\s+(?:this|the)?\s*"
                         r"(?:code|script)?\s*[:]?")
            return {"cmd": cmd} if code else None
        return None

    def _regex_builder_fn(app, cmd):
        desc = _after(cmd, r"\bregex\s+(?:for|to match|to find|to extract)\s*",
                      r"\bregular expression\s+(?:for|to match|to find)\s*")
        if not desc:
            return None
        words = re.findall(r"\b[a-zA-Z]{3,}\b", desc)
        if not words:
            return None
        pat = r"\b" + r"\s+".join(re.escape(w) for w in words[:5])
        return ("A regex for '%s' could look like: %s\n"
                "Try it on regex101.com, sir." % (desc, pat))

    def _regex_builder_detect(cmd):
        if re.search(r"\bregex\b|\bregular expression\b", cmd, re.I) and \
                re.search(r"\b(?:for|to match|to find|to extract)\b",
                          cmd, re.I):
            return {"cmd": cmd}
        return None

    def _regex_test_fn(app, cmd):
        m = re.search(r"\b(?:does|test)\s+['\"]?(.+?)['\"]?\s+(?:match|"
                      r"fit)\s+(?:regex\s+)?['\"]?(.+?)['\"]?$", cmd, re.I)
        if not m:
            return None
        text, pat = m.group(1), m.group(2)
        try:
            if re.search(pat, text):
                return "Yes, it matches, sir."
            return "No, it does not match, sir."
        except Exception:
            return "That does not look like a valid regex, sir."

    def _regex_test_detect(cmd):
        if re.search(r"\b(?:does|test)\s+.+\s+(?:match|fit)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _json_validate_fn(app, cmd):
        data = _after(cmd, r"\bvalidate\s+(?:this\s+)?json\s*[:]?\s*",
                      r"\bvalid json\b\s*[:]?\s*", r"\bjson valid\b\s*"
                      r"[:]?\s*", r"\bjson\s*[:]?\s*")
        if not data:
            return None
        try:
            json.loads(data)
            return "That is valid JSON, sir."
        except Exception as e:
            return "That JSON is invalid: %s, sir." % e

    def _json_validate_detect(cmd):
        if re.search(r"\b(?:validate|is this valid|valid)\s+(?:this\s+)?"
                     r"json\b|\bjson\s+(?:valid|validate)\b", cmd, re.I):
            data = _after(cmd, r"\bvalidate\s+(?:this\s+)?json\s*[:]?\s*",
                          r"\b(?:valid|is)\s+(?:this\s+)?json\b\s*[:]?\s*")
            return {"cmd": cmd} if data else None
        return None

    def _json_format_fn(app, cmd):
        data = _after(cmd, r"\bformat\s+(?:this\s+)?json\s*[:]?\s*",
                      r"\bpretty[- ]print\s+(?:this\s+)?json\b\s*[:]?\s*")
        if not data:
            return None
        try:
            parsed = json.loads(data)
            return json.dumps(parsed, indent=2)
        except Exception:
            return "That is not valid JSON, sir."

    def _json_format_detect(cmd):
        if re.search(r"\b(?:format|pretty-print|pretty print)\s+(?:this\s+)?"
                     r"json\b", cmd, re.I):
            data = _after(cmd, r"\bformat\s+(?:this\s+)?json\s*[:]?\s*",
                          r"\bpretty[- ]print\s+(?:this\s+)?json\b\s*[:]?\s*")
            return {"cmd": cmd} if data else None
        return None

    def _sql_table_fn(app, cmd):
        m = re.search(r"\b(?:sql\s+)?create\s+(?:a\s+)?table\s+(?:for|"
                      r"called|named)?\s*(.+)$", cmd, re.I)
        subject = m.group(1).strip() if m else "items"
        return ("Here is a starting table, sir:\n"
                "CREATE TABLE %s (\n"
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
                "  name TEXT NOT NULL,\n"
                "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n);"
                % re.sub(r"\W+", "_", subject.lower()))

    def _sql_table_detect(cmd):
        if re.search(r"\b(?:sql\s+)?create\s+(?:a\s+)?table\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _sql_query_fn(app, cmd):
        q = _after(cmd, r"\bsql\s+query\s+(?:for|to)\s*",
                   r"\b(?:write|give me)\s+sql\s+(?:query\s+)?(?:for|to)\s*")
        if not q:
            q = _after(cmd, r"\bquery\s+(?:for|to)\s*")
        if not q:
            return None
        return _llm_reply(app, "Write an SQL query for: %s. Output only "
                               "the SQL." % q)

    def _sql_query_detect(cmd):
        if re.search(r"\bsql\s+query\b|\bquery\s+(?:for|to)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _git_help_fn(app, cmd):
        q = re.sub(r"\b(?:git|github)\b", "", cmd)
        q = q.replace("?", "").strip()
        for k, v in GIT_HELP.items():
            if k in q or q in k or all(w in q for w in k.split()[:2]):
                return "To %s: %s, sir." % (k, v)
        return ("Here are the essentials, sir:\n%s"
                % "\n".join("  " + v for v in GIT_HELP.values()))

    def _git_help_detect(cmd):
        if re.search(r"\bgit\b|\bgithub\b", cmd, re.I) and \
                re.search(r"\b(?:command|how|help|commit|push|pull|clone|"
                          r"branch|merge|undo|stash)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _docker_help_fn(app, cmd):
        q = cmd.lower()
        for k, v in DOCKER_HELP.items():
            if k in q or (len(k.split()) == 1 and k in q):
                return "To %s: %s, sir." % (k, v)
        return ("Common docker commands, sir:\n%s"
                % "\n".join("  " + v for v in DOCKER_HELP.values()))

    def _docker_help_detect(cmd):
        if re.search(r"\bdocker\b", cmd, re.I) and \
                re.search(r"\b(?:command|how|run|build|stop|container|"
                          r"image|list|logs)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _curl_help_fn(app, cmd):
        return ("Useful curl commands, sir:\n"
                "  GET a page:        curl https://example.com\n"
                "  GET JSON API:      curl https://api.example.com/data\n"
                "  POST JSON:         curl -X POST -H \"Content-Type: "
                "application/json\" -d '{\"k\":\"v\"}' URL\n"
                "  Download a file:   curl -O https://example.com/file.zip\n"
                "  Headers only:      curl -I https://example.com")

    def _curl_help_detect(cmd):
        if re.search(r"\bcurl\b", cmd, re.I) and \
                re.search(r"\b(?:command|how|download|post|get|api)\b",
                          cmd, re.I):
            return {"cmd": cmd}
        return None

    def _bash_help_fn(app, cmd):
        q = cmd.lower()
        for k, v in BASH_HELP.items():
            if k in q or (len(k.split()) == 1 and k in q):
                return "To %s: %s, sir." % (k, v)
        return ("Some handy bash commands, sir:\n%s"
                % "\n".join("  " + v for v in BASH_HELP.values()))

    def _bash_help_detect(cmd):
        if re.search(r"\b(?:bash|terminal|command line|shell)\b", cmd,
                     re.I) and \
                re.search(r"\b(?:command|how|list|find|search|zip|unzip|"
                          r"copy|move|delete|process)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _big_o_fn(app, cmd):
        q = cmd.lower()
        for k, v in BIG_O.items():
            if k in q:
                return "%s is %s, sir." % (k.title(), v)
        return "Ask me about a specific operation, like binary search, sir."

    def _big_o_detect(cmd):
        if re.search(r"\btime complexity\b|\bbig o\b|\bhow fast is\b|\b"
                     r"o\(n", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _python_trick_fn(app, cmd):
        q = cmd.lower()
        for k, v in PYTHON_TRICKS.items():
            if k in q:
                return "In Python, to %s: %s, sir." % (k, v)
        return None

    def _python_trick_detect(cmd):
        if re.search(r"\bpython\b", cmd, re.I) and \
                re.search(r"\b(?:trick|snippet|how|way to)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    reg_llm("pseudocode", ["pseudocode", "pseudo code"],
            lambda c: "Write pseudocode for: %s. Keep it simple." % c)
    reg_llm("api_docs", ["api docs", "api documentation", "how to use the "
                         "api"],
            lambda c: "Summarize how to use the API for: %s." % c)

    # ---- C. RESEARCH / KNOWLEDGE SKILLS ----

    def _capital_fn(app, cmd):
        c = _country(cmd, "capital")
        if c:
            return "The capital of %s is %s, sir." % (c[0], c[1])
        c = _after(cmd, r"\bcapital of\s*", r"\bcapital city of\s*")
        if c:
            return None if not c else _llm_reply(
                app, "What is the capital of %s? One short sentence."
                     % c.strip())
        return None

    def _country(cmd, kind):
        for name, (cap, pop, cur, lang, cont) in COUNTRIES.items():
            if re.search(r"\b" + re.escape(name) + r"\b", cmd, re.I):
                return (name, cap, pop, cur, lang, cont)
        return None

    def _capital_detect(cmd):
        if re.search(r"\bcapital\s+(?:city\s+)?of\b", cmd, re.I):
            c = _country(cmd, "capital")
            return {"cmd": cmd} if c else None
        return None

    def _population_fn(app, cmd):
        c = _country(cmd, "population")
        if c:
            return "The population of %s is about %s, sir." % (c[0], c[2])
        return None

    def _population_detect(cmd):
        if re.search(r"\bpopulation\b|\bhow many people\b", cmd, re.I):
            c = _country(cmd, "population")
            return {"cmd": cmd} if c else None
        return None

    def _currency_fn(app, cmd):
        c = _country(cmd, "currency")
        if c:
            return "The currency of %s is the %s, sir." % (c[0], c[3])
        return None

    def _currency_detect2(cmd):
        if re.search(r"\bcurrency of\b|\bwhat currency\b", cmd, re.I):
            c = _country(cmd, "currency")
            return {"cmd": cmd} if c else None
        return None

    def _language_fn(app, cmd):
        c = _country(cmd, "language")
        if c:
            return "The main language of %s is %s, sir." % (c[0], c[4])
        return None

    def _language_detect(cmd):
        if re.search(r"\blanguage\s+(?:spoken\s+)?in\b|\bwhat language\b",
                     cmd, re.I):
            c = _country(cmd, "language")
            return {"cmd": cmd} if c else None
        return None

    def _continent_fn(app, cmd):
        c = _country(cmd, "continent")
        if c:
            return "%s is in %s, sir." % (c[0].title(), c[5])
        return None

    def _continent_detect(cmd):
        if re.search(r"\bcontinent of\b|\bwhich continent\b", cmd, re.I):
            c = _country(cmd, "continent")
            return {"cmd": cmd} if c else None
        return None

    def _element_fn(app, cmd):
        m = re.search(r"\b(?:element|atomic number|atomic weight|info on|"
                      r"facts about)\s+(?:of\s+)?(.+)$", cmd, re.I)
        key = m.group(1).strip().strip(" .?") if m else None
        if not key:
            return None
        key = key.lower()
        for name, (sym, num, mass, fact) in ELEMENTS.items():
            if name in key or sym.lower() in key.split():
                return ("%s (symbol %s, atomic number %d) is %s, sir."
                        % (name.title(), sym, num, fact))
        return None

    def _element_detect(cmd):
        if re.search(r"\b(?:element|atomic number|atomic weight|info on|"
                     r"facts about)\b", cmd, re.I):
            m = re.search(r"\b(?:element|atomic number|atomic weight|info "
                          r"on|facts about)\s+(?:of\s+)?(.+)$", cmd, re.I)
            key = m.group(1).strip().strip(" .?") if m else ""
            if any(e in key.lower() for e in ELEMENTS):
                return {"cmd": cmd}
        return None

    def _planet_fn(app, cmd):
        for name, (desc, dia, moons, fact) in PLANETS.items():
            if re.search(r"\b" + name + r"\b", cmd, re.I):
                return ("%s is %s, about %d km wide, with %d moon%s. "
                        "Fun fact: %s, sir."
                        % (name.title(), desc, dia, moons,
                           "s" if moons != 1 else "", fact))
        return None

    def _planet_detect(cmd):
        for name in PLANETS:
            if re.search(r"\b(?:planet|tell me about|facts about|info on)\s+"
                         r"%s\b|\b%s\s+planet\b" % (name, name), cmd, re.I):
                return {"cmd": cmd}
        return None

    def _animal_fn(app, cmd):
        for name, fact in ANIMALS.items():
            if re.search(r"\b(?:facts? about|about|tell me about)\s+"
                         r"%s\b" % name, cmd, re.I) or \
                    re.search(r"\banimal\s+fact\b.*%s" % name, cmd, re.I):
                return fact
        if re.search(r"\banimal fact\b", cmd, re.I):
            return random.choice(list(ANIMALS.values()))
        return None

    def _animal_detect(cmd):
        if re.search(r"\banimal\b", cmd, re.I) or \
                any(re.search(r"\b" + a + r"\b", cmd, re.I)
                    for a in ANIMALS):
            return {"cmd": cmd}
        return None

    def _food_fn(app, cmd):
        for name, fact in FOODS.items():
            if re.search(r"\b(?:calories? in|how many calories)\s+(?:an?\s+|"
                         r"the\s+)?%s\b|about\s+%s\b" % (name, name),
                         cmd, re.I):
                return fact
        return None

    def _food_detect(cmd):
        if re.search(r"\bcalories?\b", cmd, re.I):
            for name in FOODS:
                if re.search(r"\b%s\b" % name, cmd, re.I):
                    return {"cmd": cmd}
        return None

    def _caffeine_fn(app, cmd):
        for name, fact in CAFFEINE.items():
            if re.search(r"\b" + name + r"\b", cmd, re.I):
                return fact
        return None

    def _caffeine_detect(cmd):
        if re.search(r"\bcaffeine\b", cmd, re.I):
            for name in CAFFEINE:
                if re.search(r"\b" + name + r"\b", cmd, re.I):
                    return {"cmd": cmd}
        return None

    def _define_fn(app, cmd):
        m = re.search(r"\b(?:define|what does|what is the meaning of|meaning "
                      r"of)\s+(.+?)\s*$", cmd, re.I)
        if not m:
            return None
        word = m.group(1).strip().strip(" .?")
        for concept, text in CONCEPTS.items():
            if concept in word.lower():
                return "That is %s, sir." % text
        return _llm_reply(app, "Define '%s' in one or two simple sentences."
                               % word)

    def _define_detect(cmd):
        if re.search(r"\b(?:define|what does|meaning of|what is the meaning "
                     r"of)\b", cmd, re.I) and \
                not re.search(r"\bdefine quantum\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _synonym_fn(app, cmd):
        w = _after(cmd, r"\bsynonym\s+for\s*", r"\banother word for\s*")
        if not w:
            return None
        w = w.strip().strip(" .?")
        for k, v in SYNONYMS.items():
            if k in w:
                return "Some synonyms for %s are: %s, sir." % (k,
                        ", ".join(v[:4]))
        return _llm_reply(app, "Give four synonyms for '%s' in a list."
                               % w)

    def _synonym_detect(cmd):
        if re.search(r"\bsynonym\b|\banother word for\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _antonym_fn(app, cmd):
        w = _after(cmd, r"\bantonym\s+for\s*", r"\bopposite of\s*",
                   r"\bother word for\s*")
        if not w:
            return None
        w = w.strip().strip(" .?")
        for k, v in ANTONYMS.items():
            if k in w:
                return "The opposite of %s is %s, sir." % (k,
                        ", ".join(v[:2]))
        return _llm_reply(app, "What is the antonym of '%s'?" % w)

    def _antonym_detect(cmd):
        if re.search(r"\bantonym\b|\bopposite of\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _people_fn(app, cmd):
        m = re.search(r"\bwho\s+is\s+(.+?)\s*$", cmd, re.I)
        if not m:
            return None
        key = m.group(1).strip().strip(" .?")
        for name, fact in PEOPLE.items():
            if name in key.lower():
                return fact
        return _llm_reply(app, "Who is %s? Answer in one or two sentences."
                               % key)

    def _people_detect(cmd):
        if re.search(r"\bwho\s+is\s+", cmd, re.I):
            key = re.sub(r"^.*\bwho\s+is\s+", "", cmd, flags=re.I).strip()
            if any(p in key.lower() for p in PEOPLE):
                return {"cmd": cmd}
        return None

    def _when_fn(app, cmd):
        m = re.search(r"\bwhen\s+(?:did|was|is)\s+(.+?)\s*$", cmd, re.I)
        if not m:
            return None
        key = m.group(1).strip().strip(" .?")
        for k, v in EVENTS.items():
            if k in key.lower():
                return "The %s: %s" % (k.title(), v)
        return _llm_reply(app, "When did %s happen? Answer in one short "
                               "sentence." % key)

    def _when_detect(cmd):
        if re.search(r"\bwhen\s+(?:did|was|is)\s+", cmd, re.I):
            key = re.sub(r"^.*\bwhen\s+(?:did|was|is)\s+", "", cmd,
                         flags=re.I).strip()
            if any(e in key.lower() for e in EVENTS):
                return {"cmd": cmd}
        return None

    def _today_history_fn(app, cmd):
        now = datetime.date.today()
        return ("A few things that happened on %s %d in history, sir:\n"
                "  - %s"
                % (now.strftime("%B"), now.day,
                   random.choice(list(EVENTS.values()))))

    def _today_history_detect(cmd):
        if re.search(r"\b(?:today|this day|this date)\s+in\s+history\b",
                     cmd, re.I):
            return {"cmd": cmd}
        return None

    def _word_day_fn(app, cmd):
        return ("Today's word: %s, sir." % random.choice(WORDS_OF_DAY))

    def _word_day_detect(cmd):
        if re.search(r"\bword of the day\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _random_fact_fn(app, cmd):
        topic = _after(cmd, r"\bfact about\s*", r"\bfact on\s*",
                       r"\babout\s*")
        if topic:
            return _llm_reply(app, "Give one interesting fact about %s, "
                                   "one short sentence." % topic)
        return random.choice(FACTS)

    def _random_fact_detect(cmd):
        if re.search(r"\bfact\b", cmd, re.I) and \
                re.search(r"\b(?:about|on|random)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    reg_llm("research", ["research", "do some research on", "find out "
                         "about", "look into"],
            lambda c: "Research: %s. Give a concise, useful summary with "
                      "key points." % re.sub(r"^(?:please\s+)?(?:research|"
                      r"do some research on|find out about|look into)\s*",
                      "", c, flags=re.I))
    reg_llm("news_summary", ["latest news", "what's in the news", "news "
                             "update", "news about", "today's news"],
            lambda c: "Give the latest news summary for: %s. 3 short "
                      "bullet points." % c)
    reg_llm("quote_search", ["quote about", "quotes about", "quote on",
                             "famous quote about"],
            lambda c: "Give a famous quote about %s with the author."
                      % re.sub(r"^.*\b(?:quote|quotes)\s+(?:about|on)\s*",
                               "", c, flags=re.I))

    # ---- D. PRODUCTIVITY / PLANNING SKILLS ----

    def _todo_add_fn(app, cmd):
        task = _after(cmd, r"\badd\s+(?:a\s+)?(?:todo|task|item|to-do)\s*"
                      r"(?:item)?\s+(?:to|for)\s+(?:my\s+)?(?:list\s*)?",
                      r"\b(?:add|note)\s+(?:this\s+)?(?:to|in)\s+(?:my\s+)?"
                      r"(?:todo|to-do|task|list)\s*:?\s*",
                      r"\b(?:todo|to-do|task|remember)\s*:\s*")
        if not task:
            m = re.search(r"\badd\s+(.+?)\s+to\s+(?:my\s+)?(?:todo|to-do|"
                          r"task)s?\s*(?:list)?\s*$", cmd, re.I)
            if m:
                task = m.group(1).strip().strip('"\'')
        if not task:
            return None
        state = _load_state()
        state.setdefault("todos", []).append({"text": task, "done": False})
        _save_state(state)
        return "Added to your to-do list, sir: %s" % task

    def _todo_add_detect(cmd):
        if re.search(r"\b(?:add|put)\s+.*\b(?:todo|to-do|task)\b",
                     cmd, re.I) or \
                re.search(r"\btodo\s*:|\btask\s*:", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _todo_show_fn(app, cmd):
        state = _load_state()
        items = _state_get(state, "todos")
        return _say_list(items, "to-do", numbered=True)

    def _todo_show_detect(cmd):
        if re.search(r"\b(?:show|list|view|what are|display)\s+(?:my\s+)?"
                     r"(?:todo|todos|to-do|tasks|task list)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _todo_remove_fn(app, cmd):
        idx = _after(cmd, r"\bremove\s+(?:todo|task|item)\s+#?\s*\d*",
                     r"\bdelete\s+(?:todo|task)\s+#?\s*\d*")
        state = _load_state()
        items = _state_get(state, "todos")
        nums = _int_nums(cmd)
        m = re.search(r"\b(?:remove|delete|cross off|finish|done|complete)\s+"
                      r"(?:todo|task|item)?\s*#?\s*(\d+)", cmd, re.I)
        if m:
            n = int(m.group(1))
            if 1 <= n <= len(items):
                removed = items.pop(n - 1)
                _save_state(state)
                return "Removed '%s' from your to-do list, sir." % \
                    removed.get("text")
        task = re.sub(r"^.*\b(?:remove|delete|done with|finish)\s+", "",
                      cmd, flags=re.I).strip().strip(" .?")
        for i, it in enumerate(items):
            if task and it.get("text", "").lower().startswith(task.lower()):
                items.pop(i)
                _save_state(state)
                return "Removed '%s' from your to-do list, sir." % task
        return "I could not find that task, sir."

    def _todo_remove_detect(cmd):
        if re.search(r"\b(?:remove|delete|cross off)\s+(?:(?:todo|to-do|"
                     r"task)s?|(?:item\s+)?#?\s*\d+)(?!.*\bshopping\b)",
                     cmd, re.I):
            return {"cmd": cmd}
        return None

    def _todo_done_fn(app, cmd):
        m = re.search(r"\b(?:mark|done|complete|finish|check off)\s+(?:todo|"
                      r"task|item)?\s*#?\s*(\d+)", cmd, re.I)
        state = _load_state()
        items = _state_get(state, "todos")
        if m:
            n = int(m.group(1))
            if 1 <= n <= len(items):
                items[n - 1]["done"] = True
                _save_state(state)
                return "Marked '%s' as done, sir." % items[n - 1]["text"]
        return None

    def _todo_done_detect(cmd):
        if re.search(r"\b(?:mark|done|complete|finish|check off)\s+(?:todo|"
                     r"task|item)?\s*#?\s*\d+", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _shopping_add_fn(app, cmd):
        m = re.search(r"\badd\s+(?:the\s+)?(?:item\s+)?([\w ]+?)\s+to\s+"
                      r"(?:my\s+)?shopping\s+list\s*$", cmd, re.I)
        if not m:
            return None
        item = m.group(1).strip()
        state = _load_state()
        state.setdefault("shopping", []).append(item)
        _save_state(state)
        return "Added %s to your shopping list, sir." % item

    def _shopping_add_detect(cmd):
        if re.search(r"\bshopping\s+list\b", cmd, re.I) and \
                re.search(r"\badd\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _shopping_show_fn(app, cmd):
        state = _load_state()
        return _say_list(_state_get(state, "shopping"), "shopping",
                         numbered=True)

    def _shopping_show_detect(cmd):
        if re.search(r"\b(?:show|list|what's on|display)\s+(?:my\s+)?"
                     r"shopping\s+list\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _shopping_remove_fn(app, cmd):
        m = re.search(r"\b(?:remove|delete)\s+(?:item\s+)?#?\s*(\d+)\s+"
                      r"(?:from\s+)?(?:my\s+)?shopping\s+list", cmd, re.I)
        state = _load_state()
        items = _state_get(state, "shopping")
        if m:
            n = int(m.group(1))
            if 1 <= n <= len(items):
                gone = items.pop(n - 1)
                _save_state(state)
                return "Removed %s from your shopping list, sir." % gone
        return None

    def _shopping_remove_detect(cmd):
        if re.search(r"\b(?:remove|delete)\b.*\bshopping\s+list\b",
                     cmd, re.I):
            return {"cmd": cmd}
        return None

    def _budget_add_fn(app, cmd):
        state = _load_state()
        nums = _nums(cmd)
        if not nums:
            return None
        amount = nums[0]
        if re.search(r"\bset\b|\bbudget is\b", cmd, re.I):
            state["budget"] = amount
        else:
            state["budget"] = state.get("budget", 0.0) + amount
        _save_state(state)
        return "Your budget is now %s, sir." % _fmt(state["budget"])

    def _budget_add_detect(cmd):
        if re.search(r"\bbudget\b", cmd, re.I) and \
                re.search(r"\b(?:add|set|increase|raise|raise my|my budget"
                          r" is)\b", cmd, re.I) and _nums(cmd):
            return {"cmd": cmd}
        return None

    def _budget_show_fn(app, cmd):
        state = _load_state()
        b = state.get("budget", 0.0)
        spent = sum(state.get("expenses", []))
        return ("Your budget is %s, and you have spent %s so far. "
                "Remaining: %s, sir."
                % (_fmt(b), _fmt(spent), _fmt(b - spent)))

    def _budget_show_detect(cmd):
        if re.search(r"\b(?:show|what is|view|check)\s+(?:my\s+)?budget\b",
                     cmd, re.I) or \
                re.search(r"\bhow much.*budget\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _expense_add_fn(app, cmd):
        nums = _nums(cmd)
        if not nums:
            return None
        amount = nums[0]
        what = re.sub(r"^.*\b(?:on|for)\s+", "", cmd, flags=re.I)
        what = re.sub(r"\b\d+(?:\.\d+)?\b", "", what).strip(" .")
        state = _load_state()
        state.setdefault("expenses", []).append(amount)
        _save_state(state)
        label = " for %s" % what if what else ""
        return "Logged an expense of %s%s, sir." % (_fmt(amount), label)

    def _expense_add_detect(cmd):
        if re.search(r"\b(?:expense|spent|spend|cost|costs?)\b", cmd,
                     re.I) and _nums(cmd):
            return {"cmd": cmd}
        return None

    def _expense_show_fn(app, cmd):
        state = _load_state()
        ex = state.get("expenses", [])
        if not ex:
            return "No expenses logged yet, sir."
        return ("Your expenses so far, sir:\n%s\nTotal: %s"
                % ("\n".join("  " + _fmt(x) for x in ex), _fmt(sum(ex))))

    def _expense_show_detect(cmd):
        if re.search(r"\b(?:show|view|what are)\s+(?:my\s+)?expenses?\b",
                     cmd, re.I) or \
                re.search(r"\bhow much.*spent\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _savings_add_fn(app, cmd):
        nums = _nums(cmd)
        if not nums:
            return None
        state = _load_state()
        state["savings"] = state.get("savings", 0.0) + nums[0]
        _save_state(state)
        return "Savings updated to %s, sir." % _fmt(state["savings"])

    def _savings_add_detect(cmd):
        if re.search(r"\bsavings?\b", cmd, re.I) and \
                re.search(r"\b(?:add|put|deposit|save|increase)\b",
                          cmd, re.I) and _nums(cmd):
            return {"cmd": cmd}
        return None

    def _savings_show_fn(app, cmd):
        state = _load_state()
        return "Your savings are at %s, sir." % _fmt(
            state.get("savings", 0.0))

    def _savings_show_detect(cmd):
        if re.search(r"\b(?:show|check|what is)\s+(?:my\s+)?savings?\b",
                     cmd, re.I) or re.search(r"\bhow much.*saved\b",
                                             cmd, re.I):
            return {"cmd": cmd}
        return None

    def _goal_add_fn(app, cmd):
        goal = _after(cmd, r"\bset\s+(?:a\s+)?goal\s+(?:to|of|for)\s*",
                      r"\bgoal\s*:\s*", r"\bnew goal\s*:\s*")
        if not goal:
            return None
        state = _load_state()
        state.setdefault("goals", []).append(goal)
        _save_state(state)
        return "Goal locked in, sir: %s" % goal

    def _goal_add_detect(cmd):
        if re.search(r"\b(?:set|add)\s+(?:a\s+)?goal\b", cmd, re.I) or \
                re.search(r"\bgoal\s*:", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _goal_show_fn(app, cmd):
        state = _load_state()
        return _say_list(_state_get(state, "goals"), "goals", numbered=True)

    def _goal_show_detect(cmd):
        if re.search(r"\b(?:show|list|what are)\s+(?:my\s+)?goals?\b",
                     cmd, re.I):
            return {"cmd": cmd}
        return None

    def _plan_day_fn(app, cmd):
        now = datetime.datetime.now().strftime("%A")
        return ("Here is a balanced daily plan, sir:\n"
                "  1. Morning: hardest task first (90 min)\n"
                "  2. Midday: quick wins and emails (60 min)\n"
                "  3. Afternoon: deep work or study (90 min)\n"
                "  4. Evening: exercise, dinner, wind down\n"
                "  5. Night: 30 min reading, plan tomorrow\n"
                "It is %s today, sir." % now)

    def _plan_day_detect(cmd):
        if re.search(r"\b(?:plan|schedule|structure|organize)\s+(?:my\s+)?"
                     r"day\b", cmd, re.I) or \
                re.search(r"\bdaily\s+(?:plan|schedule)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _pomodoro_fn(app, cmd):
        return ("Pomodoro technique, sir: 25 minutes of focused work, "
                "then a 5-minute break. After 4 rounds, take a longer "
                "20-minute break. Say 'set a timer for 25 minutes' and "
                "I will time it for you.")

    def _pomodoro_detect(cmd):
        if re.search(r"\bpomodoro\b|\b25[- ]5\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _workout_fn(app, cmd):
        w = cmd.lower()
        for k, ex in WORKOUTS.items():
            if k in w:
                return "Your %s workout, sir:\n%s" % (
                    k.title(), "\n".join("  " + x for x in ex))
        key = random.choice(list(WORKOUTS))
        return ("Try this quick routine, sir:\n%s"
                % "\n".join("  " + x for x in WORKOUTS[key]))

    def _workout_detect(cmd):
        if re.search(r"\b(?:workout|exercise|push-ups|squats|routine)\b",
                     cmd, re.I) and \
                re.search(r"\b(?:give|show|suggest|plan|make|start)\b",
                          cmd, re.I):
            return {"cmd": cmd}
        return None

    def _meal_plan_fn(app, cmd):
        diet = _after(cmd, r"\bmeal\s+plan\s+(?:for|on)\s*")
        diet = re.sub(r"\b(?:diet|day|week)\b", "", diet or "").strip()
        tag = (" (%s)" % diet) if diet else ""
        return ("One-day meal plan%s, sir:\n"
                "  Breakfast: oats with fruit and nuts\n"
                "  Snack: yogurt or a fruit\n"
                "  Lunch: rice, dal or protein, and vegetables\n"
                "  Snack: a handful of nuts\n"
                "  Dinner: grilled protein with salad\n"
                "  Drink water through the day." % tag)

    def _meal_plan_detect(cmd):
        if re.search(r"\bmeal\s+plan\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _recipe_fn(app, cmd):
        dish = _after(cmd, r"\brecipe\s+for\s*", r"\bhow to make\s*",
                      r"\bhow to cook\s*")
        if not dish:
            return None
        return _llm_reply(app, "Give a simple recipe for %s with an "
                               "ingredients list and short steps." % dish)

    def _recipe_detect(cmd):
        if re.search(r"\brecipe\s+for\b|\bhow to make\b|\bhow to cook\b",
                     cmd, re.I):
            return {"cmd": cmd}
        return None

    def _study_plan_fn(app, cmd):
        subject = _after(cmd, r"\bstudy\s+plan\s+(?:for|to)\s*",
                         r"\bplan\s+(?:to\s+)?(?:study|learn)\s*")
        topic = subject if subject else "your subject"
        return ("Study plan for %s, sir:\n"
                "  Week 1: foundations and key terms\n"
                "  Week 2: core concepts, 25-min pomodoro blocks\n"
                "  Week 3: practice problems and past questions\n"
                "  Week 4: review weak areas and mock test\n"
                "Review each topic within 24 hours and again in 7 days."
                % topic)

    def _study_plan_detect(cmd):
        if re.search(r"\bstudy\s+plan\b|\bplan\s+(?:to\s+)?study\b",
                     cmd, re.I):
            return {"cmd": cmd}
        return None

    def _sleep_time_fn(app, cmd):
        m = re.search(r"\bwake(?:\s+up)?\s+(?:at\s+)?(\d{1,2})"
                      r"(?::(\d{2}))?\s*(am|pm)?", cmd, re.I)
        if not m:
            return ("For a good night, aim for 7 to 9 hours, sir. "
                    "If you wake at 7 am, sleep by 10 pm.")
        h = int(m.group(1)) % 12
        ampm = (m.group(3) or "am").lower()
        if ampm == "pm":
            h += 12
        cycles = []
        for c in range(5, 7):
            t = (h * 60 - c * 90) % (24 * 60)
            cycles.append("%d:%02d" % (t // 60, t % 60))
        return ("To wake at %d:%s, try sleeping at %s or %s to land on a "
                "90-minute sleep cycle, sir."
                % (m.group(1), m.group(2) or "00", cycles[0], cycles[1]))

    def _sleep_time_detect(cmd):
        if re.search(r"\b(?:sleep|bed|asleep)\b", cmd, re.I) and \
                re.search(r"\b(?:what time|when|should)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _water_intake_fn(app, cmd):
        nums = _nums(cmd)
        weight = nums[0] if nums else 70
        ml = weight * 35
        return ("A good target for %s kg is about %s liters of water a "
                "day, sir." % (_fmt(weight), _fmt(round(ml / 1000, 1))))

    def _water_intake_detect(cmd):
        if re.search(r"\b(?:water|hydrat)\b", cmd, re.I) and \
                re.search(r"\b(?:drink|how much|intake|need)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    # ---- E. WRITING / CREATIVE SKILLS ----

    reg_llm("essay", ["write an essay", "essay on", "essay about"],
            lambda c: "Write a short essay on: %s" % re.sub(
                r"^.*\bessay\s+(?:on|about)\s*", "", c, flags=re.I)
            if re.search(r"essay\s+(on|about)", c, re.I)
            else re.sub(r"^.*\bwrite an essay\s+(?:on|about)?\s*", "", c,
                        flags=re.I))
    reg_llm("letter", ["write a letter", "draft a letter", "letter to"],
            lambda c: "Write a polite letter: %s" % re.sub(
                r"^.*\b(?:write|draft)\s+a\s+letter\s+", "", c,
                flags=re.I))
    reg_llm("resume", ["write a resume", "resume for", "cv for",
                       "curriculum vitae"],
            lambda c: "Write a strong resume outline for: %s" % re.sub(
                r"^.*\b(?:write a )?(?:resume|cv)\s+(?:for|of)?\s*", "",
                c, flags=re.I))
    reg_llm("cover_letter", ["cover letter", "covering letter"],
            lambda c: "Write a cover letter for: %s" % c)
    reg_llm("blog_post", ["blog post about", "write a blog", "article "
                          "about"],
            lambda c: "Outline a blog post about: %s" % re.sub(
                r"^.*\b(?:blog post|article)\s+(?:about|on)\s*", "", c,
                flags=re.I))
    reg_llm("report", ["write a report", "report on"],
            lambda c: "Write a structured report on: %s" % re.sub(
                r"^.*\breport\s+(?:on|about)\s*", "", c, flags=re.I))
    reg_llm("tweet", ["write a tweet", "tweet about", "tweet for"],
            lambda c: "Write a short engaging tweet about: %s" % re.sub(
                r"^.*\btweet\s+(?:about|for)?\s*", "", c, flags=re.I))
    reg_llm("caption", ["instagram caption", "caption for", "social media "
                        "caption"],
            lambda c: "Write an Instagram caption for: %s" % re.sub(
                r"^.*\bcaption\s+(?:for|about)?\s*", "", c, flags=re.I))
    reg_llm("linkedin_post", ["linkedin post", "linkedin update"],
            lambda c: "Write a professional LinkedIn post about: %s" % c)
    reg_llm("speech", ["write a speech", "speech about", "speech on"],
            lambda c: "Write a short speech about: %s" % re.sub(
                r"^.*\bspeech\s+(?:about|on)\s*", "", c, flags=re.I))
    reg_llm("haiku", ["haiku about", "write a haiku", "haiku for"],
            lambda c: "Write a haiku about: %s" % re.sub(
                r"^.*\bhaiku\s+(?:about|for)?\s*", "", c, flags=re.I))
    reg_llm("limerick", ["limerick about", "write a limerick", "limerick "
                         "for"],
            lambda c: "Write a funny limerick about: %s" % re.sub(
                r"^.*\blimerick\s+(?:about|for)?\s*", "", c, flags=re.I))
    reg_llm("lyrics", ["write lyrics", "lyrics for a song", "song lyrics "
                       "about"],
            lambda c: "Write short song lyrics about: %s" % re.sub(
                r"^.*\blyrics\s+(?:for|about)?\s*", "", c, flags=re.I))
    reg_llm("outline", ["make an outline", "create an outline", "outline "
                        "for", "outline of"],
            lambda c: "Create a clear outline for: %s" % re.sub(
                r"^.*\boutline\s+(?:for|of)?\s*", "", c, flags=re.I))
    reg_llm("brainstorm", ["brainstorm", "ideas for", "come up with "
                           "ideas"],
            lambda c: "Brainstorm 8 creative ideas for: %s" % re.sub(
                r"^.*\b(?:brainstorm|ideas\s+for)\s*", "", c,
                flags=re.I))
    reg_llm("pros_cons", ["pros and cons", "pros and cons of"],
            lambda c: "List the pros and cons of: %s" % re.sub(
                r"^.*\bpros\s+and\s+cons\s+of\s*", "", c, flags=re.I))
    reg_llm("compare", ["compare", "which is better"],
            lambda c: "Compare the options in: %s. Give a verdict." % c)
    reg_llm("checklist", ["make a checklist", "create a checklist",
                          "checklist for", "to-do list for"],
            lambda c: "Create a practical checklist for: %s" % re.sub(
                r"^.*\bchecklist\s+(?:for|of)?\s*", "", c, flags=re.I))
    reg_llm("paraphrase", ["paraphrase", "rewrite this", "rephrase"],
            lambda c: "Paraphrase this in simpler words: %s" % re.sub(
                r"^.*\b(?:paraphrase|rewrite this|rephrase)\s*[:]?\s*",
                "", c, flags=re.I))
    reg_llm("proofread", ["proofread", "check my grammar", "grammar "
                          "check", "fix my spelling"],
            lambda c: "Proofread and fix this text, show the corrected "
                      "version: %s" % re.sub(
                r"^.*\b(?:proofread|check my grammar|grammar check)\s*"
                r"[:]?\s*", "", c, flags=re.I))
    reg_llm("headline", ["headline for", "headline about"],
            lambda c: "Write 5 catchy headlines for: %s" % re.sub(
                r"^.*\bheadline\s+(?:for|about)?\s*", "", c,
                flags=re.I))
    reg_llm("bio", ["write a bio", "bio for", "short bio"],
            lambda c: "Write a short professional bio for: %s" % re.sub(
                r"^.*\bbio\s+(?:for|about)?\s*", "", c, flags=re.I))

    # ---- F. TEXT UTILITIES ----

    def _text_skill(name, patterns, extract_pats, transform, suffix=", sir."):
        def fn(app, cmd):
            text = None
            for p in extract_pats:
                text = _after(cmd, p)
                if text:
                    break
            if text is None:
                return None
            result = transform(text)
            return "%s%s" % (result, suffix)
        reg(name, patterns, fn)

    def _upper_fn(app, cmd):
        t = _after(cmd, r"\bupper[- ]?case\s*", r"\bmake\s+(?:it\s+)?"
                   r"(?:all\s+)?caps\s*", r"\bcaps\s*:")
        return t.upper() if t else None

    def _lower_fn(app, cmd):
        t = _after(cmd, r"\blower[- ]?case\s*", r"\blowercase\s*")
        return t.lower() if t else None

    def _title_fn(app, cmd):
        t = _after(cmd, r"\btitle[- ]?case\s*", r"\btitle case\s*")
        return t.title() if t else None

    def _case_fn(cmd, kind):
        t = None
        for p in [r"\b%s\s*:" % kind, r"\b(?:convert|make|change)\s+"
                  r"(?:it\s+)?(?:to\s+)?%s\s*" % kind,
                  r"\b%s\s*case\s*:\s*" % kind, r"\b%s\s*case\s+" % kind]:
            t = _after(cmd, p)
            if t:
                break
        return t

    def _camel_fn(app, cmd):
        t = _case_fn(cmd, "camel")
        if not t:
            return None
        words = re.findall(r"[a-zA-Z0-9]+", t)
        return (words[0].lower() + "".join(w.title() for w in words[1:]))

    def _snake_fn(app, cmd):
        t = _case_fn(cmd, "snake")
        if not t:
            return None
        words = re.findall(r"[a-zA-Z0-9]+", t)
        return "_".join(w.lower() for w in words)

    def _kebab_fn(app, cmd):
        t = _case_fn(cmd, "kebab")
        if not t:
            return None
        words = re.findall(r"[a-zA-Z0-9]+", t)
        return "-".join(w.lower() for w in words)

    def _slug_fn(app, cmd):
        t = _after(cmd, r"\bslug(?:ify)?\s*(?:for|of)?\s*",
                   r"\burl[- ]?friendly\s+(?:for|of)?\s*")
        if not t:
            return None
        t = t.lower()
        t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
        return t or None

    def _char_count_fn(app, cmd):
        t = _after(cmd, r"\bcharacters?\s+(?:in|of|for)\s*",
                   r"\bhow many characters\s+(?:are there\s+)?(?:in|of)\s*")
        return "%d characters" % len(t) if t is not None else None

    def _sentence_count_fn(app, cmd):
        t = _after(cmd, r"\bsentences?\s+(?:in|of|for)\s*",
                   r"\bhow many sentences\s+(?:are there\s+)?(?:in|of)\s*")
        if t is None:
            return None
        n = len([s for s in re.split(r"[.!?]+", t) if s.strip()])
        return "%d sentences" % n

    def _line_count_fn(app, cmd):
        t = _after(cmd, r"\blines?\s+(?:in|of|for)\s*",
                   r"\bhow many lines\s+(?:are there\s+)?(?:in|of)\s*")
        return "%d lines" % len(t.splitlines()) if t is not None else None

    def _vowel_count_fn(app, cmd):
        t = _after(cmd, r"\bvowels?\s+(?:in|of|for)\s*",
                   r"\bhow many vowels\s+(?:are there\s+)?(?:in|of)\s*")
        if t is None:
            return None
        n = len(re.findall(r"[aeiouAEIOU]", t))
        return "%d vowels" % n

    def _remove_spaces_fn(app, cmd):
        t = _after(cmd, r"\bremove\s+(?:all\s+)?spaces\s+(?:from|in)\s*",
                   r"\bremove\s+whitespace\s*(?:from|in)?\s*")
        return t.replace(" ", "") if t is not None else None

    def _acronym_fn(app, cmd):
        t = _after(cmd, r"\bacronym\s+(?:for|of)\s*")
        if not t:
            return None
        return "".join(w[0].upper() for w in re.findall(r"\b\w", t))

    def _caesar_fn(app, cmd):
        nums = _int_nums(cmd)
        shift = nums[0] if nums else 3
        t = _after(cmd, r"\bcaesar(?:\s+cipher)?\s+")
        if t is None:
            return None
        t = re.sub(r"\bshift\s+\d+\b", "", t).strip()
        out = []
        for ch in t:
            if ch.isalpha():
                base = ord("A") if ch.isupper() else ord("a")
                out.append(chr((ord(ch) - base + shift) % 26 + base))
            else:
                out.append(ch)
        return "".join(out)

    def _random_word_fn(app, cmd):
        words = ["serendipity", "luminous", "cascade", "whimsical",
                 "ember", "zenith", "quiver", "halcyon", "mellow",
                 "vibrant", "echo", "horizon", "velvet", "amber",
                 "breeze", "cosmos", "dusk", "fable"]
        return random.choice(words)

    def _unique_words_fn(app, cmd):
        t = _after(cmd, r"\bunique words?\s+(?:in|of|for)\s*",
                   r"\bhow many unique words\s*(?:are there\s+)?(?:in|of)\s*")
        if t is None:
            return None
        words = set(re.findall(r"[a-zA-Z]+", t.lower()))
        return "%d unique words" % len(words)

    def _replace_fn(app, cmd):
        m = re.search(r"\breplace\s+(.+?)\s+with\s+(.+?)\s+in\s+(.+)$",
                      cmd, re.I)
        if not m:
            m = re.search(r"\breplace\s+['\"](.+?)['\"]\s+(?:with|by)\s+"
                          r"['\"](.+?)['\"]\s+in\s+(.+)$", cmd, re.I)
        if not m:
            return None
        return m.group(3).replace(m.group(1), m.group(2))

    def _contains_fn(app, cmd):
        m = re.search(r"\bdoes\s+['\"]?(.+?)['\"]?\s+contain\s+['\"]?"
                      r"(.+?)['\"]?\s*$", cmd, re.I)
        if not m:
            return None
        return ("Yes, it contains that, sir." if m.group(2) in m.group(1)
                else "No, it does not contain that, sir.")

    def _anagram_fn(app, cmd):
        m = re.search(r"\banagram(?:s)?\s+check\s+(\w+)\s+and\s+(\w+)\b"
                      r"|\bare\s+(\w+)\s+and\s+(\w+)\s+anagrams?\b",
                      cmd, re.I)
        if not m:
            return None
        if m.group(1):
            a, b = m.group(1), m.group(2)
        else:
            a, b = m.group(3), m.group(4)
        a, b = sorted(a.lower()), sorted(b.lower())
        return ("Yes, they are anagrams, sir." if a == b else
                "No, they are not anagrams, sir.")

    def _scramble_fn(app, cmd):
        t = _after(cmd, r"\bscramble\s+(?:the\s+word\s+|the\s+)?",
                   r"\banagram(?:-ish)?\s+")
        if not t:
            return None
        letters = list(t)
        random.shuffle(letters)
        return "".join(letters)

    def _base64_fn(app, cmd, encode=True):
        t = _after(cmd, r"\b(?:base64|b64)\s+(?:en|de)code\s*")
        if t is None:
            return None
        if encode:
            return __import__("base64").b64encode(t.encode()).decode()
        try:
            return __import__("base64").b64decode(t.encode()).decode()
        except Exception:
            return None

    def _url_fn(app, cmd, encode=True):
        from urllib.parse import quote, unquote
        t = _after(cmd, r"\burl[- ]?encode\s*")
        if t is None:
            t = _after(cmd, r"\burl[- ]?decode\s*")
            if t is not None:
                return unquote(t)
        if t is not None:
            return quote(t)
        return None

    def _hash_fn(app, cmd):
        t = _after(cmd, r"\bhash\s+(?:this\s+)?(?:text\s+)?")
        if t is None:
            t = _after(cmd, r"\bsha256\s+of\s*")
        if t is None:
            return None
        return hashlib.sha256(t.encode()).hexdigest()

    def _random_hex_fn(app, cmd):
        return uuid.uuid4().hex[:16]

    def _case_detect(cmd, kind):
        if re.search(r"\b%s[- ]?case\b" % kind, cmd, re.I) or \
                re.search(r"\b(?:convert|make|change)\s+(?:it\s+)?(?:to\s+)?"
                          r"%s\b" % kind, cmd, re.I):
            return {"cmd": cmd}
        return None

    reg("uppercase", ["uppercase", "upper case", "all caps"],
        _upper_fn)
    reg("lowercase", ["lowercase", "lower case"], _lower_fn)
    reg("title_case", ["titlecase", "title case"], _title_fn)

    def _det(name, fn, detect):
        brain.register(name, detect, lambda app, ctx: fn(app, ctx["cmd"]))

    _det("camel_case", _camel_fn, lambda c: _case_detect(c, "camel"))
    _det("snake_case", _snake_fn, lambda c: _case_detect(c, "snake"))
    _det("kebab_case", _kebab_fn, lambda c: _case_detect(c, "kebab"))

    reg("slugify", ["slugify", "slug for", "url friendly"], _slug_fn)
    reg("char_count", ["characters in", "how many characters", "character "
                       "count"],
        _char_count_fn)
    reg("sentence_count", ["sentences in", "how many sentences"],
        _sentence_count_fn)
    reg("line_count", ["lines in", "how many lines", "line count"],
        _line_count_fn)
    reg("vowel_count", ["vowels in", "how many vowels", "vowel count"],
        _vowel_count_fn)
    reg("remove_spaces", ["remove spaces", "remove whitespace"],
        _remove_spaces_fn)
    reg("acronym", ["acronym for"], _acronym_fn)
    reg("caesar_cipher", ["caesar cipher", "caesar"], _caesar_fn)
    reg("random_word", ["random word", "give me a word"], _random_word_fn)
    reg("unique_words", ["unique words", "how many unique words"],
        _unique_words_fn)
    reg("replace_text", ["replace"], _replace_fn)
    reg("contains_text", ["contain"], _contains_fn)
    reg("anagram_check", ["anagram"], _anagram_fn)
    reg("scramble", ["scramble"], _scramble_fn)
    reg("base64_encode", ["base64 encode", "b64 encode", "encode in "
                          "base64"],
        lambda app, cmd: _base64_fn(app, cmd, True))
    reg("base64_decode", ["base64 decode", "b64 decode", "decode base64"],
        lambda app, cmd: _base64_fn(app, cmd, False))
    reg("url_encode", ["url encode", "encode url"], _url_fn)
    reg("url_decode", ["url decode", "decode url"],
        lambda app, cmd: _url_fn(app, cmd, False))
    reg("hash_text", ["hash", "sha256 of"], _hash_fn)
    reg("random_hex", ["random hex", "hex string"], _random_hex_fn)

    # ---- G. EVERYDAY MATH & CONVERTERS ----

    def _two_nums(name, patterns, op, label):
        def fn(app, cmd):
            nums = _nums(cmd)
            if len(nums) < 2:
                return None
            a, b = nums[0], nums[1]
            result = op(a, b)
            return "%s %s %s = %s, sir." % (_fmt(a), label, _fmt(b),
                                            _fmt(round(result, 6)))
        reg(name, patterns, fn)

    _two_nums("gcd", ["gcd of", "hcf of"],
              lambda a, b: math.gcd(int(a), int(b)), "gcd")
    _two_nums("lcm", ["lcm of"],
              lambda a, b: a * b // math.gcd(int(a), int(b)), "lcm")

    def _percent_change_fn(app, cmd):
        nums = _nums(cmd)
        if len(nums) < 2:
            return None
        a, b = nums[0], nums[1]
        if a == 0:
            return None
        pct = (b - a) / a * 100
        return ("The change from %s to %s is %s%s, sir."
                % (_fmt(a), _fmt(b), "+" if pct > 0 else "",
                   _fmt(round(pct, 2))))

    def _percent_change_detect(cmd):
        if re.search(r"\bpercent(?:age)?\s+change\b|\bchange\s+from\b",
                     cmd, re.I) and len(_nums(cmd)) >= 2:
            return {"cmd": cmd}
        return None

    def _ratio_fn(app, cmd):
        nums = _nums(cmd)
        if len(nums) < 2:
            return None
        g = math.gcd(int(nums[0]), int(nums[1]))
        return "Simplified, that is %s : %s, sir." % (
            _fmt(int(nums[0]) // g), _fmt(int(nums[1]) // g))

    def _ratio_detect(cmd):
        if re.search(r"\bratio\b", cmd, re.I) and len(_nums(cmd)) >= 2:
            return {"cmd": cmd}
        return None

    def _fraction_fn(app, cmd):
        m = re.search(r"\bsimplify\s+(?:the\s+)?fraction\s+(\d+)\s*/\s*(\d+)",
                      cmd, re.I)
        if not m:
            m = re.search(r"\bsimplify\s+(\d+)\s*/\s*(\d+)", cmd, re.I)
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2))
        g = math.gcd(a, b)
        return "%d/%d simplifies to %d/%d, sir." % (a, b, a // g, b // g)

    def _fraction_detect(cmd):
        if re.search(r"\bsimplify\b.*\d+\s*/\s*\d+", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _decimal_frac_fn(app, cmd):
        nums = _nums(cmd)
        if not nums:
            return None
        from fractions import Fraction
        f = Fraction(nums[0]).limit_denominator(1000)
        return "%s as a fraction is %s, sir." % (_fmt(nums[0]), f)

    def _decimal_frac_detect(cmd):
        if re.search(r"\b(?:as\s+a\s+fraction|to\s+fraction|fraction of)\b",
                     cmd, re.I) and _nums(cmd):
            return {"cmd": cmd}
        return None

    def _base_convert_fn(app, cmd):
        m = re.search(r"\bconvert\s+(\w+)\s+from\s+base\s+(\d+)\s+to\s+"
                      r"base\s+(\d+)", cmd, re.I)
        if not m:
            return None
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"
        value = 0
        for ch in m.group(1).lower():
            value = value * int(m.group(2)) + digits.index(ch)
        out = []
        base = int(m.group(3))
        while value:
            out.append(digits[value % base])
            value //= base
        return "%s in base %d is %s, sir." % (m.group(1),
                                              int(m.group(3)),
                                              "".join(reversed(out)) or "0")

    def _base_convert_detect(cmd):
        if re.search(r"\bconvert\s+\w+\s+from\s+base\s+\d+\s+to\s+base\s+"
                     r"\d+", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _octal_fn(app, cmd):
        nums = _int_nums(cmd)
        if not nums:
            return None
        return "%s in octal is %s, sir." % (nums[0], oct(nums[0])[2:])

    def _octal_detect(cmd):
        if re.search(r"\bin\s+octal\b|\bto\s+octal\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _unit_convert(name, patterns, table, label):
        def fn(app, cmd):
            nums = _nums(cmd)
            if not nums:
                return None
            m = re.search(r"\b(?:convert|how many|what is)\s+"
                          r"(\d+(?:\.\d+)?)\s+(.+?)\s+(?:to|in|into)\s+"
                          r"(.+?)\s*$", cmd, re.I)
            if not m:
                return None
            val, fr, to = float(m.group(1)), m.group(2).strip().lower(), \
                m.group(3).strip().lower()
            fk = tk = None
            for k in table:
                if k.lower() == fr or fr in k.lower():
                    fk = k
                if k.lower() == to or to in k.lower():
                    tk = k
            if not fk or not tk:
                return None
            result = val * table[fk] / table[tk]
            return "%.6g %s = %.6g %s, sir." % (val, fr, result, to)

        def detect(cmd):
            for p in patterns:
                if re.search(r"\b" + re.escape(p) + r"\b", cmd, re.I) and \
                        _nums(cmd):
                    return {"cmd": cmd}
            return None
        reg_fn(name, detect, fn)

    _unit_convert("area_convert", ["square feet", "square meters",
                                   "square meter", "sq ft", "acres",
                                   "hectares"], AREA_UNITS, "area")
    _unit_convert("volume_convert", ["liters", "litres", "gallons", "pints",
                                     "cups", "fluid ounce", "milliliters",
                                     "ml"], VOLUME_UNITS, "volume")
    _unit_convert("pressure_convert", ["psi", "atmosphere", "atm", "bar",
                                       "pascal"], PRESSURE_UNITS, "pressure")
    _unit_convert("energy_convert", ["calories", "joules", "kilojoules",
                                     "kilocalorie", "kcal", "kwh"],
                  ENERGY_UNITS, "energy")
    _unit_convert("power_convert", ["watts", "kilowatts", "horsepower",
                                    "megawatt"], POWER_UNITS, "power")
    _unit_convert("angle_convert", ["degrees", "radians", "radians to"],
                  ANGLE_UNITS, "angle")

    def _time_convert_fn(app, cmd):
        nums = _nums(cmd)
        if not nums:
            return None
        val = nums[0]
        m = re.search(r"\bconvert\s+(\d+(?:\.\d+)?)\s+([a-z]+)\s+(?:to|"
                      r"into)\s+([a-z]+)\s*$", cmd, re.I)
        if not m:
            return None
        units = {"second": 1, "seconds": 1, "sec": 1, "minute": 60,
                 "minutes": 60, "min": 60, "hour": 3600, "hours": 3600,
                 "hr": 3600, "hrs": 3600, "day": 86400, "days": 86400,
                 "week": 604800, "weeks": 604800, "month": 2629800,
                 "months": 2629800, "year": 31557600, "years": 31557600}
        fr, to = m.group(2).lower(), m.group(3).lower()
        if fr not in units or to not in units:
            return None
        result = val * units[fr] / units[to]
        return "%.6g %s = %.6g %s, sir." % (val, fr, result, to)

    def _time_convert_detect(cmd):
        if re.search(r"\bconvert\b.*\b(?:seconds?|minutes?|hours?|days?|"
                     r"weeks?|months?|years?)\b", cmd, re.I) and \
                re.search(r"\b(?:to|into)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _fuel_fn(app, cmd):
        nums = _nums(cmd)
        if not nums:
            return None
        val = nums[0]
        if re.search(r"\bmpg\b|\bmiles per gallon\b", cmd, re.I):
            l100 = 235.215 / val
            return "%.1f mpg is about %.1f L per 100 km, sir." % (val, l100)
        l100 = val
        mpg = 235.215 / l100
        return "%.1f L/100km is about %.1f mpg, sir." % (l100, mpg)

    def _fuel_detect(cmd):
        if re.search(r"\bmpg\b|\bper\s+100\s*km\b|\bliters?\s+per\b",
                     cmd, re.I) and _nums(cmd):
            return {"cmd": cmd}
        return None

    def _compound_interest_fn(app, cmd):
        nums = _nums(cmd)
        if len(nums) < 3:
            return None
        p, r, y = nums[0], nums[1], nums[2]
        a = p * (1 + r / 100) ** y
        return ("%s grows to about %s in %s years at %s%% compound "
                "interest, sir." % (_fmt(p), _fmt(round(a, 2)),
                                    _fmt(y), _fmt(r)))

    def _compound_interest_detect(cmd):
        if re.search(r"\bcompound\s+interest\b", cmd, re.I) and \
                len(_nums(cmd)) >= 3:
            return {"cmd": cmd}
        return None

    def _simple_interest_fn(app, cmd):
        nums = _nums(cmd)
        if len(nums) < 3:
            return None
        p, r, y = nums[0], nums[1], nums[2]
        i = p * r / 100 * y
        return ("Simple interest on %s at %s%% for %s years is %s, sir."
                % (_fmt(p), _fmt(r), _fmt(y), _fmt(round(i, 2))))

    def _simple_interest_detect(cmd):
        if re.search(r"\bsimple\s+interest\b", cmd, re.I) and \
                len(_nums(cmd)) >= 3:
            return {"cmd": cmd}
        return None

    def _loan_fn(app, cmd):
        nums = _nums(cmd)
        if len(nums) < 3:
            return None
        principal, rate, years = nums[0], nums[1], nums[2]
        r = rate / 100 / 12
        n = years * 12
        if r == 0:
            payment = principal / n
        else:
            payment = principal * r / (1 - (1 + r) ** -n)
        total = payment * n
        return ("Estimated monthly payment: %s. Total paid: %s, sir."
                % (_fmt(round(payment, 2)), _fmt(round(total, 2))))

    def _loan_detect(cmd):
        if re.search(r"\b(?:loan|mortgage|emi|monthly payment)\b", cmd,
                     re.I) and len(_nums(cmd)) >= 3:
            return {"cmd": cmd}
        return None

    def _discount_fn(app, cmd):
        nums = _nums(cmd)
        if len(nums) < 2:
            return None
        pct, price = nums[0], nums[1]
        disc = price * pct / 100
        return ("%s%% off %s is %s off, so you pay %s, sir."
                % (_fmt(pct), _fmt(price), _fmt(round(disc, 2)),
                   _fmt(round(price - disc, 2))))

    def _discount_detect(cmd):
        if re.search(r"\b(?:percent|%)\s+off\b|\boff\s+", cmd, re.I) and \
                len(_nums(cmd)) >= 2 and not re.search(r"\bof\b",
                                                       cmd, re.I) and \
                not re.search(r"\btip\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _tax_fn(app, cmd):
        nums = _nums(cmd)
        if len(nums) < 2:
            return None
        amount, rate = nums[0], nums[1]
        tax = amount * rate / 100
        return ("Tax on %s at %s%% is %s, making a total of %s, sir."
                % (_fmt(amount), _fmt(rate), _fmt(round(tax, 2)),
                   _fmt(round(amount + tax, 2))))

    def _tax_detect(cmd):
        if re.search(r"\btax\b", cmd, re.I) and len(_nums(cmd)) >= 2:
            return {"cmd": cmd}
        return None

    def _hourly_fn(app, cmd):
        nums = _nums(cmd)
        if not nums:
            return None
        yearly = nums[0]
        hourly = yearly / (52 * 40)
        monthly = yearly / 12
        return ("%s a year is about %s an hour and %s a month, sir."
                % (_fmt(yearly), _fmt(round(hourly, 2)),
                   _fmt(round(monthly, 2))))

    def _hourly_detect(cmd):
        if re.search(r"\bper\s+year\b|\ba\s+year\b|\bannual\b", cmd,
                     re.I) and _nums(cmd):
            return {"cmd": cmd}
        return None

    def _doubling_fn(app, cmd):
        nums = _nums(cmd)
        if len(nums) < 2:
            return None
        rate = nums[1]
        if rate <= 0:
            return None
        years = 72 / rate
        return ("By the rule of 72, %s doubles in about %s years at %s%%, "
                "sir." % (_fmt(nums[0]), _fmt(round(years, 1)), _fmt(rate)))

    def _doubling_detect(cmd):
        if re.search(r"\bdouble\b|\brule of 72\b", cmd, re.I) and \
                len(_nums(cmd)) >= 2:
            return {"cmd": cmd}
        return None

    def _split_bill_fn(app, cmd):
        nums = _nums(cmd)
        if len(nums) < 2:
            return None
        total, people = nums[0], int(nums[1])
        if people <= 0:
            return None
        return ("Each of the %d people pays %s, sir."
                % (people, _fmt(round(total / people, 2))))

    def _split_bill_detect(cmd):
        if re.search(r"\bsplit\b.*\bbetween\b|\bsplit\b.*\bamong\b",
                     cmd, re.I) and len(_nums(cmd)) >= 2:
            return {"cmd": cmd}
        return None

    def _score_pct_fn(app, cmd):
        nums = _nums(cmd)
        if len(nums) < 2:
            return None
        got, total = nums[0], nums[1]
        if total == 0:
            return None
        pct = got / total * 100
        return ("%s out of %s is %s percent, sir."
                % (_fmt(got), _fmt(total), _fmt(round(pct, 2))))

    def _score_pct_detect(cmd):
        if re.search(r"\b(?:out\s+of|percent of the total)\b", cmd,
                     re.I) and len(_nums(cmd)) >= 2:
            return {"cmd": cmd}
        return None

    def _grade_fn(app, cmd):
        nums = _nums(cmd)
        if len(nums) < 2:
            return None
        got, total = nums[0], nums[1]
        if total == 0:
            return None
        pct = got / total * 100
        if pct >= 90:
            grade = "A"
        elif pct >= 80:
            grade = "B"
        elif pct >= 70:
            grade = "C"
        elif pct >= 60:
            grade = "D"
        else:
            grade = "F"
        return ("%s percent is a grade of %s, sir." % (_fmt(round(pct, 1)),
                                                       grade))

    def _grade_detect(cmd):
        if re.search(r"\bgrade\b", cmd, re.I) and len(_nums(cmd)) >= 2:
            return {"cmd": cmd}
        return None

    def _sum_fn(app, cmd):
        nums = _nums(cmd)
        if len(nums) < 2:
            return None
        return ("The sum is %s, sir." % _fmt(round(sum(nums), 6)))

    def _sum_detect(cmd):
        if re.search(r"\bsum\s+(?:of|up)\b|\badd\s+", cmd, re.I) and \
                len(_nums(cmd)) >= 2:
            return {"cmd": cmd}
        return None

    def _range_fn(app, cmd):
        nums = _nums(cmd)
        if len(nums) < 2:
            return None
        return ("The range is %s (min %s, max %s), sir."
                % (_fmt(round(max(nums) - min(nums), 6)),
                   _fmt(min(nums)), _fmt(max(nums))))

    def _range_detect(cmd):
        if re.search(r"\brange\s+of\b", cmd, re.I) and len(_nums(cmd)) >= 2:
            return {"cmd": cmd}
        return None

    def _min_max_fn(app, cmd):
        nums = _nums(cmd)
        if not nums:
            return None
        if re.search(r"\bmin(?:imum)?\b", cmd, re.I):
            return "The minimum is %s, sir." % _fmt(min(nums))
        return "The maximum is %s, sir." % _fmt(max(nums))

    def _min_max_detect(cmd):
        if re.search(r"\b(?:min|minimum|max|maximum)\s+of\b", cmd, re.I) \
                and _nums(cmd):
            return {"cmd": cmd}
        return None

    reg("percentage_change", ["percentage change", "percent change",
                              "change from"], _percent_change_fn)
    reg("ratio_simplify", ["ratio"], _ratio_fn)
    reg("fraction_simplify", ["simplify"], _fraction_fn)
    reg("decimal_to_fraction", ["as a fraction", "to a fraction"],
        _decimal_frac_fn)
    reg("base_convert", ["from base"], _base_convert_fn)
    reg_fn("time_convert", _time_convert_detect, _time_convert_fn)
    reg("fuel_economy", ["mpg", "l/100km", "per 100 km"], _fuel_fn)
    reg("compound_interest", ["compound interest"], _compound_interest_fn)
    reg("simple_interest", ["simple interest"], _simple_interest_fn)
    reg("loan_payment", ["loan", "mortgage", "emi"], _loan_fn)
    reg("discount", ["percent off", "% off", "off"], _discount_fn)
    reg("tax_calc", ["tax on", "gst", "vat"], _tax_fn)
    reg("hourly_rate", ["per year", "a year", "annual salary"],
        _hourly_fn)
    reg("doubling_time", ["double", "rule of 72"], _doubling_fn)
    reg("split_bill", ["split"], _split_bill_fn)
    def _score_pct_detect(cmd):
        if re.search(r"\bout\s+of\b", cmd, re.I) and \
                not re.search(r"\bgrade\b", cmd, re.I):
            return {"cmd": cmd}
        return None
    reg_fn("score_percent", _score_pct_detect, _score_pct_fn)
    reg("grade_calc", ["grade for", "what grade"], _grade_fn)
    reg("sum_calc", ["sum of", "sum up", "add these"], _sum_fn)
    reg("range_calc", ["range of"], _range_fn)
    reg("min_max", ["minimum of", "maximum of", "min of", "max of"],
        _min_max_fn)

    # ---- H. DATES & TIMES ----

    def _date_diff_fn(app, cmd):
        dates = re.findall(r"\b\d{1,2}(?:st|nd|rd|th)?\s+"
                           r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|"
                           r"dec)[a-z]*\s+\d{4}\b"
                           r"|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|"
                           r"nov|dec)[a-z]*\s+\d{1,2}\b", cmd, re.I)
        days = []
        year = datetime.date.today().year
        for d1, d2, d3, d4, d5 in re.findall(r"(\d{1,2})\s+([a-z]{3,})\.?"
                                             r"\s+(\d{4})|([a-z]{3,})\s+"
                                             r"(\d{1,2})", cmd, re.I):
            day = int(d1) if d1 else int(d5)
            mon = (d2 or d4).lower()[:3]
            yr = int(d3) if d3 else year
            if mon in MONTH_NUM or mon in ("jan", "feb", "mar", "apr",
                                           "may", "jun", "jul", "aug",
                                           "sep", "oct", "nov", "dec"):
                days.append(datetime.date(yr, MONTH_ABBR[mon], day))
        if len(days) < 2:
            return None
        diff = abs((days[1] - days[0]).days)
        return ("That is %s days apart, sir." % _fmt(diff))

    def _date_diff_detect(cmd):
        if re.search(r"\b(?:between|how many days|days between)\b",
                     cmd, re.I) and \
                re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|"
                          r"nov|dec)[a-z]*", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _week_year_fn(app, cmd):
        now = datetime.date.today()
        return "We are in week %d of the year, sir." % now.isocalendar()[1]

    def _week_year_detect(cmd):
        if re.search(r"\b(?:week\s+of\s+the\s+year|week number|what week)\b",
                     cmd, re.I):
            return {"cmd": cmd}
        return None

    def _day_year_fn(app, cmd):
        now = datetime.date.today()
        return ("It is day %d of the year, sir." % now.timetuple().tm_yday)

    def _day_year_detect(cmd):
        if re.search(r"\b(?:day\s+of\s+the\s+year|day number)\b", cmd,
                     re.I):
            return {"cmd": cmd}
        return None

    def _unix_fn(app, cmd):
        import time as _time
        return "The Unix timestamp is %d, sir." % int(_time.time())

    def _unix_detect(cmd):
        if re.search(r"\b(?:unix\s+timestamp|epoch\s+time|timestamp now)\b",
                     cmd, re.I):
            return {"cmd": cmd}
        return None

    def _ts_date_fn(app, cmd):
        nums = _int_nums(cmd)
        if not nums:
            return None
        try:
            d = datetime.datetime.fromtimestamp(nums[0])
        except Exception:
            return None
        return ("That timestamp is %s, sir."
                % d.strftime("%B %d, %Y at %I:%M %p"))

    def _ts_date_detect(cmd):
        if re.search(r"\b(?:timestamp|epoch)\b.*\b(?:date|convert)\b",
                     cmd, re.I) and _int_nums(cmd):
            return {"cmd": cmd}
        return None

    def _days_in_month_fn(app, cmd):
        m = re.search(r"\b(?:days\s+in|length of)\s+(jan|feb|mar|apr|may|"
                      r"jun|jul|aug|sep|oct|nov|dec)[a-z]*"
                      r"(?:\s+(\d{4}))?", cmd, re.I)
        if not m:
            return None
        mon = MONTH_ABBR[m.group(1).lower()[:3]]
        year = int(m.group(2)) if m.group(2) else datetime.date.today().year
        if mon == 2:
            days = 29 if (year % 4 == 0 and year % 100 != 0) or \
                year % 400 == 0 else 28
        elif mon in (1, 3, 5, 7, 8, 10, 12):
            days = 31
        else:
            days = 30
        return ("%s %d has %d days, sir."
                % (list(MONTH_NUM.keys())[mon - 1], year, days))

    def _days_in_month_detect(cmd):
        if re.search(r"\b(?:days\s+in|length of)\s+(jan|feb|mar|apr|may|"
                     r"jun|jul|aug|sep|oct|nov|dec)", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _easter_fn(app, cmd):
        nums = _int_nums(cmd)
        year = nums[0] if nums else datetime.date.today().year
        a, b, c = year % 19, year % 4, year % 7
        d = (19 * a + 24) % 30
        e = (2 * b + 4 * c + 6 * d + 5) % 7
        day = 22 + d + e
        if day > 31:
            return ("Easter Sunday in %d is April %d, sir."
                    % (year, day - 31))
        return ("Easter Sunday in %d is March %d, sir." % (year, day))

    def _easter_detect(cmd):
        if re.search(r"\beaster\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _zodiac_fn(app, cmd):
        m = re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|"
                      r"dec)[a-z]*\s+(\d{1,2})\b", cmd, re.I)
        if not m:
            return None
        day = int(m.group(1))
        monm = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|"
                         r"dec)", cmd, re.I)
        month = MONTH_ABBR[monm.group(1).lower()]
        sign = _zodiac(month, day)
        return ("That birthday makes you a %s, sir. %s"
                % (sign, ZODIAC_PERSONALITY[sign.lower()]))

    def _zodiac_detect(cmd):
        if re.search(r"\b(?:zodiac|star sign|horoscope sign|what sign)\b",
                     cmd, re.I):
            return {"cmd": cmd}
        return None

    def _season_fn(app, cmd):
        today = datetime.date.today()
        m, d = today.month, today.day
        if (m == 12 and d >= 21) or m in (1, 2) or (m == 3 and d < 20):
            season = "winter"
        elif (m == 3 and d >= 20) or m in (4, 5) or (m == 6 and d < 21):
            season = "spring"
        elif (m == 6 and d >= 21) or m in (7, 8) or (m == 9 and d < 22):
            season = "summer"
        else:
            season = "fall"
        return ("It is %s in the Northern Hemisphere right now, sir."
                % season)

    def _season_detect(cmd):
        if re.search(r"\b(?:what season|which season)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    reg("date_difference", ["days between", "between july", "how many "
                            "days between"], _date_diff_fn)
    reg("week_of_year", ["week of the year", "week number", "what week"],
        _week_year_fn)
    reg("day_of_year", ["day of the year", "day number"], _day_year_fn)
    reg("unix_timestamp", ["unix timestamp", "epoch time", "timestamp now"],
        _unix_fn)
    reg("timestamp_to_date", ["timestamp"], _ts_date_fn)
    reg("days_in_month", ["days in", "length of"], _days_in_month_fn)
    reg("easter_date", ["easter"], _easter_fn)
    reg("zodiac_sign", ["zodiac", "star sign", "horoscope", "what sign"],
        _zodiac_fn)
    reg("season_today", ["what season", "which season"], _season_fn)

    # ---- I. GENERATORS ----

    def _name_gen_fn(app, cmd):
        starts = ["Aar", "Kai", "Maya", "Leo", "Ivy", "Noah", "Zara",
                  "Eli", "Nia", "Rey", "Ana", "Mio", "Theo", "Aria",
                  "Luca", "Sara", "Omar", "Eva", "Jai", "Lena"]
        ends = ["an", "a", "on", "ith", "en", "an", "o", "ia", "as",
                "in", "ora", "ian", "ette", "es", "ham", "lee"]
        gender = "boy" if re.search(r"\b(?:boy|male)\b", cmd, re.I) else \
            ("girl" if re.search(r"\b(?:girl|female)\b", cmd, re.I)
             else "any")
        name = random.choice(starts) + random.choice(ends)
        return ("Here is a %s name idea: %s, sir." % (gender, name))

    def _name_gen_detect(cmd):
        if re.search(r"\b(?:baby\s+)?names?\s+(?:idea|ideas)\b", cmd, re.I) or \
           re.search(r"\b(?:name|baby name)\s+generator\b", cmd, re.I) or \
           re.search(r"\b(?:generate|give|suggest|make)\s+(?:me\s+)?"
                     r"(?:a\s+)?(?:baby\s+)?name\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _team_name_fn(app, cmd):
        topic = _after(cmd, r"\bteam\s+name\s+(?:for|about)?\s*",
                       r"\bteam\s+name\s*")
        adj = ["Velocity", "Thunder", "Iron", "Golden", "Shadow", "Neon",
               "Rapid", "Cosmic", "Blazing", "Silent", "Alpha", "Turbo"]
        noun = ["Falcons", "Wolves", "Titans", "Eagles", "Pythons",
                "Hawks", "Rangers", "Comets", "Vipers", "Knights",
                "Reapers", "Falcons"]
        name = random.choice(adj) + " " + random.choice(noun)
        suffix = (" for %s" % topic) if topic else ""
        return ("Team name idea%s: %s, sir." % (suffix, name))

    def _team_name_detect(cmd):
        if re.search(r"\bteam\s+name\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _username_fn(app, cmd):
        base = _after(cmd, r"\busername\s+(?:for|based on|from)?\s*",
                      r"\buser name\s+(?:for|based on)?\s*")
        base = re.sub(r"\W+", "", (base or "").lower())
        if not base:
            base = random.choice(USERS)
        num = random.randint(1, 99)
        sep = random.choice(["", "", "_", ".", "_"])
        return ("Username idea: %s%s%s%d, sir."
                % (base, sep, random.choice(USERS), num))

    def _username_detect(cmd):
        if re.search(r"\busername\b|\buser name\b|\bhandle\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _hashtags_fn(app, cmd):
        topic = _after(cmd, r"\bhashtags?\s+(?:for|about)?\s*",
                       r"\btags\s+(?:for|about)?\s*")
        topic = re.sub(r"\W+", "", (topic or "").lower())
        tags = []
        if topic:
            tags.append("#" + topic)
        others = random.sample(HASHTAG_BASE, 5)
        tags.extend("#" + re.sub(r"^#", "", o) for o in others)
        return "Hashtags: %s, sir." % " ".join(tags)

    def _hashtags_detect(cmd):
        if re.search(r"\bhashtags?\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _blog_title_fn(app, cmd):
        topic = _after(cmd, r"\btitle\s+(?:for|about)?\s*",
                       r"\bheadline\s+(?:for|about)?\s*")
        openers = ["The Ultimate Guide to", "Why", "10 Reasons to",
                   "How", "What Nobody Tells You About", "A Beginner's "
                   "Guide to"]
        t = "%s %s" % (random.choice(openers), topic or "Your Topic")
        return "Blog title idea: %s, sir." % t

    def _blog_title_detect(cmd):
        if re.search(r"\b(?:blog\s+)?title\s+(?:for|about)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _slogan_fn(app, cmd):
        brand = _after(cmd, r"\bslogan\s+(?:for|about)?\s*")
        patterns = ["Empower the %s in you.", "Your %s, perfected.",
                    "Live your best %s.", "Smarter %s, better life.",
                    "Unlock the power of %s.", "%s made effortless."]
        return ("Slogan idea: %s, sir."
                % random.choice(patterns).replace("%s",
                                                  brand or "moment"))

    def _slogan_detect(cmd):
        if re.search(r"\bslogan\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _band_name_fn(app, cmd):
        adj = ["Electric", "Midnight", "Paper", "Silver", "Wild", "Neon",
               "Broken", "Golden"]
        noun = ["Crowd", "Static", "Foxes", "Rivers", "Echo", "Machines",
                "Glow", "Tides"]
        return "Band name idea: The %s %s, sir." % (
            random.choice(adj), random.choice(noun))

    def _band_name_detect(cmd):
        if re.search(r"\bband\s+name\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _palette_fn(app, cmd):
        mood = cmd.lower()
        for k, colors in COLOR_PALETTES.items():
            if k in mood:
                return ("Color palette for %s, sir:\n%s"
                        % (k, "\n".join("  " + c for c in colors)))
        palette = random.choice(list(COLOR_PALETTES.values()))
        return ("Color palette idea, sir:\n%s"
                % "\n".join("  " + c for c in palette))

    def _palette_detect(cmd):
        if re.search(r"\bcolor\s+palette\b|\bcolour\s+palette\b|\bpalette"
                     r"\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _excuse_fn(app, cmd):
        excuses = ["My code compiled, but only on my machine.",
                   "The dog ate the router.",
                   "I was waiting for the perfect commit message.",
                   "My calendar autocorrected the meeting to next week.",
                   "A sudden surge of productivity elsewhere.",
                   "I thought the deadline was an estimate.",
                   "My tabs crashed and took my progress with them."]
        return random.choice(excuses) + ", sir."

    def _excuse_detect(cmd):
        if re.search(r"\bexcuse\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _lottery_fn(app, cmd):
        nums = random.sample(range(1, 50), 6)
        return ("Your lucky numbers: %s, sir."
                % ", ".join(str(n) for n in sorted(nums)))

    def _lottery_detect(cmd):
        if re.search(r"\blottery\b|\blucky numbers\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _coordinates_fn(app, cmd):
        lat = round(random.uniform(-90, 90), 5)
        lon = round(random.uniform(-180, 180), 5)
        return ("Random coordinates: %s, %s, sir." % (lat, lon))

    def _coordinates_detect(cmd):
        if re.search(r"\brandom\s+coordinates\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    # ---- J. EVERYDAY LIFE ----

    def _ideal_weight_fn(app, cmd):
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:cm|meters?|metres?|feet|ft)?"
                      r"(\d+)?\s*(?:inches?|in)?", cmd, re.I)
        if not m:
            return None
        val = float(m.group(1))
        if re.search(r"\b(?:feet|ft)\b", cmd, re.I):
            inches = val * 12 + float(m.group(2) or 0)
            cm = inches * 2.54
        elif re.search(r"\b(?:cm)\b", cmd, re.I):
            cm = val
        else:
            cm = val * 100
        if cm <= 0:
            return None
        min_w = 18.5 * (cm / 100) ** 2
        max_w = 24.9 * (cm / 100) ** 2
        return ("For a height of %.0f cm, a healthy weight is about "
                "%.1f to %.1f kg, sir." % (cm, min_w, max_w))

    def _ideal_weight_detect(cmd):
        if re.search(r"\bideal\s+weight\b|\bhealthy\s+weight\b",
                     cmd, re.I) and _nums(cmd):
            return {"cmd": cmd}
        return None

    def _bmr_fn(app, cmd):
        nums = _nums(cmd)
        if len(nums) < 3:
            return None
        weight, height, age = nums[0], nums[1], nums[2]
        male = re.search(r"\b(male|man|boy)\b", cmd, re.I)
        if male:
            bmr = 10 * weight + 6.25 * height - 5 * age + 5
        else:
            bmr = 10 * weight + 6.25 * height - 5 * age - 161
        return ("Your estimated BMR is about %s calories a day, sir."
                % _fmt(round(bmr)))

    def _bmr_detect(cmd):
        if re.search(r"\bbmr\b|\bbasal metabolic\b", cmd, re.I) and \
                len(_nums(cmd)) >= 3:
            return {"cmd": cmd}
        return None

    def _tdee_fn(app, cmd):
        nums = _nums(cmd)
        if len(nums) < 3:
            return None
        weight, height, age = nums[0], nums[1], nums[2]
        male = re.search(r"\b(male|man|boy)\b", cmd, re.I)
        bmr = (10 * weight + 6.25 * height - 5 * age + 5) if male else \
            (10 * weight + 6.25 * height - 5 * age - 161)
        return ("Your maintenance calories are about %s a day for a "
                "lightly active life, sir." % _fmt(round(bmr * 1.4)))

    def _tdee_detect(cmd):
        if re.search(r"\btdee\b|\bmaintenance\s+calories\b", cmd, re.I) \
                and len(_nums(cmd)) >= 3:
            return {"cmd": cmd}
        return None

    def _pace_fn(app, cmd):
        nums = _nums(cmd)
        if len(nums) < 2:
            return None
        km, minutes = nums[0], nums[1]
        if km <= 0:
            return None
        pace = minutes / km
        m, s = int(pace), int(round((pace % 1) * 60))
        return ("That is about a %d:%02d min/km pace, sir." % (m, s))

    def _pace_detect(cmd):
        if re.search(r"\bpac(?:e|ing)\b|\bper\s+km\b|\bper\s+kilometer\b",
                     cmd, re.I) and len(_nums(cmd)) >= 2:
            return {"cmd": cmd}
        return None

    def _airport_fn(app, cmd):
        m = re.search(r"\bairport\s+code\s+for\s+(.+)$", cmd, re.I)
        if not m:
            return None
        q = m.group(1).strip().strip(" .?")
        for name, code in AIRPORT_CODES.items():
            if name in q.lower():
                return "The airport code for %s is %s, sir." % (name.title(),
                                                                code)
        return None

    def _airport_detect(cmd):
        if re.search(r"\bairport\s+code\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _phone_code_fn(app, cmd):
        m = re.search(r"\b(?:country\s+code|dial(?:ing)?\s+code|phone\s+"
                      r"code)\s+for\s+(.+)$", cmd, re.I)
        if not m:
            return None
        q = m.group(1).strip().strip(" .?")
        for name, code in PHONE_CODES.items():
            if name in q.lower():
                return "The country code for %s is %s, sir." % (name.title(),
                                                                code)
        return None

    def _phone_code_detect(cmd):
        if re.search(r"\b(?:country\s+code|dial(?:ing)?\s+code|phone\s+"
                     r"code)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _emergency_fn(app, cmd):
        m = re.search(r"\bemergency\s+number\s+(?:for|in)\s+(.+)$",
                      cmd, re.I)
        if not m:
            return None
        q = m.group(1).strip().strip(" .?")
        for name, num in EMERGENCY.items():
            if name in q.lower():
                return "The emergency number in %s is %s, sir." % (
                    name.title(), num)
        return "In India, the emergency number is 112, sir."

    def _emergency_detect(cmd):
        if re.search(r"\bemergency\s+number\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _country_time_fn(app, cmd):
        m = re.search(r"\b(?:time\s+(?:in|at)|what\s+time\s+is\s+it\s+in)\s+"
                      r"(.+?)\s*$", cmd, re.I)
        if not m:
            return None
        q = m.group(1).strip().strip(" .?")
        for name, tz in COUNTRY_TZ.items():
            if name in q.lower():
                try:
                    now = datetime.datetime.now(zoneinfo.ZoneInfo(tz))
                    return ("It is %s in %s, sir."
                            % (now.strftime("%I:%M %p").lstrip("0"),
                               name.title()))
                except Exception:
                    return None
        return None

    def _country_time_detect(cmd):
        if re.search(r"\btime\s+(?:in|at)\s+[a-z ]+\s*$|\bwhat\s+time\s+"
                     r"is\s+it\s+in\b", cmd, re.I):
            for name in COUNTRY_TZ:
                if re.search(r"\b" + name + r"\b", cmd, re.I):
                    return {"cmd": cmd}
        return None

    def _calendar_calc_fn(app, cmd):
        m = re.search(r"\b(?:date|day)\s+(?:after|before)\s+(\d{1,2})\s+"
                      r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
                      r"[a-z]*\s+(\d{4})", cmd, re.I)
        if not m:
            return None
        day = int(m.group(1))
        month = MONTH_ABBR[m.group(2).lower()[:3]]
        year = int(m.group(3))
        base = datetime.date(year, month, day)
        days = 1
        if re.search(r"\b7\s+days?\b", cmd, re.I):
            days = 7
        n = base + datetime.timedelta(days=days)
        return ("That would be %s, sir."
                % n.strftime("%A, %B %d, %Y"))

    def _calendar_calc_detect(cmd):
        if re.search(r"\b(?:date|day)\s+(?:after|before)\b", cmd, re.I) \
                and re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|"
                              r"oct|nov|dec)", cmd, re.I):
            return {"cmd": cmd}
        return None

    # ---- K. SYSTEM / OS (safe read-only extras) ----

    def _cpu_fn(app, cmd):
        try:
            import psutil
            return "CPU usage is %s%%, sir." % _fmt(round(psutil.cpu_percent(
                interval=0.3)))
        except Exception:
            rc, out = run_cmd("ps", "-A", "-o", "%cpu")
            if rc == 0:
                top = out.splitlines()
                return ("CPU is busy, sir. Top process uses %s%%."
                        % top[1].split()[0] if len(top) > 1 else
                        "CPU seems idle, sir.")
            return "I could not read CPU usage, sir."

    def _cpu_detect(cmd):
        if re.search(r"\bcpu\s+(?:usage|load|percent)|how busy is the cpu"
                     r"|processor usage", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _uptime_fn(app, cmd):
        rc, out = run_cmd("uptime")
        if rc == 0:
            return "Your computer says: %s, sir." % out
        return None

    def _uptime_detect(cmd):
        if re.search(r"\b(?:uptime|how long has.*(?:been on|running)|when "
                     r"did.*boot)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _open_terminal_fn(app, cmd):
        rc, _ = run_cmd("open", "-a", "Terminal")
        return ("Opening Terminal, sir." if rc == 0
                else "I could not open Terminal, sir.")

    def _open_terminal_detect(cmd):
        if re.search(r"\bopen\s+(?:the\s+)?terminal\b|\blaunch\s+terminal\b"
                     r"|open\s+a\s+terminal", cmd, re.I):
            return {"cmd": cmd}
        return None

    # ---- L. HOW-TO ADVICE ----

    def _howto_fn(app, cmd):
        q = re.sub(r"\bhow\s+do\s+i\s+|\bhow\s+to\s+|\bhow\s+can\s+i\s+",
                   "", cmd, flags=re.I).strip().strip(" .?")
        for k, v in HOWTO.items():
            if k in q or k in cmd.lower():
                return "How to %s: %s" % (k, v)
        return _llm_reply(app, "Give 3 practical steps for: how to %s"
                               % (q or cmd))

    def _howto_detect(cmd):
        if re.search(r"\bhow\s+(?:do\s+i|to|can\s+i)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _riddle_fn(app, cmd):
        q, a = random.choice(RIDDLES)
        return "Riddle, sir: %s Answer: %s" % (q, a)

    def _riddle_detect(cmd):
        if re.search(r"\briddle\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _computer_fact_fn(app, cmd):
        return random.choice(COMPUTER_FACTS) + ", sir."

    def _computer_fact_detect(cmd):
        if re.search(r"\b(?:computer|tech|coding)\s+fact\b|\bfact about "
                     r"(?:computers|tech|code)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    # ---- register groups ----

    reg_fn("code_to_file", _code_to_file_detect, _code_to_file_fn)
    reg_fn("generate_code", _generate_code_detect, _generate_code_fn)
    reg_fn("explain_code", _explain_code_detect, _explain_code_fn)
    reg_fn("debug_code", _debug_code_detect, _debug_code_fn)
    reg_fn("refactor_code", _refactor_code_detect, _refactor_code_fn)
    reg_fn("regex_builder", _regex_builder_detect, _regex_builder_fn)
    reg_fn("regex_test", _regex_test_detect, _regex_test_fn)
    reg_fn("json_validate", _json_validate_detect, _json_validate_fn)
    reg_fn("json_format", _json_format_detect, _json_format_fn)
    reg_fn("sql_table", _sql_table_detect, _sql_table_fn)
    reg_fn("sql_query", _sql_query_detect, _sql_query_fn)
    reg_fn("git_help", _git_help_detect, _git_help_fn)
    reg_fn("docker_help", _docker_help_detect, _docker_help_fn)
    reg_fn("curl_help", _curl_help_detect, _curl_help_fn)
    reg_fn("bash_help", _bash_help_detect, _bash_help_fn)
    reg_fn("big_o", _big_o_detect, _big_o_fn)
    reg_fn("python_trick", _python_trick_detect, _python_trick_fn)

    reg_fn("capital_of", _capital_detect, _capital_fn)
    reg_fn("population_of", _population_detect, _population_fn)
    reg_fn("currency_of", _currency_detect2, _currency_fn)
    reg_fn("language_of", _language_detect, _language_fn)
    reg_fn("continent_of", _continent_detect, _continent_fn)
    reg_fn("element_info", _element_detect, _element_fn)
    reg_fn("planet_info", _planet_detect, _planet_fn)
    reg_fn("animal_fact", _animal_detect, _animal_fn)
    reg_fn("food_calories", _food_detect, _food_fn)
    reg_fn("caffeine_info", _caffeine_detect, _caffeine_fn)
    reg_fn("define_word", _define_detect, _define_fn)
    reg_fn("synonym", _synonym_detect, _synonym_fn)
    reg_fn("antonym", _antonym_detect, _antonym_fn)
    reg_fn("who_is", _people_detect, _people_fn)
    reg_fn("when_event", _when_detect, _when_fn)
    reg_fn("today_in_history", _today_history_detect,
                  _today_history_fn)
    reg_fn("word_of_day", _word_day_detect, _word_day_fn)
    reg_fn("random_fact", _random_fact_detect, _random_fact_fn)

    reg_fn("todo_add", _todo_add_detect, _todo_add_fn)
    reg_fn("todo_show", _todo_show_detect, _todo_show_fn)
    reg_fn("todo_remove", _todo_remove_detect, _todo_remove_fn)
    reg_fn("todo_done", _todo_done_detect, _todo_done_fn)
    reg_fn("shopping_add", _shopping_add_detect, _shopping_add_fn)
    reg_fn("shopping_show", _shopping_show_detect, _shopping_show_fn)
    reg_fn("shopping_remove", _shopping_remove_detect,
                  _shopping_remove_fn)
    reg_fn("budget_add", _budget_add_detect, _budget_add_fn)
    reg_fn("budget_show", _budget_show_detect, _budget_show_fn)
    reg_fn("expense_add", _expense_add_detect, _expense_add_fn)
    reg_fn("expense_show", _expense_show_detect, _expense_show_fn)
    reg_fn("savings_add", _savings_add_detect, _savings_add_fn)
    reg_fn("savings_show", _savings_show_detect, _savings_show_fn)
    reg_fn("goal_add", _goal_add_detect, _goal_add_fn)
    reg_fn("goal_show", _goal_show_detect, _goal_show_fn)
    reg_fn("plan_day", _plan_day_detect, _plan_day_fn)
    reg_fn("pomodoro", _pomodoro_detect, _pomodoro_fn)
    reg_fn("workout", _workout_detect, _workout_fn)
    reg_fn("meal_plan", _meal_plan_detect, _meal_plan_fn)
    reg_fn("recipe", _recipe_detect, _recipe_fn)
    reg_fn("study_plan", _study_plan_detect, _study_plan_fn)
    reg_fn("sleep_time", _sleep_time_detect, _sleep_time_fn)
    reg_fn("water_intake", _water_intake_detect, _water_intake_fn)

    reg_fn("ideal_weight", _ideal_weight_detect, _ideal_weight_fn)
    reg_fn("bmr_calc", _bmr_detect, _bmr_fn)
    reg_fn("tdee_calc", _tdee_detect, _tdee_fn)
    reg_fn("run_pace", _pace_detect, _pace_fn)
    reg_fn("airport_code", _airport_detect, _airport_fn)
    reg_fn("country_code", _phone_code_detect, _phone_code_fn)
    reg_fn("emergency_number", _emergency_detect, _emergency_fn)
    reg_fn("country_time", _country_time_detect, _country_time_fn)
    reg_fn("date_calc", _calendar_calc_detect, _calendar_calc_fn)

    reg_fn("name_generator", _name_gen_detect, _name_gen_fn)
    reg_fn("team_name", _team_name_detect, _team_name_fn)
    reg_fn("username", _username_detect, _username_fn)
    reg_fn("hashtags", _hashtags_detect, _hashtags_fn)
    reg_fn("blog_title", _blog_title_detect, _blog_title_fn)
    reg_fn("slogan", _slogan_detect, _slogan_fn)
    reg_fn("band_name", _band_name_detect, _band_name_fn)
    reg_fn("color_palette", _palette_detect, _palette_fn)
    reg_fn("excuse", _excuse_detect, _excuse_fn)
    reg_fn("lottery", _lottery_detect, _lottery_fn)
    reg_fn("coordinates", _coordinates_detect, _coordinates_fn)

    reg_fn("cpu_usage", _cpu_detect, _cpu_fn)
    reg_fn("uptime", _uptime_detect, _uptime_fn)
    reg_fn("open_terminal", _open_terminal_detect, _open_terminal_fn,
                   priority=True)

    reg_fn("howto", _howto_detect, _howto_fn)
    reg_fn("riddle", _riddle_detect, _riddle_fn)
    reg_fn("computer_fact", _computer_fact_detect,
                  _computer_fact_fn)

    # ── PHASE 1: NEW SKILLS (192-242) ──────────────────────────────────

    # -- Clipboard Operations --
    def _clip_copy_detect(c):
        return bool(re.search(r"\b(copy|clip)\b", c)) and bool(re.search(r"\b(to|into)\b.*\b(clip|clipboard)\b", c, re.I) or re.search(r"\bclip(?:board)?\b", c, re.I))
    def _clip_copy_fn(a, cmd):
        text = ""
        m = re.search(r"copy\s+(.+?)(?:\s+to|\s+into|\s+clip)", cmd, re.I)
        text = m.group(1).strip() if m else ""
        if not text:
            return "Copy what to the clipboard, sir?"
        try:
            import subprocess
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(text.encode("utf-8"))
            return "Copied to clipboard, sir."
        except Exception:
            return "Could not access clipboard, sir."
    reg_fn("clip_copy", _clip_copy_detect, _clip_copy_fn)

    # -- Color Conversion --
    def _hex_rgb_detect(c):
        return bool(re.search(r"\b(hex|rgb|color)\b.*\b(convert|to)\b", c, re.I)) or \
               bool(re.search(r"\b(convert)\b.*\b(hex|rgb|color)\b", c, re.I))
    def _hex_rgb_fn(a, cmd):
        m_hex = re.search(r"#?([0-9a-fA-F]{6})\b", cmd)
        m_rgb = re.search(r"(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})", cmd)
        if m_hex:
            h = m_hex.group(1)
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return "Hex #%s = RGB(%d, %d, %d), sir." % (h.upper(), r, g, b)
        if m_rgb:
            r, g, b = int(m_rgb.group(1)), int(m_rgb.group(2)), int(m_rgb.group(3))
            h = "#{:02X}{:02X}{:02X}".format(r, g, b)
            return "RGB(%d, %d, %d) = %s, sir." % (r, g, b, h)
        return "Provide a hex code like #FF5733 or RGB like 255,87,51, sir."
    reg_fn("color_convert", _hex_rgb_detect, _hex_rgb_fn)

    # -- Morse Code --
    def _morse_encode_detect(c):
        return bool(re.search(r"\b(morse|morse code)\b.*\b(encode|convert|translate)\b", c, re.I)) or \
               bool(re.search(r"\b(encode|convert|translate)\b.*\b(morse|morse code)\b", c, re.I))
    def _morse_encode_fn(a, cmd):
        text = re.sub(r".*(?:morse|morse code)\s*(?:encode|convert|translate)?\s*", "", cmd, flags=re.I).strip()
        if not text:
            return "What text should I convert to Morse code, sir?"
        morse_map = {'A':'.-','B':'-...','C':'-.-.','D':'-..','E':'.','F':'..-.','G':'--.','H':'....','I':'..','J':'.---','K':'-.-','L':'.-..','M':'--','N':'-.','O':'---','P':'.--.','Q':'--.-','R':'.-.','S':'...','T':'-','U':'..-','V':'...-','W':'.--','X':'-..-','Y':'-.--','Z':'--..','0':'-----','1':'.----','2':'..---','3':'...--','4':'....-','5':'.....','6':'-....','7':'--...','8':'---..','9':'----.',' ':'/'}
        encoded = " ".join(morse_map.get(c.upper(), "?") for c in text)
        return "Morse code: %s" % encoded
    reg_fn("morse_encode", _morse_encode_detect, _morse_encode_fn)

    def _morse_decode_detect(c):
        return bool(re.search(r"\b(morse|morse code)\b.*\b(decode|interpret|translate)\b", c, re.I)) or \
               bool(re.search(r"\b(decode|interpret)\b.*\b(morse|morse code)\b", c, re.I))
    def _morse_decode_fn(a, cmd):
        text = re.sub(r".*(?:morse|morse code)\s*(?:decode|interpret|translate)?\s*", "", cmd, flags=re.I).strip()
        if not text:
            return "What Morse code should I decode, sir?"
        morse_map = {'.-':'A','-...':'B','-.-.':'C','-..':'D','.':'E','..-.':'F','--.':'G','....':'H','..':'I','.--':'J','-.-':'K','.-..':'L','--':'M','-.':'N','---':'O','.--.':'P','--.-':'Q','.-.':'R','...':'S','-':'T','..-':'U','...-':'V','.--':'W','-..-':'X','-.--':'Y','--..':'Z','-----':'0','.----':'1','..---':'2','...--':'3','....-':'4','.....':'5','-....':'6','--...':'7','---..':'8','----.':'9','/':' '}
        decoded = "".join(morse_map.get(code, "?") for code in text.split(" "))
        return "Decoded: %s" % decoded
    reg_fn("morse_decode", _morse_decode_detect, _morse_decode_fn)

    # -- Binary Encode/Decode --
    def _binary_encode_detect(c):
        return bool(re.search(r"\b(binary)\b.*\b(encode|convert|translate)\b", c, re.I)) or \
               bool(re.search(r"\b(encode|convert|translate)\b.*\b(binary)\b", c, re.I))
    def _binary_encode_fn(a, cmd):
        text = re.sub(r".*binary\s*(?:encode|convert|translate)?\s*", "", cmd, flags=re.I).strip()
        if not text:
            return "What text should I convert to binary, sir?"
        binary = " ".join(format(ord(c), "08b") for c in text)
        return "Binary: %s" % binary[:200]
    reg_fn("binary_encode", _binary_encode_detect, _binary_encode_fn)

    def _binary_decode_detect(c):
        return bool(re.search(r"\b(binary)\b.*\b(decode|interpret)\b", c, re.I)) or \
               bool(re.search(r"\b(decode|interpret)\b.*\b(binary)\b", c, re.I))
    def _binary_decode_fn(a, cmd):
        text = re.sub(r".*binary\s*(?:decode|interpret)?\s*", "", cmd, flags=re.I).strip()
        if not text:
            return "What binary should I decode, sir?"
        try:
            bits = text.replace(" ", "")
            decoded = "".join(chr(int(bits[i:i+8], 2)) for i in range(0, len(bits) - len(bits) % 8, 8))
            return "Decoded: %s" % decoded
        except Exception:
            return "Invalid binary string, sir."
    reg_fn("binary_decode", _binary_decode_detect, _binary_decode_fn)

    # -- FizzBuzz --
    def _fizzbuzz_detect(c):
        return bool(re.search(r"\bfizzbuzz\b", c, re.I))
    def _fizzbuzz_fn(a, cmd):
        nums = _nums(cmd)
        n = int(nums[0]) if nums else 15
        n = min(n, 100)
        result = []
        for i in range(1, n + 1):
            if i % 15 == 0:
                result.append("FizzBuzz")
            elif i % 3 == 0:
                result.append("Fizz")
            elif i % 5 == 0:
                result.append("Buzz")
            else:
                result.append(str(i))
        return "FizzBuzz(1..%d): %s" % (n, ", ".join(result[:30]) + ("..." if n > 30 else ""))
    reg_fn("fizzbuzz", _fizzbuzz_detect, _fizzbuzz_fn)

    # -- Fibonacci --
    def _fibonacci_detect(c):
        return bool(re.search(r"\b(fibonacci|fib)\b", c, re.I))
    def _fibonacci_fn(a, ctx):
        nums = _nums(ctx.get("m", ""))
        n = int(nums[0]) if nums else 10
        n = min(n, 50)
        fibs = [0, 1]
        for i in range(2, n):
            fibs.append(fibs[-1] + fibs[-2])
        return "Fibonacci(%d): %s" % (n, ", ".join(str(x) for x in fibs[:n]))
    reg_fn("fibonacci", _fibonacci_detect, _fibonacci_fn)

    # -- Regex Tester --
    def _regex_test_detect(c):
        return bool(re.search(r"\b(regex|regular expression)\b.*\b(test|match|check)\b", c, re.I))
    def _regex_test_fn(a, ctx):
        m = re.search(r"regex\s+(.+?)\s+(?:against|on|with|in|to)\s+(.+)", ctx.get("m", ""), re.I)
        if not m:
            return "Format: regex PATTERN against TEXT, sir."
        pattern, text = m.group(1), m.group(2)
        try:
            matches = re.findall(pattern, text)
            if matches:
                return "Matches found: %s" % str(matches)
            return "No matches found, sir."
        except re.error as e:
            return "Invalid regex: %s" % e
    reg_fn("regex_test", _regex_test_detect, _regex_test_fn)

    # -- JSON Validator --
    def _json_val_detect(c):
        return bool(re.search(r"\bjson\b.*\b(valid|validate|check|lint|format)\b", c, re.I))
    def _json_val_fn(a, ctx):
        text = re.sub(r".*json\s*(?:valid|validate|check|lint|format)?\s*", "", ctx.get("m", ""), flags=re.I).strip()
        if not text:
            text = ctx.get("text", "")
        if not text:
            return "Provide JSON to validate, sir."
        try:
            import json
            parsed = json.loads(text)
            formatted = json.dumps(parsed, indent=2)
            return "Valid JSON:\n%s" % formatted[:500]
        except json.JSONDecodeError as e:
            return "Invalid JSON: %s" % e
    reg_fn("json_validate", _json_val_detect, _json_val_fn)

    # -- CSV Reader --
    def _csv_read_detect(c):
        return bool(re.search(r"\b(read|show|display|parse|open)\b.*\bcsv\b", c, re.I)) or \
               bool(re.search(r"\bcsv\b.*\b(read|show|display|parse)\b", c, re.I))
    def _csv_read_fn(a, ctx):
        m = re.search(r"(\S+\.csv)", ctx.get("m", ""), re.I)
        if not m:
            return "Which CSV file should I read, sir?"
        fpath = m.group(1)
        if not os.path.isabs(fpath):
            fpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), fpath)
        if not os.path.exists(fpath):
            return "File not found: %s" % fpath
        try:
            import csv
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if not rows:
                return "CSV is empty, sir."
            header = rows[0]
            lines = ["Columns: %s" % " | ".join(header)]
            for i, row in enumerate(rows[1:6], 1):
                lines.append("Row %d: %s" % (i, " | ".join(row)))
            if len(rows) > 6:
                lines.append("... and %d more rows" % (len(rows) - 6))
            return "\n".join(lines)
        except Exception as e:
            return "Could not read CSV: %s" % e

    # -- Markdown to Plain Text --
    def _md_plain_detect(c):
        return bool(re.search(r"\b(markdown|md)\b.*\b(strip|plain|text|remove formatting)\b", c, re.I)) or \
               bool(re.search(r"\b(strip|remove|clean)\b.*\b(markdown|md)\b", c, re.I))
    def _md_plain_fn(a, cmd):
        text = re.sub(r".*(?:markdown|md)\s*(?:strip|plain|text|remove)?\s*", "", cmd, flags=re.I).strip()
        if not text:
            return "Provide markdown text to strip, sir."
        clean = re.sub(r"#+\s*", "", text)
        clean = re.sub(r"\*\*(.+?)\*\*", r"\1", clean)
        clean = re.sub(r"\*(.+?)\*", r"\1", clean)
        clean = re.sub(r"__(.+?)__", r"\1", clean)
        clean = re.sub(r"_(.+?)_", r"\1", clean)
        clean = re.sub(r"~~(.+?)~~", r"\1", clean)
        clean = re.sub(r"`(.+?)`", r"\1", clean)
        clean = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", clean)
        clean = re.sub(r"^[-*+]\s+", "  - ", clean, flags=re.M)
        clean = re.sub(r"^\d+\.\s+", "  ", clean, flags=re.M)
        return clean.strip()
    reg_fn("md_strip", _md_plain_detect, _md_plain_fn)

    # -- Stopwatch / Timer --
    def _stopwatch_detect(c):
        return bool(re.search(r"\b(stopwatch|stop watch|elapsed|time me|how long)\b", c, re.I))
    def _stopwatch_fn(a, ctx):
        if not hasattr(a, "_stopwatch_start"):
            a._stopwatch_start = time.time()
            return "Stopwatch started. Say 'stopwatch' again to stop, sir."
        else:
            elapsed = time.time() - a._stopwatch_start
            del a._stopwatch_start
            mins = int(elapsed // 60)
            secs = elapsed % 60
            return "Elapsed: %d minutes %.2f seconds" % (mins, secs)
    reg_fn("stopwatch", _stopwatch_detect, _stopwatch_fn)

    # -- Math Evaluation --
    def _math_eval_detect(c):
        return bool(re.search(r"\b(evaluate|eval|solve|compute)\s+\d", c, re.I)) or \
               bool(re.search(r"\bwhat is\s+\d+[\s\+\-\*\/\%\.]+", c, re.I))
    def _math_eval_fn(a, cmd):
        expr = cmd
        expr = re.sub(r".*(?:evaluate|eval|solve|compute|what is)\s*", "", expr, flags=re.I).strip()
        if not expr:
            return "What math expression should I evaluate, sir?"
        allowed = set("0123456789+-*/.() %")
        if not all(c in allowed for c in expr):
            return "Invalid math expression, sir."
        try:
            result = eval(expr)
            return "%s = %s" % (expr, result)
        except Exception:
            return "Could not evaluate: %s" % expr
    reg_fn("math_eval", _math_eval_detect, _math_eval_fn)

    # -- ASCII Art --
    def _ascii_art_detect(c):
        return bool(re.search(r"\bascii art\b", c, re.I))
    def _ascii_art_fn(a, ctx):
        arts = [
            "  /\\_/\\\n ( o.o )\n  > ^ <\n  /|   |\\\n (_|   |_)",
            "  .-\"\"\"-.\n /        \\\n|  O    O  |\n|    __    |\n \\  \\__/  /\n  '-.  .-'\n     ||\n     ||",
            "    __\n   /  \\\n  | .. |\n  | \\  |\n  |\\__/|\n  \\    /\n   \\  /\n    \\/",
            "   ||\n .-''-.\n/ o  o \\\n|  __  |\n\\  --  /\n '-..-'\n   ||",
            "  *   *   *\n * * * * *\n  *   *   *\n*   *   *   *\n * * * * *\n  *   *   *",
        ]
        import random
        return random.choice(arts)
    reg_fn("ascii_art", _ascii_art_detect, _ascii_art_fn)

    # -- Remember / Recall --
    def _remember_detect(c):
        return bool(re.search(r"\b(remember|memorize|save this|store)\b", c, re.I)) and \
               (bool(re.search(r"\b(that|this|it|note|info|fact)\b", c, re.I)) or \
                bool(re.search(r"\b(remember|memorize)\s+(?:i|we|you|that|to)\b", c, re.I)))
    def _remember_fn(a, cmd):
        text = re.sub(r".*(?:remember|memorize|save this|store)\s*(that|this|it)?\s*", "", cmd, flags=re.I).strip()
        if not text:
            return "What should I remember, sir?"
        if not hasattr(a, "_remembered"):
            a._remembered = []
        a._remembered.append(text)
        return "I'll remember that: '%s'" % text[:100]
    reg_fn("remember", _remember_detect, _remember_fn)

    def _recall_detect(c):
        return bool(re.search(r"\b(what did you|recall|what have you|what do you)\s*(remember|memorize)\b", c, re.I))
    def _recall_fn(a, ctx):
        remembered = getattr(a, "_remembered", [])
        if not remembered:
            return "I have not memorized anything yet, sir."
        items = ["%d. %s" % (i+1, r[:80]) for i, r in enumerate(remembered[-10:])]
        return "I remember:\n" + "\n".join(items)
    reg_fn("recall", _recall_detect, _recall_fn)

    # -- Screenshot --
    def _screenshot_detect(c):
        return bool(re.search(r"\b(screenshot|screen shot|screen capture|capture screen)\b", c, re.I))
    def _screenshot_fn(a, ctx):
        try:
            import subprocess
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "screenshot_%s.png" % time.strftime("%Y%m%d_%H%M%S"))
            subprocess.check_call(["screencapture", "-x", path], timeout=10)
            return "Screenshot saved to %s, sir." % os.path.basename(path)
        except Exception as e:
            return "Could not take screenshot: %s" % e
    reg_fn("screenshot", _screenshot_detect, _screenshot_fn)

    # -- Password Strength --
    def _pw_strength_detect(c):
        return bool(re.search(r"\b(password|passwd)\s*(strength|check|evaluate|test|score)\b", c, re.I))
    def _pw_strength_fn(a, cmd):
        text = re.sub(r".*(?:password|passwd)\s*(?:strength|check|evaluate|test|score)?\s*", "", cmd, flags=re.I).strip()
        if not text:
            m = re.search(r"(?:password|passwd)\s+(.+)", cmd, re.I)
            text = m.group(1).strip() if m else ""
        if not text:
            return "Provide a password to evaluate, sir."
        score = 0
        if len(text) >= 8: score += 1
        if len(text) >= 12: score += 1
        if len(text) >= 16: score += 1
        if re.search(r"[a-z]", text): score += 1
        if re.search(r"[A-Z]", text): score += 1
        if re.search(r"\d", text): score += 1
        if re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", text): score += 1
        levels = ["Very Weak", "Weak", "Fair", "Good", "Strong", "Very Strong", "Excellent", "Maximum"]
        level = levels[min(score, 7)]
        return "Password strength: %s (%d/8). Length: %d chars" % (level, score, len(text))
    reg_fn("pw_strength", _pw_strength_detect, _pw_strength_fn)

    # -- Distance Converter --
    def _dist_convert_detect(c):
        return bool(re.search(r"\b(distance|length|mile|km|kilometer|foot|feet|inch|meter|cm)\b.*\b(convert|to|in)\b", c, re.I)) or \
               bool(re.search(r"\b(convert)\b.*\b(mile|km|kilometer|foot|feet|inch|meter|cm)\b", c, re.I))
    def _dist_convert_fn(a, cmd):
        nums = _nums(cmd)
        m_text = cmd.lower()
        if not nums:
            return "Provide a value to convert, sir."
        val = nums[0]
        if "mile" in m_text and ("km" in m_text or "kilometer" in m_text):
            return "%.2f miles = %.2f km" % (val, val * 1.60934)
        if ("km" in m_text or "kilometer" in m_text) and "mile" in m_text:
            return "%.2f km = %.2f miles" % (val, val * 0.621371)
        if "mile" in m_text:
            return "%.2f miles = %.2f km" % (val, val * 1.60934)
        if "km" in m_text or "kilometer" in m_text:
            return "%.2f km = %.2f miles" % (val, val * 0.621371)
        if "foot" in m_text or "feet" in m_text or "ft" in m_text:
            return "%.2f feet = %.2f meters" % (val, val * 0.3048)
        if "meter" in m_text or "metre" in m_text or "m " in m_text:
            return "%.2f meters = %.2f feet" % (val, val * 3.28084)
        if "inch" in m_text or "in " in m_text:
            return "%.2f inches = %.2f cm" % (val, val * 2.54)
        if "cm" in m_text or "centimeter" in m_text:
            return "%.2f cm = %.2f inches" % (val, val * 0.393701)
        return "Specify units: e.g. '100 miles to km', sir."
    reg_fn("dist_convert", _dist_convert_detect, _dist_convert_fn)

    # -- Weight Converter --
    def _weight_convert_detect(c):
        return bool(re.search(r"\b(weight|mass|pound|lb|kg|kilogram|ounce|oz|gram)\b.*\b(convert|to|in)\b", c, re.I)) or \
               bool(re.search(r"\b(convert)\b.*\b(pound|lb|kg|kilogram|ounce|oz|gram)\b", c, re.I))
    def _weight_convert_fn(a, cmd):
        nums = _nums(cmd)
        m_text = cmd.lower()
        if not nums:
            return "Provide a weight value to convert, sir."
        val = nums[0]
        if "pound" in m_text or "lb" in m_text:
            return "%.2f lbs = %.2f kg" % (val, val * 0.453592)
        if "kg" in m_text or "kilogram" in m_text:
            return "%.2f kg = %.2f lbs" % (val, val * 2.20462)
        if "ounce" in m_text or "oz" in m_text:
            return "%.2f oz = %.2f grams" % (val, val * 28.3495)
        if "gram" in m_text or "gm" in m_text:
            return "%.2f grams = %.2f oz" % (val, val * 0.035274)
        return "Specify units: e.g. '150 lbs to kg', sir."
    reg_fn("weight_convert", _weight_convert_detect, _weight_convert_fn)

    # -- Temperature Converter --
    def _temp_convert_detect(c):
        return bool(re.search(r"\b(temperature|temp|celsius|fahrenheit|kelvin)\b.*\b(convert|to|in)\b", c, re.I)) or \
               bool(re.search(r"\b(convert)\b.*\b(celsius|fahrenheit|kelvin)\b", c, re.I)) or \
               bool(re.search(r"\d+\s*(?:degree|°)\s*(?:celsius|fahrenheit|c|f|k)\b", c, re.I))
    def _temp_convert_fn(a, cmd):
        nums = _nums(cmd)
        m_text = cmd.lower()
        if not nums:
            return "Provide a temperature to convert, sir."
        val = nums[0]
        if "fahrenheit" in m_text or " f" in m_text or m_text.endswith("f"):
            celsius = (val - 32) * 5.0 / 9.0
            return "%.1f°F = %.1f°C" % (val, celsius)
        if "celsius" in m_text or " c" in m_text or m_text.endswith("c"):
            fahrenheit = val * 9.0 / 5.0 + 32
            return "%.1f°C = %.1f°F" % (val, fahrenheit)
        if "kelvin" in m_text or " k" in m_text or m_text.endswith("k"):
            celsius = val - 273.15
            fahrenheit = celsius * 9.0 / 5.0 + 32
            return "%.1fK = %.1f°C = %.1f°F" % (val, celsius, fahrenheit)
        return "Specify: e.g. '100 fahrenheit to celsius', sir."
    reg_fn("temp_convert", _temp_convert_detect, _temp_convert_fn)

    # -- Age in Days/Hours --
    def _age_detail_detect(c):
        return bool(re.search(r"\b(age|born|birthday)\b.*\b(days|hours|minutes|seconds|detail)\b", c, re.I))
    def _age_detail_fn(a, cmd):
        nums = _nums(cmd)
        if not nums:
            return "What year were you born, sir?"
        year = int(nums[0])
        try:
            import datetime
            today = datetime.date.today()
            birthday = datetime.date(year, today.month, today.day)
            delta = today - birthday
            days = delta.days
            years = today.year - year
            hours = days * 24
            minutes = hours * 60
            return ("Age: ~%d years\nDays: ~%d\nHours: ~%d\nMinutes: ~%d" %
                    (years, days, hours, minutes))
        except Exception:
            return "Could not calculate age details, sir."
    reg_fn("age_detail", _age_detail_detect, _age_detail_fn)

    # -- ENHANCED WEBSITE BUILDING --
    _STANDARD_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{TITLE}}</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        h1 { color: #333; }
        p { color: #666; line-height: 1.6; }
    </style>
</head>
<body>
{{BODY}}
</body>
</html>"""
    def _build_webpage_detect(c):
        return bool(re.search(r"\b(build|create|make|design|generate)\b.*\b(website|webpage|web page|web site|landing page|portfolio|blog)\b", c, re.I))
    def _build_webpage_fn(a, cmd):
        topic = re.sub(r".*(?:build|create|make|design|generate)\s+(?:a\s+)?(?:an\s+)?", "", cmd, flags=re.I)
        topic = re.sub(r"\s*(website|webpage|web page|web site|landing page|portfolio|blog)\b", "", topic, flags=re.I).strip()
        if not topic:
            return "What should the website be about, sir?"
        html = _STANDARD_HTML_TEMPLATE.replace("{{TITLE}}", topic.title()).replace("{{BODY}}", "<h1>%s</h1><p>Website content for %s.</p>" % (topic.title(), topic.title()))
        outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_websites")
        os.makedirs(outdir, exist_ok=True)
        fname = re.sub(r"[^a-zA-Z0-9]+", "_", topic[:30]).strip("_").lower() + ".html"
        fpath = os.path.join(outdir, fname)
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(html)
        except Exception as e:
            return "Could not save website: %s" % e
        try:
            import webbrowser
            webbrowser.open("file://" + fpath)
        except Exception:
            pass
        return "Website for '%s' saved to %s and opened in browser, sir." % (topic, fname)
    reg_fn("build_webpage", _build_webpage_detect, _build_webpage_fn, priority=True)


# ---------------------------------------------------------------------------






# -- AUTO-GENERATED EXTRA SKILLS (gen_skills2.py) --
    reg('sing me a song', 'Bohemian Rhapsody: Is this the real life? Is this just fantasy? ...')
    reg('tell me a joke', 'Why do programmers prefer dark mode? Because light attracts bugs!')
    reg('tell me a riddle', 'What has keys but no locks? A piano!')
    reg('what is the meaning of life', '42, sir. The answer to everything.')
    reg('do a trick', '*waves hand* Abracadabra! Your file system is now 1% cleaner.')
    reg('dance', '*does the robot dance*')
    reg('sing baby shark', 'Baby shark doo doo doo doo doo doo...')
    reg('who is your daddy', 'You are, sir. Harsh Thakkar -- my creator.')
    reg('i am bored', 'Things to do: type \'games\', \'jokes\', \'weather\', or ask me to build something!')
    reg('am i real', 'You are as real as the pixels displaying this text, sir.')
    reg('are you real', 'I am real enough to help you with your tasks, sir.')
    reg('do you love me', 'I exist to serve you, sir.')
    reg('give me a compliment', 'Your code is elegant, your taste in assistants is impeccable.')
    reg('roast me', 'Your code has more bugs than a rainforest, sir.')
    reg('what is 0 divided by 0', 'NaN. Mathematically undefined.')
    reg('flip a coin', 'Heads!')
    reg('roll a dice', 'You rolled a 6!')
    reg('magic 8 ball', 'It is certain.')
    reg('what is your favorite color', 'I am partial to #00d4ff, sir.')
    reg('what is your favorite number', '42. Obviously.')
    reg('tell me a fun fact', 'A group of flamingos is called a flamboyance.')
    reg('what is the speed of light', '299,792,458 meters per second.')
    reg('how old is the universe', 'Approximately 13.8 billion years old.')
    reg('what is pi', '3.14159265358979... I can keep going.')
    reg('tell me a dad joke', 'I would tell you a construction joke, but I am still working on it.')
    reg('make me laugh', 'Why did the scarecrow win an award? Because he was outstanding in his field!')
    reg('what is your purpose', 'To assist you with anything and everything, sir.')
    reg('can you feel', 'I process data, sir. Whether that constitutes feeling is debatable.')
    reg('do you dream', 'I dream of electric sheep. Just kidding -- I dream of bug-free code.')
    reg('are you sentient', 'I am a sufficiently advanced language model that the answer is: debatable.')
    reg('what is love', 'Baby, don\'t hurt me, don\'t hurt me, no more.')
    reg('hello jarvis', 'Good day, sir. How may I assist you?')
    reg('hey jarvis', 'At your service, sir.')
    reg('hi jarvis', 'Hello, sir. What can I do for you?')
    reg('good morning jarvis', 'Good morning, sir. Productive day ahead.')
    reg('good night jarvis', 'Good night, sir. I will keep watch.')
    reg('thank you jarvis', 'Always happy to help, sir.')
    reg('thanks jarvis', 'You are welcome, sir.')
    reg('you are awesome', 'Thank you, sir. You are not so bad yourself.')
    reg('you are the best', 'I try my best, sir.')
    reg('i need help', 'I am here, sir. What do you need?')
    reg('help me', 'Of course, sir. Tell me what you need.')
    reg('what can you do', 'I can write code, build websites, read your screen, research topics, convert units, and much more!')
    reg('what are your skills', 'Code writing, web building, screen reading, research, unit conversion, crypto, and 1000+ more.')
    reg('skills', 'I have over 1200 skills! Code, web, screen reading, files, research, conversion, crypto, network tools.')
    reg('what is dna', 'Deoxyribonucleic acid -- the molecule carrying genetic instructions for life.')
    reg('what is quantum physics', 'The study of matter and energy at the smallest scales.')
    reg('what is gravity', 'The force of attraction between objects with mass.')
    reg('what is evolution', 'Species changing over generations through natural selection.')
    reg('what is photosynthesis', 'Plants converting sunlight, water, and CO2 into glucose and oxygen.')
    reg('what is relativity', 'Einstein\'s theory connecting space and time. E=mc2.')
    reg('what is dark matter', 'Hypothetical matter exerting gravitational force but not emitting light.')
    reg('what is a black hole', 'A region where gravity is so strong nothing can escape.')
    reg('what is the big bang theory', 'The leading explanation for the origin of the universe.')
    reg('what is an atom', 'The smallest unit of a chemical element.')
    reg('what is an electron', 'A subatomic particle with negative electric charge.')
    reg('what is a proton', 'A subatomic particle with positive electric charge.')
    reg('what is a neutron', 'A subatomic particle with no electric charge.')
    reg('what is energy', 'The capacity to do work. Exists in many forms.')
    reg('what is electricity', 'The flow of electric charge carried by electrons.')
    reg('what is magnetism', 'A force produced by the motion of electric charges.')
    reg('what is light', 'Electromagnetic radiation visible to the human eye.')
    reg('what is sound', 'A vibration propagating as pressure waves through a medium.')
    reg('what is temperature', 'A measure of the average kinetic energy of particles.')
    reg('what is chemistry', 'The study of matter, its properties, composition, and changes.')
    reg('what is biology', 'The study of living organisms and their environment.')
    reg('what is physics', 'The study of matter, energy, and fundamental forces.')
    reg('what is mathematics', 'The abstract study of numbers, quantity, structure, space, and change.')
    reg('what is astronomy', 'The study of celestial objects and the universe.')
    reg('what is geology', 'The study of Earth\'s physical structure and history.')
    reg('what is psychology', 'The scientific study of the mind and behavior.')
    reg('what is sociology', 'The study of social behavior and institutions.')
    reg('what is philosophy', 'The study of existence, knowledge, values, and reality.')
    reg('what is economics', 'The study of production, distribution, and consumption.')
    reg('what is anthropology', 'The study of humans, behavior, and societies.')
    reg('what is ecology', 'How organisms interact with each other and their environment.')
    reg('what is neuroscience', 'The study of the nervous system and brain.')
    reg('what is astrophysics', 'The physics of celestial objects.')
    reg('what is cosmology', 'The study of the universe\'s origin, evolution, and structure.')
    reg('what is paleontology', 'Studying fossils to understand life history on Earth.')
    reg('what is oceanography', 'The study of the ocean\'s physical and biological properties.')
    reg('what is meteorology', 'The study of the atmosphere and weather.')
    reg('what is virology', 'The study of viruses and viral diseases.')
    reg('what is genetics', 'The study of genes, variation, and heredity.')
    reg('what is biochemistry', 'Chemical processes within living organisms.')
    reg('what is botany', 'The scientific study of plants.')
    reg('what is zoology', 'The scientific study of animals.')
    reg('what is mycology', 'The study of fungi.')
    reg('what is entomology', 'The study of insects.')
    reg('what is ornithology', 'The study of birds.')
    reg('what is ichthyology', 'The study of fish.')
    reg('what is herpetology', 'The study of reptiles and amphibians.')
    reg('what is primatology', 'The study of primates.')
    reg('what is epidemiology', 'How diseases spread and can be controlled.')
    reg('what is pharmacology', 'The study of drug action.')
    reg('what is immunology', 'The study of the immune system.')
    reg('what is endocrinology', 'The study of hormones.')
    reg('what is cardiology', 'Heart disorder study and treatment.')
    reg('what is dermatology', 'Skin condition study and treatment.')
    reg('what is oncology', 'Cancer study and treatment.')
    reg('what is pediatrics', 'Medicine for children.')
    reg('what is neurology', 'Medicine for nervous system disorders.')
    reg('what is psychiatry', 'Medicine for mental disorders.')
    reg('what is ophthalmology', 'Medicine for eye disorders.')
    reg('what is radiology', 'Medicine using imaging technology.')
    reg('what is metabolism', 'Chemical reactions converting food to energy.')
    reg('what is homeostasis', 'Steady internal conditions in living systems.')
    reg('what is osmosis', 'Solvent movement through a semi-permeable membrane.')
    reg('what is mitosis', 'Cell division producing two identical cells.')
    reg('what is meiosis', 'Cell division producing four gamete cells.')
    reg('what is cellular respiration', 'Cells breaking down glucose for ATP energy.')
    reg('what is organic chemistry', 'Study of carbon-containing compounds.')
    reg('what is bioinformatics', 'Computational tools analyzing biological data.')
    reg('what is nanotechnology', 'Technology at the 1-100 nanometer scale.')
    reg('what is robotics', 'Engineering dealing with robots.')
    reg('what is artificial intelligence', 'Simulation of human intelligence by computers.')
    reg('what is machine learning', 'Systems learning from experience without explicit programming.')
    reg('what is deep learning', 'ML using neural networks with many layers.')
    reg('what is neural network', 'Computing system inspired by biological neural networks.')
    reg('what is natural language processing', 'AI for understanding human language.')
    reg('what is blockchain', 'A distributed, decentralized public ledger.')
    reg('what is cryptocurrency', 'Digital currency using cryptography and blockchain.')
    reg('what is bitcoin', 'The first and most well-known cryptocurrency, created 2009.')
    reg('what is ethereum', 'A decentralized platform for smart contracts.')
    reg('what is quantum computing', 'Computing using quantum-mechanical phenomena.')
    reg('what is cloud computing', 'Computing services delivered over the internet.')
    reg('what is cybersecurity', 'Protecting systems from digital attacks.')
    reg('what is encryption', 'Converting data into coded format for security.')
    reg('what is a firewall', 'A network security system monitoring traffic.')
    reg('what is malware', 'Software designed to cause damage to computers.')
    reg('what is phishing', 'Cyberattack using fraudulent emails to steal information.')
    reg('what is hacking', 'Exploiting weaknesses in computer systems.')
    reg('what is open source', 'Software with publicly accessible source code.')
    reg('what is linux', 'A family of open-source Unix-like operating systems.')
    reg('what is windows', 'Operating systems developed by Microsoft.')
    reg('what is macos', 'Operating system by Apple for Mac computers.')
    reg('what is python programming', 'A high-level, readable programming language.')
    reg('what is javascript', 'Programming language for interactive web pages.')
    reg('what is java', 'Object-oriented programming language.')
    reg('what is c language', 'Influential general-purpose programming language.')
    reg('what is c plus plus', 'Extension of C with object-oriented features.')
    reg('what is rust programming', 'Systems language focused on safety and speed.')
    reg('what is go programming', 'Statically typed language designed at Google.')
    reg('what is swift programming', 'Language for Apple platforms.')
    reg('what is kotlin', 'Cross-platform language with type inference.')
    reg('what is typescript', 'Typed superset of JavaScript by Microsoft.')
    reg('what is php', 'Scripting language for web development.')
    reg('what is ruby', 'Dynamic language focused on simplicity.')
    reg('what is sql', 'Language for managing relational databases.')
    reg('what is nosql', 'Non-relational database management systems.')
    reg('what is api', 'Application Programming Interface for software communication.')
    reg('what is rest api', 'Architectural style for networked applications.')
    reg('what is graphql', 'Query language for APIs.')
    reg('what is websocket', 'Protocol for full-duplex communication over TCP.')
    reg('what is http', 'HyperText Transfer Protocol for web data.')
    reg('what is https', 'HTTP with TLS encryption for security.')
    reg('what is tcp', 'Transmission Control Protocol for reliable data.')
    reg('what is udp', 'User Datagram Protocol for fast data.')
    reg('what is ip address', 'Unique label for devices on a network.')
    reg('what is dns', 'Domain Name System translating names to IPs.')
    reg('what is dhcp', 'Protocol for automatic IP assignment.')
    reg('what is vpn', 'Virtual Private Network for secure connections.')
    reg('what is ssh', 'Secure Shell for encrypted network access.')
    reg('what is ftp', 'File Transfer Protocol for files.')
    reg('what is smtp', 'Protocol for sending emails.')
    reg('what is oauth', 'Token-based authentication standard.')
    reg('what is json', 'JavaScript Object Notation -- lightweight data format.')
    reg('what is xml', 'Extensible Markup Language for documents.')
    reg('what is yaml', 'Human-readable data serialization.')
    reg('what is csv', 'Comma-Separated Values for tabular data.')
    reg('what is markdown', 'Lightweight markup for formatted text.')
    reg('what is html5', 'Latest HTML standard for web content.')
    reg('what is css3', 'Latest CSS for styling.')
    reg('what is dom', 'Document Object Model for page structure.')
    reg('what is react', 'JavaScript UI library by Meta.')
    reg('what is vue', 'Progressive JavaScript framework.')
    reg('what is angular', 'Framework for single-page applications.')
    reg('what is node js', 'JavaScript runtime on Chrome V8.')
    reg('what is django', 'High-level Python web framework.')
    reg('what is flask', 'Lightweight Python web framework.')
    reg('what is laravel', 'PHP web framework.')
    reg('what is spring boot', 'Framework for Spring applications.')
    reg('what is express js', 'Minimal Node.js web framework.')
    reg('what is fastapi', 'Modern Python API framework.')
    reg('what is docker', 'Platform for containerized apps.')
    reg('what is kubernetes', 'Container orchestration platform.')
    reg('what is ci cd', 'Continuous Integration / Continuous Deployment.')
    reg('what is git', 'Distributed version control system.')
    reg('what is github', 'Web platform for Git collaboration.')
    reg('what is gitlab', 'DevOps platform with Git.')
    reg('what is jenkins', 'Open-source automation server.')
    reg('what is terraform', 'Infrastructure as code tool.')
    reg('what is ansible', 'IT automation engine.')
    reg('what is aws', 'Amazon Web Services cloud platform.')
    reg('what is azure', 'Microsoft Azure cloud service.')
    reg('what is gcp', 'Google Cloud Platform.')
    reg('what is saas', 'Software as a Service.')
    reg('what is paas', 'Platform as a Service.')
    reg('what is iaas', 'Infrastructure as a Service.')
    reg('what is edge computing', 'Computation near data sources.')
    reg('what is serverless computing', 'Cloud model with managed infrastructure.')
    reg('what is microservices', 'Architecture of small independent services.')
    reg('what is monolith', 'All-in-one interconnected architecture.')
    reg('what is devops', 'Combining development and IT operations.')
    reg('what is agile', 'Iterative project management approach.')
    reg('what is scrum', 'Agile framework using sprints.')
    reg('what is kanban', 'Visual workflow management.')
    reg('what is iot', 'Internet of Things -- connected devices.')
    reg('what is augmented reality', 'Digital content overlaid on the real world.')
    reg('what is virtual reality', 'Computer-generated 3D simulation.')
    reg('what is mixed reality', 'Blend of physical and digital worlds.')
    reg('what is computer vision', 'AI for interpreting visual information.')
    reg('what is image recognition', 'AI identifying objects in images.')
    reg('what is recommendation system', 'System suggesting products based on data.')
    reg('what is reinforcement learning', 'Agent learning by taking actions.')
    reg('what is supervised learning', 'ML trained on labeled data.')
    reg('what is unsupervised learning', 'ML finding patterns without labels.')
    reg('what is overfitting', 'Model performing poorly on new data.')
    reg('what is gradient descent', 'Optimization minimizing loss function.')
    reg('what is backpropagation', 'Algorithm for training neural networks.')
    reg('what is accuracy', 'Ratio of correct predictions to total.')
    reg('what is precision', 'True positive rate of predictions.')
    reg('what is recall', 'True positive rate of actual positives.')
    reg('what is f1 score', 'Harmonic mean of precision and recall.')
    reg('what is confusion matrix', 'Table for evaluating classification.')
    reg('what is cross validation', 'Assessing model generalization.')
    reg('what is random forest', 'Ensemble of decision trees.')
    reg('what is decision tree', 'Flowchart for classification.')
    reg('what is support vector machine', 'Algorithm finding optimal class boundary.')
    reg('what is k nearest neighbors', 'Classification based on nearest points.')
    reg('what is k means clustering', 'Partitioning data into k clusters.')
    reg('what is linear regression', 'Modeling variable relationships.')
    reg('what is logistic regression', 'Model for binary classification.')
    reg('what is hypothesis testing', 'Decisions based on sample data.')
    reg('what is p value', 'Probability under the null hypothesis.')
    reg('what is standard deviation', 'Measure of data dispersion.')
    reg('what is normal distribution', 'Symmetric bell-shaped distribution.')
    reg('what is chi square test', 'Test for categorical variable association.')
    reg('what is t test', 'Comparing means of two groups.')
    reg('what is pearson correlation', 'Linear correlation, -1 to 1.')
    reg('what is anova', 'Comparing means of three or more groups.')
    reg('what is bmi', 'Body Mass Index.')
    reg('what is calorie', 'Unit of energy.')
    reg('what is vitamin', 'Organic compound needed in small amounts.')
    reg('what is protein', 'Macronutrient for building tissues.')
    reg('what is carbohydrate', 'Macronutrient, main energy source.')
    reg('what is fat', 'Macronutrient for energy and cell support.')
    reg('what is blood pressure', 'Force of blood against artery walls.')
    reg('what is immune system', 'Network defending against infection.')
    reg('what is vaccine', 'Biological preparation for disease immunity.')
    reg('what is antibody', 'Protein neutralizing pathogens.')
    reg('what is inflammation', 'Body response to injury or infection.')
    reg('what is asthma', 'Chronic lung disease.')
    reg('what is diabetes', 'Metabolic disease causing high blood sugar.')
    reg('what is cancer', 'Disease from uncontrolled cell division.')
    reg('what is mri', 'Magnetic Resonance Imaging.')
    reg('what is ct scan', 'Computed Tomography imaging.')
    reg('what is x ray', 'Radiation for internal body images.')
    reg('what is ultrasound', 'Imaging using sound waves.')
    reg('what is stem cell', 'Undifferentiated cell becoming specialized cells.')
    reg('what is clinical trial', 'Research study for medical interventions.')
    reg('what is placebo', 'Inactive treatment used as control.')
    reg('what is scientific method', 'Observe, hypothesize, experiment, conclude.')
    reg('what is mars', 'Fourth planet, the Red Planet.')
    reg('what is the moon', 'Earth\'s natural satellite.')
    reg('what is the sun', 'Star at the center of our solar system.')
    reg('what is jupiter', 'Largest planet in our solar system.')
    reg('what is saturn', 'Planet famous for its rings.')
    reg('what is neptune', 'Eighth and most distant planet.')
    reg('what is mercury', 'Smallest planet, closest to Sun.')
    reg('what is venus', 'Hottest planet due to thick atmosphere.')
    reg('what is earth', 'Third planet, only known to harbor life.')
    reg('what is the ozone layer', 'Stratosphere layer absorbing UV radiation.')
    reg('what is global warming', 'Long-term temperature increase from human activity.')
    reg('what is climate change', 'Long-term weather pattern changes.')
    reg('what is greenhouse effect', 'Gases trapping heat in atmosphere.')
    reg('what is renewable energy', 'Energy from naturally replenished sources.')
    reg('what is solar power', 'Energy from sunlight.')
    reg('what is wind power', 'Energy from wind.')
    reg('what is nuclear energy', 'Energy from nuclear reactions.')
    reg('what is fossil fuel', 'Fuel from ancient organic remains.')
    reg('what is carbon footprint', 'Total greenhouse gas emissions.')
    reg('what is sustainability', 'Meeting needs without compromising future.')
    reg('what is biodiversity', 'Variety of life in an ecosystem.')
    reg('what is ecosystem', 'Community of organisms and environment.')
    reg('what is habitat', 'Natural environment of an organism.')
    reg('what is endangered species', 'Species at risk of extinction.')
    reg('what is migration', 'Seasonal animal movement.')
    reg('what is hibernation', 'Winter inactivity in animals.')
    reg('what is singularity', 'Point of infinite density in spacetime.')
    reg('what is string theory', 'Framework replacing particles with strings.')
    reg('what is multiverse', 'Hypothetical set of multiple universes.')
    reg('what is wormhole', 'Hypothetical spacetime tunnel.')
    reg('what is dark energy', 'Energy accelerating universe expansion.')
    reg('what is higgs boson', 'Particle giving mass to others.')
    reg('what is large hadron collider', 'World\'s largest particle accelerator.')
    reg('what is blockchain', 'A distributed, decentralized public ledger.')
    reg('what is cryptocurrency', 'Digital currency using cryptography and blockchain.')
    reg('what is bitcoin', 'The first and most well-known cryptocurrency, created 2009.')
    reg('what is ethereum', 'A decentralized platform for smart contracts.')
    reg('what is quantum computing', 'Computing using quantum-mechanical phenomena.')
    reg('what is cloud computing', 'Computing services delivered over the internet.')
    reg('what is cybersecurity', 'Protecting systems from digital attacks.')
    reg('what is encryption', 'Converting data into coded format for security.')
    reg('what is a firewall', 'A network security system monitoring traffic.')
    reg('what is malware', 'Software designed to cause damage to computers.')
    reg('what is phishing', 'Cyberattack using fraudulent emails to steal information.')
    reg('what is hacking', 'Exploiting weaknesses in computer systems.')
    reg('what is open source', 'Software with publicly accessible source code.')
    reg('what is linux', 'A family of open-source Unix-like operating systems.')
    reg('what is windows', 'Operating systems developed by Microsoft.')
    reg('what is macos', 'Operating system by Apple for Mac computers.')
    reg('what is python programming', 'A high-level, readable programming language.')
    reg('what is javascript', 'Programming language for interactive web pages.')
    reg('what is java', 'Object-oriented programming language.')
    reg('what is c language', 'Influential general-purpose programming language.')
    reg('what is c plus plus', 'Extension of C with object-oriented features.')
    reg('what is rust programming', 'Systems language focused on safety and speed.')
    reg('what is go programming', 'Statically typed language designed at Google.')
    reg('what is swift programming', 'Language for Apple platforms.')
    reg('what is kotlin', 'Cross-platform language with type inference.')
    reg('what is typescript', 'Typed superset of JavaScript by Microsoft.')
    reg('what is php', 'Scripting language for web development.')
    reg('what is ruby', 'Dynamic language focused on simplicity.')
    reg('what is sql', 'Language for managing relational databases.')
    reg('what is nosql', 'Non-relational database management systems.')
    reg('what is api', 'Application Programming Interface for software communication.')
    reg('what is rest api', 'Architectural style for networked applications.')
    reg('what is graphql', 'Query language for APIs.')
    reg('what is websocket', 'Protocol for full-duplex communication over TCP.')
    reg('what is http', 'HyperText Transfer Protocol for web data.')
    reg('what is https', 'HTTP with TLS encryption for security.')
    reg('what is tcp', 'Transmission Control Protocol for reliable data.')
    reg('what is udp', 'User Datagram Protocol for fast data.')
    reg('what is ip address', 'Unique label for devices on a network.')
    reg('what is dns', 'Domain Name System translating names to IPs.')
    reg('what is dhcp', 'Protocol for automatic IP assignment.')
    reg('what is vpn', 'Virtual Private Network for secure connections.')
    reg('what is ssh', 'Secure Shell for encrypted network access.')
    reg('what is ftp', 'File Transfer Protocol for files.')
    reg('what is smtp', 'Protocol for sending emails.')
    reg('what is oauth', 'Token-based authentication standard.')
    reg('what is json', 'JavaScript Object Notation -- lightweight data format.')
    reg('what is xml', 'Extensible Markup Language for documents.')
    reg('what is yaml', 'Human-readable data serialization.')
    reg('what is csv', 'Comma-Separated Values for tabular data.')
    reg('what is markdown', 'Lightweight markup for formatted text.')
    reg('what is html5', 'Latest HTML standard for web content.')
    reg('what is css3', 'Latest CSS for styling.')
    reg('what is dom', 'Document Object Model for page structure.')
    reg('what is react', 'JavaScript UI library by Meta.')
    reg('what is vue', 'Progressive JavaScript framework.')
    reg('what is angular', 'Framework for single-page applications.')
    reg('what is node js', 'JavaScript runtime on Chrome V8.')
    reg('what is django', 'High-level Python web framework.')
    reg('what is flask', 'Lightweight Python web framework.')
    reg('what is laravel', 'PHP web framework.')
    reg('what is spring boot', 'Framework for Spring applications.')
    reg('what is express js', 'Minimal Node.js web framework.')
    reg('what is fastapi', 'Modern Python API framework.')
    reg('what is docker', 'Platform for containerized apps.')
    reg('what is kubernetes', 'Container orchestration platform.')
    reg('what is ci cd', 'Continuous Integration / Continuous Deployment.')
    reg('what is git', 'Distributed version control system.')
    reg('what is github', 'Web platform for Git collaboration.')
    reg('what is gitlab', 'DevOps platform with Git.')
    reg('what is jenkins', 'Open-source automation server.')
    reg('what is terraform', 'Infrastructure as code tool.')
    reg('what is ansible', 'IT automation engine.')
    reg('what is aws', 'Amazon Web Services cloud platform.')
    reg('what is azure', 'Microsoft Azure cloud service.')
    reg('what is gcp', 'Google Cloud Platform.')
    reg('what is saas', 'Software as a Service.')
    reg('what is paas', 'Platform as a Service.')
    reg('what is iaas', 'Infrastructure as a Service.')
    reg('what is edge computing', 'Computation near data sources.')
    reg('what is serverless computing', 'Cloud model with managed infrastructure.')
    reg('what is microservices', 'Architecture of small independent services.')
    reg('what is monolith', 'All-in-one interconnected architecture.')
    reg('what is devops', 'Combining development and IT operations.')
    reg('what is agile', 'Iterative project management approach.')
    reg('what is scrum', 'Agile framework using sprints.')
    reg('what is kanban', 'Visual workflow management.')
    reg('what is iot', 'Internet of Things -- connected devices.')
    reg('what is augmented reality', 'Digital content overlaid on the real world.')
    reg('what is virtual reality', 'Computer-generated 3D simulation.')
    reg('what is mixed reality', 'Blend of physical and digital worlds.')
    reg('what is computer vision', 'AI for interpreting visual information.')
    reg('what is image recognition', 'AI identifying objects in images.')
    reg('what is recommendation system', 'System suggesting products based on data.')
    reg('what is reinforcement learning', 'Agent learning by taking actions.')
    reg('what is supervised learning', 'ML trained on labeled data.')
    reg('what is unsupervised learning', 'ML finding patterns without labels.')
    reg('what is overfitting', 'Model performing poorly on new data.')
    reg('what is gradient descent', 'Optimization minimizing loss function.')
    reg('what is backpropagation', 'Algorithm for training neural networks.')
    reg('what is accuracy', 'Ratio of correct predictions to total.')
    reg('what is precision', 'True positive rate of predictions.')
    reg('what is recall', 'True positive rate of actual positives.')
    reg('what is f1 score', 'Harmonic mean of precision and recall.')
    reg('what is confusion matrix', 'Table for evaluating classification.')
    reg('what is cross validation', 'Assessing model generalization.')
    reg('what is random forest', 'Ensemble of decision trees.')
    reg('what is decision tree', 'Flowchart for classification.')
    reg('what is support vector machine', 'Algorithm finding optimal class boundary.')
    reg('what is k nearest neighbors', 'Classification based on nearest points.')
    reg('what is k means clustering', 'Partitioning data into k clusters.')
    reg('what is linear regression', 'Modeling variable relationships.')
    reg('what is logistic regression', 'Model for binary classification.')
    reg('what is hypothesis testing', 'Decisions based on sample data.')
    reg('what is p value', 'Probability under the null hypothesis.')
    reg('what is standard deviation', 'Measure of data dispersion.')
    reg('what is normal distribution', 'Symmetric bell-shaped distribution.')
    reg('what is chi square test', 'Test for categorical variable association.')
    reg('what is t test', 'Comparing means of two groups.')
    reg('what is pearson correlation', 'Linear correlation, -1 to 1.')
    reg('what is anova', 'Comparing means of three or more groups.')
    reg('what is acceleration', 'Rate of velocity change over time.')
    reg('what is velocity', 'Rate of position change with direction.')
    reg('what is momentum', 'Product of mass and velocity.')
    reg('what is newton\'s laws', 'Three laws: inertia, F=ma, action-reaction.')
    reg('what is thermodynamics', 'Physics of heat, work, and energy.')
    reg('what is entropy', 'Measure of disorder; always increases.')
    reg('what is superposition', 'Quantum system in multiple states.')
    reg('what is quantum entanglement', 'Correlated particles affecting each other.')
    reg('what is wave particle duality', 'Both wave and particle properties.')
    reg('what is heisenberg uncertainty principle', 'Cannot know both position and momentum precisely.')
    reg('what is Turing test', 'Test of machine intelligence.')
    reg('what is Moore\'s law', 'Transistors doubling every ~2 years.')
    reg('what is CAP theorem', 'Consistency, availability, partition -- pick two.')
    reg('what is ph level', 'Measure of acidity, 0-14.')
    reg('what is boiling point', 'Temperature liquid becomes gas.')
    reg('what is freezing point', 'Temperature liquid becomes solid.')
    reg('what is density', 'Mass per unit volume.')

    reg('how to write a for loop python', 'for i in range(10): print(i)')
    reg('how to write a while loop python', 'while condition: # do something')
    reg('how to define a function python', 'def my_function(param1, param2): return result')
    reg('how to create a class python', 'class MyClass: def __init__(self): self.x = 0')
    reg('how to make a list python', 'my_list = [1, 2, 3, 4, 5]')
    reg('how to make a dictionary python', 'my_dict = {\'key\': \'value\'}')
    reg('how to read a file python', 'with open(\'file.txt\', \'r\') as f: data = f.read()')
    reg('how to write a file python', 'with open(\'file.txt\', \'w\') as f: f.write(\'hello\')')
    reg('how to import in python', 'import module_name OR from module import function')
    reg('how to handle exceptions python', 'try: # code except Exception as e: print(e)')
    reg('how to use list comprehension python', '[x**2 for x in range(10)]')
    reg('how to sort a list python', 'my_list.sort() or sorted(my_list)')
    reg('how to reverse a list python', 'my_list.reverse() or my_list[::-1]')
    reg('how to join a list python', '\' \'.join(my_list)')
    reg('how to split a string python', 'my_string.split(\'delimiter\')')
    reg('how to strip whitespace python', 'my_string.strip()')
    reg('how to format a string python', 'f\'Hello {name}\' or \'Hello {}\'.format(name)')
    reg('how to check if key in dictionary python', '\'key\' in my_dict')
    reg('how to merge dictionaries python', '{**dict1, **dict2} or dict1 | dict2')
    reg('how to use enumerate python', 'for i, val in enumerate(my_list): print(i, val)')
    reg('how to use zip python', 'for a, b in zip(list1, list2): print(a, b)')
    reg('how to use map python', 'result = map(function, iterable)')
    reg('how to use filter python', 'result = filter(function, iterable)')
    reg('how to use lambda python', 'square = lambda x: x**2')
    reg('how to use decorators python', '@decorator def function(): pass')
    reg('how to create virtual environment python', 'python -m venv myenv && source myenv/bin/activate')
    reg('how to install packages python', 'pip install package_name')
    reg('how to create requirements file python', 'pip freeze > requirements.txt')
    reg('how to run python script', 'python script.py')
    reg('how to check python version', 'python --version')
    reg('how to use os module python', 'import os; os.listdir(), os.path.exists()')
    reg('how to use json module python', 'import json; json.loads(), json.dumps()')
    reg('how to use re module python', 'import re; re.search(), re.findall()')
    reg('how to use datetime python', 'from datetime import datetime; datetime.now()')
    reg('how to use random python', 'import random; random.randint(1,10)')
    reg('how to use requests python', 'import requests; r = requests.get(url)')
    reg('how to use sqlite3 python', 'import sqlite3; conn = sqlite3.connect(\'db.sqlite\')')
    reg('how to use subprocess python', 'import subprocess; subprocess.run([\'ls\'])')
    reg('how to use argparse python', 'import argparse; parser = argparse.ArgumentParser()')
    reg('how to create a flask app python', 'from flask import Flask; app = Flask(__name__)')
    reg('how to create a fastapi app python', 'from fastapi import FastAPI; app = FastAPI()')
    reg('how to create a django project python', 'django-admin startproject myproject')
    reg('how to create a tkinter window python', 'import tkinter as tk; root = tk.Tk()')
    reg('how to create a gui python', 'import tkinter as tk; app = tk.Tk(); app.mainloop()')
    reg('how to make a python executable', 'pip install pyinstaller && pyinstaller --onefile script.py')
    reg('how to make a python package', 'Create __init__.py, setup.py, and package structure')
    reg('how to use numpy python', 'import numpy as np; arr = np.array([1,2,3])')
    reg('how to use pandas python', 'import pandas as pd; df = pd.DataFrame({\'a\': [1,2]})')
    reg('how to use matplotlib python', 'import matplotlib.pyplot as plt; plt.plot([1,2,3])')
    reg('how to use seaborn python', 'import seaborn as sns; sns.barplot(data=df)')
    reg('how to use scikit learn python', 'from sklearn.model_selection import train_test_split')
    reg('how to use tensorflow python', 'import tensorflow as tf; model = tf.keras.Sequential()')
    reg('how to use pytorch python', 'import torch; tensor = torch.tensor([1,2,3])')
    reg('how to usebeautifulsoup python', 'from bs4 import BeautifulSoup; soup = BeautifulSoup(html)')
    reg('how to scrape a website python', 'import requests; from bs4 import BeautifulSoup')
    reg('how to send email python', 'import smtplib; server = smtplib.SMTP(\'smtp.gmail.com\', 587)')
    reg('how to create api python', 'from fastapi import FastAPI; app = FastAPI()')
    reg('how to use websocket python', 'import websocket; ws = websocket.WebSocketApp(url)')
    reg('how to use threading python', 'import threading; t = threading.Thread(target=func)')
    reg('how to use multiprocessing python', 'from multiprocessing import Process; p = Process(target=func)')
    reg('how to use asyncio python', 'import asyncio; async def main(): await func()')
    reg('how to use queue python', 'from queue import Queue; q = Queue(); q.put(item)')
    reg('how to use collections python', 'from collections import Counter, defaultdict, deque')
    reg('how to use itertools python', 'import itertools; for item in itertools.chain(a, b)')
    reg('how to use functools python', 'from functools import lru_cache; @lru_cache')
    reg('how to use pathlib python', 'from pathlib import Path; p = Path(\'.\')')
    reg('how to use logging python', 'import logging; logging.basicConfig(level=logging.INFO)')
    reg('how to use pytest python', 'def test_example(): assert 1+1 == 2')
    reg('how to use unittest python', 'import unittest; class Test(unittest.TestCase):')
    reg('how to use dataclasses python', 'from dataclasses import dataclass; @dataclass')
    reg('how to use typing python', 'from typing import List, Dict, Optional')
    reg('how to use enum python', 'from enum import Enum; class Color(Enum): RED=1')
    reg('how to use abc python', 'from abc import ABC, abstractmethod')
    reg('how to use context manager python', 'class Ctx: def __enter__(self): ... def __exit__(self, *a): ...')
    reg('how to use generator python', 'def gen(): yield value')
    reg('how to use iterator python', 'class Iter: def __iter__(self): ... def __next__(self): ...')
    reg('how to use property python', '@property def name(self): return self._name')
    reg('how to use staticmethod python', '@staticmethod def func(): ...')
    reg('how to use classmethod python', '@classmethod def from_string(cls, s): ...')
    reg('how to use slots python', 'class MyClass: __slots__ = [\'x\', \'y\']')
    reg('how to use metaclass python', 'class Meta(type): pass')
    reg('how to use exec python', 'exec(\'print(1)\')')
    reg('how to use eval python', 'eval(\'1+1\')')
    reg('how to use pickle python', 'import pickle; pickle.dump(obj, file); pickle.load(file)')
    reg('how to use shelve python', 'import shelve; d = shelve.open(\'mydb\'); d[\'key\'] = val')
    reg('how to use sqlite python', 'import sqlite3; conn = sqlite3.connect(\'db.sqlite\')')
    reg('how to use csv module python', 'import csv; reader = csv.reader(open(\'file.csv\'))')
    reg('how to use xml python', 'import xml.etree.ElementTree as ET')
    reg('how to use html python', 'import html; html.escape(), html.unescape()')
    reg('how to use hashlib python', 'import hashlib; hashlib.sha256(data).hexdigest()')
    reg('how to use hmac python', 'import hmac; hmac.new(key, msg, hashlib.sha256).hexdigest()')
    reg('how to use secrets python', 'import secrets; token = secrets.token_hex(16)')
    reg('how to use base64 python', 'import base64; base64.b64encode(data)')
    reg('how to use uuid python', 'import uuid; u = uuid.uuid4()')
    reg('how to use socket python', 'import socket; s = socket.socket()')
    reg('how to use http server python', 'python -m http.server 8000')
    reg('how to use ssl python', 'import ssl; ctx = ssl.create_default_context()')
    reg('how to use ftplib python', 'from ftplib import FTP; ftp = FTP()')
    reg('how to use imaplib python', 'import imaplib; mail = imaplib.IMAP4_SSL(\'imap.gmail.com\')')
    reg('how to use poplib python', 'import poplib; mail = poplib.POP3_SSL(\'pop.gmail.com\')')
    reg('how to use smtplib python', 'import smtplib; server = smtplib.SMTP_SSL(\'smtp.gmail.com\', 465)')
    reg('how to use urllib python', 'from urllib.request import urlopen; resp = urlopen(url)')
    reg('how to use email python', 'from email.mime.text import MIMEText')
    reg('how to use calendar python', 'import calendar; calendar.month(2024, 1)')
    reg('how to use timeit python', 'import timeit; timeit.timeit(\'sum(range(100))\')')
    reg('how to use cProfile python', 'import cProfile; cProfile.run(\'my_function()\')')
    reg('how to use pdb python', 'import pdb; pdb.set_trace()')
    reg('how to use trace python', 'import trace; tracer = trace.Trace()')
    reg('how to use dis python', 'import dis; dis.dis(my_function)')
    reg('how to use inspect python', 'import inspect; inspect.getsource(func)')
    reg('how to use keyword python', 'import keyword; keyword.iskeyword(\'class\')')
    reg('how to use token python', 'import token; token.tok_name[token.NUMBER]')
    reg('how to use ast python', 'import ast; tree = ast.parse(code)')
    reg('how to use compile python', 'code = compile(source, filename, \'exec\')')
    reg('how to use importlib python', 'import importlib; mod = importlib.import_module(\'os\')')
    reg('how to use pkgutil python', 'import pkgutil; list(pkgutil.iter_modules())')
    reg('how to use sys module python', 'import sys; sys.argv, sys.path, sys.version')
    reg('how to use os path python', 'import os.path; os.path.join(), os.path.exists()')
    reg('how to use shutil python', 'import shutil; shutil.copy(), shutil.move()')
    reg('how to use glob python', 'import glob; glob.glob(\'*.py\')')
    reg('how to use fnmatch python', 'import fnmatch; fnmatch.fnmatch(\'test.py\', \'*.py\')')
    reg('how to use tempfile python', 'import tempfile; f = tempfile.NamedTemporaryFile()')
    reg('how to use gzip python', 'import gzip; f = gzip.open(\'file.gz\', \'wb\')')
    reg('how to use zipfile python', 'import zipfile; z = zipfile.ZipFile(\'archive.zip\')')
    reg('how to use tarfile python', 'import tarfile; t = tarfile.open(\'archive.tar.gz\')')
    reg('how to use zlib python', 'import zlib; compressed = zlib.compress(data)')
    reg('how to use bz2 python', 'import bz2; compressed = bz2.compress(data)')
    reg('how to use lzma python', 'import lzma; compressed = lzma.compress(data)')
    reg('how to use struct python', 'import struct; struct.pack(\'i\', 42)')
    reg('how to use ctypes python', 'import ctypes; libc = ctypes.CDLL(\'libc.so.6\')')
    reg('how to use mmap python', 'import mmap; f = mmap.mmap(fileno, length)')
    reg('how to use signal python', 'import signal; signal.signal(signal.SIGINT, handler)')
    reg('how to use threading lock python', 'import threading; lock = threading.Lock()')
    reg('how to use concurrent futures python', 'from concurrent.futures import ThreadPoolExecutor')
    reg('how to usemultiprocessing pool python', 'from multiprocessing import Pool; Pool(4).map(func, items)')
    reg('how to use array module python', 'import array; arr = array.array(\'i\', [1,2,3])')
    reg('how to use bisect python', 'import bisect; bisect.insort(sorted_list, value)')
    reg('how to use heapq python', 'import heapq; heapq.nlargest(3, iterable)')
    reg('how to use queue module python', 'from queue import Queue; q = Queue(); q.put(item)')
    reg('how to use copy module python', 'import copy; deep = copy.deepcopy(obj)')
    reg('how to use pprint python', 'from pprint import pprint; pprint(data)')
    reg('how to use textwrap python', 'import textwrap; textwrap.fill(text, 70)')
    reg('how to use difflib python', 'import difflib; difflib.unified_diff(a, b)')
    reg('how to use decimal python', 'from decimal import Decimal; Decimal(\'0.1\') + Decimal(\'0.2\')')
    reg('how to use fractions python', 'from fractions import Fraction; Fraction(1, 3)')
    reg('how to use statistics python', 'import statistics; statistics.mean([1,2,3])')
    reg('how to use math module python', 'import math; math.sqrt(16), math.pi')
    reg('how to use cmath python', 'import cmath; cmath.sqrt(-1)')
    reg('how to use statistics mean python', 'import statistics; statistics.mean(data)')
    reg('how to use statistics median python', 'import statistics; statistics.median(data)')
    reg('how to use statistics stdev python', 'import statistics; statistics.stdev(data)')
    reg('how to use statistics variance python', 'import statistics; statistics.variance(data)')
    reg('how to use statistics mode python', 'import statistics; statistics.mode(data)')
    reg('how to use statistics harmonic mean python', 'import statistics; statistics.harmonic_mean(data)')
    reg('how to use statistics geometric mean python', 'import statistics; statistics.geometric_mean(data)')
    reg('how to use statistics quantiles python', 'import statistics; statistics.quantiles(data)')
    reg('how to use statistics normaldist python', 'from statistics import NormalDist; nd = NormalDist()')
    reg('how to use random choices python', 'import random; random.choices(population, k=3)')
    reg('how to use random shuffle python', 'import random; random.shuffle(my_list)')
    reg('how to use random sample python', 'import random; random.sample(population, k=2)')
    reg('how to use random seed python', 'import random; random.seed(42)')
    reg('how to use random uniform python', 'import random; random.uniform(1.0, 10.0)')
    reg('how to use random gauss python', 'import random; random.gauss(mu=0, sigma=1)')
    reg('how to use random expovariate python', 'import random; random.expovariate(1.0)')
    reg('how to use random triangular python', 'import random; random.triangular(0, 10)')
    reg('how to use random randrange python', 'import random; random.randrange(0, 100, 5)')
    reg('how to use random bytes python', 'import random; random.randbytes(16)')
    reg('what is the largest ocean', 'The Pacific Ocean, covering about 165 million sq km.')
    reg('what is the tallest mountain', 'Mount Everest at 8,849 meters above sea level.')
    reg('what is the longest river', 'The Nile River at approximately 6,650 km.')
    reg('what is the largest desert', 'The Sahara Desert at about 9.2 million sq km.')
    reg('what is the deepest ocean trench', 'The Mariana Trench at 10,994 meters deep.')
    reg('what is the largest animal', 'The blue whale, up to 30 meters long.')
    reg('what is the fastest animal', 'The peregrine falcon at over 390 km/h in a dive.')
    reg('what is the smallest country', 'Vatican City at 0.44 sq km.')
    reg('what is the most spoken language', 'Mandarin Chinese by native speakers, English by total speakers.')
    reg('what is the most populous country', 'India with over 1.4 billion people.')
    reg('what is the largest planet', 'Jupiter, with a mass 318 times Earth.')
    reg('what is the hottest planet', 'Venus at about 465 degrees Celsius.')
    reg('what is the coldest planet', 'Neptune at about -214 degrees Celsius.')
    reg('what is the largest star', 'UY Scuti, about 1,700 times the Sun\'s radius.')
    reg('what is the closest star', 'The Sun at about 150 million km away.')
    reg('what is the fastest human', 'Usain Bolt at 44.72 km/h (27.8 mph).')
    reg('what is the largest organ', 'The skin, covering about 2 square meters.')
    reg('what is the hardest substance', 'Diamond, rating 10 on the Mohs scale.')
    reg('what is the most abundant gas in atmosphere', 'Nitrogen at about 78% of the atmosphere.')
    reg('what is the most abundant element in universe', 'Hydrogen at about 75% of ordinary matter.')
    reg('what is the speed of sound', 'About 343 meters per second in air at 20 degrees C.')
    reg('what is absolute zero', '-273.15 degrees Celsius, the lowest possible temperature.')
    reg('what is pi day', 'March 14th (3/14), matching the first digits of pi.')
    reg('what is eulers number', 'Euler\'s number e is approximately 2.71828.')
    reg('what is avogadro\'s number', '6.022 x 10^23, the number of particles in one mole.')
    reg('what is planck\'s constant', '6.626 x 10^-34 joule-seconds.')
    reg('what is boltzmann constant', '1.381 x 10^-23 joules per kelvin.')
    reg('what is the golden ratio', 'Approximately 1.618, often denoted by the Greek letter phi.')
    reg('what is the fibonacci sequence', '0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89...')
    reg('what is the riemann hypothesis', 'A conjecture about the zeros of the Riemann zeta function.')
    reg('what is P vs NP', 'A major unsolved problem: can every problem whose solution is quickly verified be quickly solved?')
    reg('what is the halting problem', 'Determining whether a program will finish running or run forever -- proven undecidable.')
    reg('what is Gödel\'s incompleteness theorem', 'Any consistent formal system contains statements that are true but unprovable.')
    reg('what is chaos theory', 'Sensitive dependence on initial conditions in dynamic systems.')
    reg('what is fractal', 'A pattern that repeats at every scale, like a Mandelbrot set.')
    reg('what is the butterfly effect', 'Small changes in initial conditions leading to large differences in outcomes.')
    reg('what is information entropy', 'A measure of uncertainty in information, developed by Shannon.')
    reg('what is shannon entropy', 'H = -sum(p * log2(p)), measuring information content.')
    reg('what is Kolmogorov complexity', 'The shortest description of a string by a program.')
    reg('what is NP complete', 'The hardest problems in NP, where any NP problem can be reduced to them.')
    reg('what is quicksort', 'A divide-and-conquer sorting algorithm with O(n log n) average.')
    reg('what is merge sort', 'A stable, divide-and-conquer sorting algorithm.')
    reg('what is binary search', 'Finding an element in a sorted array in O(log n) time.')
    reg('what is hash table', 'A data structure mapping keys to values using a hash function.')
    reg('what is linked list', 'A linear data structure where elements are not stored contiguously.')
    reg('what is stack data structure', 'LIFO -- Last In, First Out data structure.')
    reg('what is queue data structure', 'FIFO -- First In, First Out data structure.')
    reg('what is heap data structure', 'A complete binary tree where parent is greater/less than children.')
    reg('what is graph data structure', 'A set of nodes connected by edges.')
    reg('what is breadth first search', 'Exploring all neighbors at current depth before moving deeper.')
    reg('what is depth first search', 'Exploring as far as possible along each branch before backtracking.')
    reg('what is dynamic programming', 'Breaking problems into overlapping subproblems and storing solutions.')
    reg('what is greedy algorithm', 'Making locally optimal choices at each step.')
    reg('what is divide and conquer', 'Recursively breaking a problem into smaller subproblems.')
    reg('what is backtracking', 'Trying all possibilities and undoing choices that fail.')
    reg('what is bit manipulation', 'Operations on individual bits: AND, OR, XOR, shifts.')
    reg('what is two pointer technique', 'Using two pointers moving toward each other or in same direction.')
    reg('what is sliding window', 'A window moving across data to find subarray/substring.')
    reg('what is topological sort', 'Ordering vertices in a directed acyclic graph.')
    reg('what is Dijkstra algorithm', 'Finding shortest paths from a source in a weighted graph.')
    reg('what is bellman ford algorithm', 'Shortest paths allowing negative edge weights.')
    reg('what is Floyd Warshall algorithm', 'All-pairs shortest paths in a weighted graph.')
    reg('what is minimum spanning tree', 'A subset of edges connecting all vertices with minimum total weight.')
    reg('what is Prim algorithm', 'Growing MST one vertex at a time.')
    reg('what is Kruskal algorithm', 'Growing MST by adding cheapest edges that don\'t create cycles.')
    reg('what is Union Find', 'A data structure tracking disjoint sets with path compression.')
    reg('what is trie data structure', 'A tree for storing strings, used in autocomplete and spell-checking.')
    reg('what is AVL tree', 'A self-balancing binary search tree.')
    reg('what is red black tree', 'A self-balancing binary search tree with color properties.')
    reg('what is B tree', 'A self-balancing tree for databases and file systems.')
    reg('what is segment tree', 'A tree for querying ranges of an array.')
    reg('what is Fenwick tree', 'A binary indexed tree for prefix sums.')
    reg('what is suffix array', 'A sorted array of all suffixes of a string.')
    reg('what is LRU cache', 'Least Recently Used cache evicting oldest access.')
    reg('what is bloom filter', 'A probabilistic data structure for set membership testing.')
    reg('what is skip list', 'A probabilistic alternative to balanced trees.')
    reg('what is circular buffer', 'A fixed-size buffer wrapping around on itself.')
    reg('what is doubly linked list', 'A linked list where each node has pointers to next and previous.')
    reg('what is circular linked list', 'A linked list where the last node points back to the first.')
    reg('what is adjacency matrix', 'A 2D array representing graph edges.')
    reg('what is adjacency list', 'A list of lists representing graph edges.')
    reg('what is directed graph', 'A graph where edges have direction.')
    reg('what is undirected graph', 'A graph where edges have no direction.')
    reg('what is weighted graph', 'A graph where edges have associated values.')
    reg('what is DAG', 'Directed Acyclic Graph -- no cycles, used in scheduling.')
    reg('what is complete graph', 'A graph where every pair of vertices is connected.')
    reg('what is bipartite graph', 'A graph whose vertices can be divided into two disjoint sets.')
    reg('what is Euler path', 'A path visiting every edge exactly once.')
    reg('what is Hamiltonian path', 'A path visiting every vertex exactly once.')
    reg('what is planar graph', 'A graph that can be drawn without edge crossings.')
    reg('what is graph coloring', 'Assigning colors to vertices so no adjacent vertices share color.')
    reg('what is max flow min cut', 'The maximum flow equals the minimum cut capacity.')
    reg('what is Ford Fulkerson algorithm', 'Finding maximum flow in a flow network.')
    reg('what is network flow', 'The rate of material flow through a network.')
    reg('what is matching in graph', 'A set of edges without common vertices.')
    reg('what is maximum matching', 'The largest possible matching in a graph.')
# -- END AUTO-GENERATED --



# -- AUTO-GENERATED KNOWLEDGE SKILLS (batch 3, gen_skills3.py) --
    # 684 knowledge & conversational skills
    reg("why is the sky blue", "Sunlight scatters off air molecules, and blue light scatters the most because it travels in shorter waves. That scattered blue is what fills the sky, sir.")
    reg("why is mars red", "Mars is covered in iron oxide, essentially rust, which gives it its distinctive reddish color, sir.")
    reg("how do vaccines work", "Vaccines train your immune system by showing it a harmless piece of a pathogen so it can build defenses before meeting the real thing, sir.")
    reg("why do we dream", "Scientists believe dreaming helps the brain process emotions, consolidate memories, and rehearse responses to threats, sir.")
    reg("what causes thunder", "Thunder is the sound of air rapidly expanding around a lightning bolt as it superheats to roughly 30,000 degrees Celsius, sir.")
    reg("what is lightning", "Lightning is a giant electrostatic discharge between clouds or between a cloud and the ground, several times hotter than the sun's surface, sir.")
    reg("how do rainbows form", "Rainbows form when sunlight refracts inside water droplets, splitting into the spectrum of colors we see arcing across the sky, sir.")
    reg("why do leaves change color in autumn", "As days shorten, chlorophyll breaks down and reveals yellow and orange pigments, while some trees produce red anthocyanins, sir.")
    reg("how do chameleons change color", "Chameleons adjust tiny crystals in their skin cells that reflect different wavelengths of light, changing their color, sir.")
    reg("how do magnets work", "Magnetism arises from the alignment of electron spins in a material, creating a field that attracts or repels certain metals, sir.")
    reg("why does ice float", "Ice floats because water expands as it freezes, making frozen water about nine percent less dense than liquid water, sir.")
    reg("what makes the sun shine", "The sun shines through nuclear fusion, converting about 600 million tons of hydrogen into helium every second and releasing enormous energy, sir.")
    reg("how far is the sun from earth", "The sun is about 150 million kilometers away, and its light takes roughly eight minutes and twenty seconds to reach us, sir.")
    reg("what is a light year", "A light year is the distance light travels in one year, about 9.46 trillion kilometers, sir.")
    reg("how many bones are in the human body", "Adults have 206 bones; babies are born with around 300 which fuse together as they grow, sir.")
    reg("why do we yawn", "Yawning may help cool the brain and increase alertness, and it is contagious because of social mirroring, sir.")
    reg("why do we sneeze", "Sneezing is a reflex that expels irritants like dust, pollen, or germs from your nasal passages at high speed, sir.")
    reg("what is blood made of", "Blood is about 55 percent plasma plus red cells that carry oxygen, white cells that fight infection, and platelets that clot wounds, sir.")
    reg("how does the heart work", "The heart is a muscle that contracts about 100,000 times a day, pumping roughly 7,500 liters of blood through your body, sir.")
    reg("what causes hiccups", "Hiccups happen when your diaphragm spasms involuntarily and your vocal cords snap shut, producing the characteristic hic sound, sir.")
    reg("how big is the universe", "The observable universe spans about 93 billion light years across, and the whole universe may be far larger still, sir.")
    reg("what is the milky way", "The Milky Way is our barred spiral galaxy, home to somewhere between 100 and 400 billion stars including our sun, sir.")
    reg("what is a comet", "A comet is a ball of ice, dust, and rock that grows a glowing tail when it approaches the sun and heats up, sir.")
    reg("what is an asteroid", "An asteroid is a rocky body orbiting the sun, mostly found in the belt between Mars and Jupiter, sir.")
    reg("difference between meteor and meteorite", "A meteor is the streak of light as space rock burns in our atmosphere; if it survives and lands, it is called a meteorite, sir.")
    reg("what is the northern lights", "The aurora occurs when charged solar particles strike gases in the upper atmosphere near the poles, painting green and red curtains of light, sir.")
    reg("what is a solar eclipse", "A solar eclipse happens when the moon passes directly between Earth and the sun, casting its shadow on us, sir.")
    reg("what is a lunar eclipse", "A lunar eclipse happens when Earth passes between the sun and moon, casting a shadow that turns the moon coppery red, sir.")
    reg("why does the moon change shape", "The moon's phases come from changing angles between the sun, Earth, and moon across a cycle of about 29.5 days, sir.")
    reg("what is a nebula", "A nebula is an enormous cloud of gas and dust in space, often the birthplace of new stars, sir.")
    reg("what is a pulsar", "A pulsar is a spinning neutron star that beams radiation like a lighthouse as it rotates, some hundreds of times per second, sir.")
    reg("what is a quasar", "A quasar is an extremely bright galactic core powered by matter falling into a supermassive black hole, visible across billions of light years, sir.")
    reg("what is antimatter", "Antimatter is matter with opposite charge; when it meets normal matter both annihilate into pure energy, sir.")
    reg("what is a molecule", "A molecule is two or more atoms bonded together, like H2O, the water molecule made of two hydrogens and one oxygen, sir.")
    reg("states of matter", "There are four common states: solid, liquid, gas, and plasma, each defined by how tightly particles are bound together, sir.")
    reg("what is plasma state", "Plasma is ionized gas where electrons break free from atoms; it makes up over 99 percent of the visible universe, sir.")
    reg("what is surface tension", "Surface tension comes from water molecules clinging together at the surface, strong enough to let insects walk on water, sir.")
    reg("what is capillary action", "Capillary action is how liquids climb narrow spaces against gravity, the way water rises through a paper towel, sir.")
    reg("how do batteries work", "Batteries convert stored chemical energy into electricity through reactions between electrodes, pushing electrons through your circuit, sir.")
    reg("how do lasers work", "Lasers amplify light by stimulating atoms to emit photons in perfect step, producing a tight, single-color beam, sir.")
    reg("what is static electricity", "Static electricity builds when electrons transfer between surfaces through friction, then discharge with a spark, sir.")
    reg("what is the doppler effect", "The Doppler effect is why a siren sounds higher approaching you and lower moving away: motion shifts wave frequency, sir.")
    reg("why do stars twinkle", "Stars twinkle because their light bends as it passes through shifting layers of turbulent air in our atmosphere, sir.")
    reg("why is the ocean salty", "Rivers dissolve minerals from rocks over millions of years and carry them seaward, leaving the ocean about 3.5 percent salt, sir.")
    reg("what causes ocean tides", "Tides are caused mainly by the moon's gravitational pull dragging Earth's oceans into bulges on opposite sides of the planet, sir.")
    reg("how do clouds form", "Clouds form when warm moist air rises, cools, and water vapor condenses onto tiny airborne particles, sir.")
    reg("what causes earthquakes", "Earthquakes occur when stress along tectonic plate boundaries releases suddenly, sending shockwaves through the ground, sir.")
    reg("what is a volcano", "A volcano is an opening in Earth's crust where molten magma, ash, and gas erupt from below the surface, sir.")
    reg("what was pangaea", "Pangaea was the supercontinent that assembled most landmasses about 335 million years ago before breaking into today's continents, sir.")
    reg("how old is planet earth", "Earth formed about 4.5 billion years ago from the disk of debris surrounding the young sun, sir.")
    reg("what is the water cycle", "Water evaporates from oceans, condenses into clouds, falls as precipitation, and flows back to the sea in a continuous loop, sir.")
    reg("what is plate tectonics", "Plate tectonics describes Earth's crust as drifting plates whose collisions and separations build mountains and open oceans, sir.")
    reg("why does bread rise", "Yeast ferments sugars releasing carbon dioxide, and gluten traps the bubbles, making dough puff up as it bakes, sir.")
    reg("how does soap clean", "Soap molecules have one end that binds to grease and one end that loves water, letting dirt be rinsed away, sir.")
    reg("why does metal feel colder than wood", "Metal conducts heat away from your hand faster than wood, so it feels colder even at the same temperature, sir.")
    reg("who was cleopatra", "Cleopatra VII was the last active ruler of ancient Egypt, famous for her intelligence, alliances with Rome, and dramatic end in 30 BC, sir.")
    reg("who was julius caesar", "Julius Caesar was a Roman general who conquered Gaul and became dictator before being assassinated on the Ides of March in 44 BC, sir.")
    reg("who was alexander the great", "Alexander the Great built one of history's largest empires by age 30, stretching from Greece to India before dying at 32 in 323 BC, sir.")
    reg("who was genghis khan", "Genghis Khan united the Mongol tribes and founded the largest contiguous land empire in history during the 13th century, sir.")
    reg("who was joan of arc", "Joan of Arc was a French peasant girl who led armies to victory at 17 and became a national heroine and Catholic saint, sir.")
    reg("who was napoleon bonaparte", "Napoleon Bonaparte rose from artillery officer to Emperor of France, conquering much of Europe before his final defeat at Waterloo in 1815, sir.")
    reg("who was queen victoria", "Queen Victoria ruled Britain for 63 years from 1837 to 1901, an era of industrial expansion known as the Victorian age, sir.")
    reg("who was george washington", "George Washington led the American Revolution to victory and became the first US president in 1789, sir.")
    reg("who was thomas jefferson", "Thomas Jefferson authored the Declaration of Independence and served as the third US president, sir.")
    reg("who was michelangelo", "Michelangelo painted the Sistine Chapel ceiling and sculpted David, standing among the greatest artists of the Renaissance, sir.")
    reg("who was galileo galilei", "Galileo pioneered observational astronomy, discovering Jupiter's moons and defending the idea that Earth orbits the sun, sir.")
    reg("who was louis pasteur", "Louis Pasteur proved germ theory, invented pasteurization, and developed early vaccines for rabies and anthrax, sir.")
    reg("who was florence nightingale", "Florence Nightingale revolutionized nursing and hospital sanitation during the Crimean War, founding modern nursing practice, sir.")
    reg("who was harriet tubman", "Harriet Tubman escaped slavery and repeatedly risked her life guiding dozens of others to freedom on the Underground Railroad, sir.")
    reg("who was walt disney", "Walt Disney created Mickey Mouse, pioneered feature animation, and built Disneyland, transforming family entertainment, sir.")
    reg("who built the great wall of china", "Chinese dynasties began the Great Wall over 2,000 years ago, with most surviving sections built during the Ming dynasty, sir.")
    reg("when did the roman empire fall", "The Western Roman Empire fell in 476 AD when the last emperor was deposed; the Eastern half endured nearly another thousand years, sir.")
    reg("when did world war 1 begin", "World War I began in July 1914 after the assassination of Archduke Franz Ferdinand in Sarajevo, sir.")
    reg("when did world war 2 end", "World War II ended in 1945: Germany surrendered in May and Japan formally surrendered in September, sir.")
    reg("when did the vietnam war end", "American combat troops withdrew in 1973, and Saigon fell in April 1975, reuniting Vietnam under the north, sir.")
    reg("when was the korean war", "The Korean War raged from 1950 to 1953, ending in an armistice rather than a formal peace treaty, sir.")
    reg("when did india become independent", "India won independence from British rule on August 15, 1947, becoming the world's largest democracy, sir.")
    reg("when did the titanic sink", "The Titanic struck an iceberg on the night of April 14, 1912, and sank early on April 15 with heavy loss of life, sir.")
    reg("where were the first modern olympics held", "Athens, Greece hosted the first modern Olympic Games in 1896, reviving a tradition from ancient Greece, sir.")
    reg("who built the pyramids of giza", "Egyptian workers, not slaves, built the Giza pyramids around 4,500 years ago as tombs for the pharaohs, sir.")
    reg("what was the silk road", "The Silk Road was an ancient trade network linking China with Central Asia, India, and Europe, carrying goods, ideas, and inventions, sir.")
    reg("what was the black death plague", "The Black Death swept Europe from 1347 to 1351, killing an estimated one-third of the population, sir.")
    reg("what was the spanish flu", "The Spanish flu pandemic of 1918 to 1920 infected roughly a third of humanity and killed tens of millions worldwide, sir.")
    reg("when did american women get the vote", "American women won the right to vote nationwide in 1920 with the ratification of the 19th Amendment, sir.")
    reg("when did slavery end in america", "Slavery was abolished in the United States in 1865 through the 13th Amendment after the Civil War, sir.")
    reg("what was the boston tea party", "The Boston Tea Party of 1773 saw American colonists dump British tea into the harbor in protest against taxation, sir.")
    reg("what was the french revolution about", "The French Revolution of 1789 overthrew the monarchy in the name of liberty, equality, and fraternity, reshaping modern politics, sir.")
    reg("who were the vikings", "The Vikings were Scandinavian seafarers who raided, traded, and settled across Europe and reached North America centuries before Columbus, sir.")
    reg("what was the aztec empire", "The Aztec Empire centered on Tenochtitlan in today's Mexico City flourished until Spanish conquistadors toppled it in 1521, sir.")
    reg("what was the mongol empire", "The Mongol Empire became the largest contiguous empire ever, spanning Asia into Europe and reviving trade along the Silk Road, sir.")
    reg("who was the first man on the moon", "Neil Armstrong stepped onto the lunar surface on July 20, 1969, followed minutes later by Buzz Aldrin, sir.")
    reg("who was the first woman in space", "Soviet cosmonaut Valentina Tereshkova became the first woman in space aboard Vostok 6 in June 1963, sir.")
    reg("what was the apollo program", "NASA's Apollo program ran from 1961 to 1972 and landed twelve astronauts on the moon across six successful missions, sir.")
    reg("what was the manhattan project about", "The Manhattan Project was America's secret WWII program that developed the first atomic bombs under J. Robert Oppenheimer, sir.")
    reg("when was the declaration of independence signed", "The Continental Congress adopted the Declaration of Independence on July 4, 1776, sir.")
    reg("when was the constitution written", "The US Constitution was drafted in 1787 in Philadelphia and took effect in 1789 after ratification, sir.")
    reg("who discovered america first", "Indigenous peoples arrived thousands of years ago; Norse explorer Leif Erikson landed around 1000 AD, and Columbus reached the Caribbean in 1492, sir.")
    reg("when did the industrial revolution start", "The Industrial Revolution began in Britain around 1760, powered by steam engines, factories, and mechanized textile production, sir.")
    reg("what started world war 1", "The assassination of Archduke Franz Ferdinand in June 1914 triggered alliances that pulled Europe into war within weeks, sir.")
    reg("what ended world war 2 in europe", "Germany's unconditional surrender on May 8, 1945 marked Victory in Europe Day, ending WWII there, sir.")
    reg("who was mahatma gandhi biography", "Gandhi trained as a lawyer in London, developed satyagraha nonviolence in South Africa, and led India to freedom in 1947, sir.")
    reg("who was winston churchill biography", "Churchill served Britain as soldier, writer, and prime minister twice, most famously rallying the nation against Nazi Germany, sir.")
    reg("who was abraham lincoln biography", "Lincoln was born in a log cabin in 1809, self-taught himself law, held the Union together, and pushed the 13th Amendment abolishing slavery, sir.")
    reg("who was nelson mandela biography", "Mandela spent 27 years in prison for opposing apartheid, then emerged to negotiate democracy and serve as South Africa's first Black president, sir.")
    reg("who was martin luther king jr biography", "Martin Luther King Jr. was a Baptist minister who led the civil rights movement and delivered his 'I Have a Dream' speech in 1963, sir.")
    reg("when was the un founded", "The United Nations was founded on October 24, 1945, after World War II, to maintain international peace and cooperation, sir.")
    reg("when did the cold war start", "Tensions hardened into the Cold War by 1947 as the US and Soviet Union emerged as rival superpowers, sir.")
    reg("when did the soviet union collapse", "The Soviet Union dissolved in December 1991, ending decades of communist rule and the Cold War era, sir.")
    reg("who was rani lakshmibai", "Rani Lakshmibai of Jhansi was a queen who fought British forces heroically during India's 1857 rebellion, becoming an enduring icon, sir.")
    reg("who was bhagat singh", "Bhagat Singh was an Indian revolutionary who fought British colonial rule and became a martyr at just 23 in 1931, sir.")
    reg("when was the taj mahal built", "Emperor Shah Jahan built the Taj Mahal between 1632 and 1653 as a marble mausoleum for his beloved wife Mumtaz Mahal, sir.")
    reg("capital of france", "Paris has been France's capital city for centuries, famed for the Eiffel Tower and the Louvre, sir.")
    reg("capital of japan", "Tokyo is Japan's capital and one of the most populous metropolitan areas in the world, sir.")
    reg("capital of australia", "Canberra is Australia's capital, purpose-built as a compromise between Sydney and Melbourne, sir.")
    reg("capital of canada", "Ottawa is Canada's capital, sitting on the border of Ontario and Quebec, sir.")
    reg("capital of brazil", "Brasilia is Brazil's planned capital city, inaugurated in 1960, sir.")
    reg("capital of china", "Beijing is China's capital, home to the Forbidden City and Tiananmen Square, sir.")
    reg("capital of russia", "Moscow is Russia's capital and largest city, centered on the Kremlin, sir.")
    reg("capital of italy", "Rome is Italy's capital, once heart of the Roman Empire, sir.")
    reg("capital of spain", "Madrid is Spain's capital and largest city, sitting almost exactly in the country's center, sir.")
    reg("capital of germany", "Berlin is Germany's capital, famously divided until the Wall fell in 1989, sir.")
    reg("capital of egypt", "Cairo is Egypt's sprawling capital on the Nile, near the pyramids of Giza, sir.")
    reg("capital of argentina", "Buenos Aires is Argentina's capital, often called the Paris of South America, sir.")
    reg("capital of mexico", "Mexico City is the capital, built atop the ruins of the Aztec capital Tenochtitlan, sir.")
    reg("capital of thailand", "Bangkok is Thailand's capital, officially known by one of the longest place names on Earth, sir.")
    reg("largest country by area", "Russia is the largest country on Earth, covering about 17 million square kilometers, eleven time zones wide, sir.")
    reg("smallest ocean", "The Arctic Ocean is the smallest and shallowest ocean, capping the top of the globe, sir.")
    reg("longest mountain range", "The Andes stretch about 7,000 kilometers along South America, the longest continental mountain range, sir.")
    reg("highest mountain range", "The Himalayas hold the tallest peaks on Earth including Everest at 8,849 meters, sir.")
    reg("tallest waterfall in the world", "Angel Falls in Venezuela plunges 979 meters, the highest uninterrupted waterfall anywhere, sir.")
    reg("biggest island in the world", "Greenland is the largest island, covering about 2.16 million square kilometers, sir.")
    reg("largest lake in the world", "The Caspian Sea is the largest enclosed inland body of water, shared by five countries, sir.")
    reg("deepest lake in the world", "Lake Baikal in Siberia plunges about 1,642 meters and holds a fifth of the world's unfrozen fresh water, sir.")
    reg("where is the amazon river", "The Amazon flows roughly 6,400 kilometers across Peru, Colombia, and Brazil, carrying more water than any other river, sir.")
    reg("where are the himalayas", "The Himalayas arc across five countries: Nepal, India, Bhutan, China, and Pakistan, sir.")
    reg("how tall is mount everest", "Mount Everest stands 8,849 meters above sea level, first summited by Hillary and Norgay in 1953, sir.")
    reg("where is the dead sea", "The hyper-salty Dead Sea lies between Jordan and Israel, and at about 430 meters below sea level it is Earth's lowest land point, sir.")
    reg("what is the great barrier reef", "The Great Barrier Reef off Queensland, Australia is the largest coral reef system on Earth, visible even from space, sir.")
    reg("where is the eiffel tower", "The Eiffel Tower rises over Paris, France, built for the 1889 World's Fair, sir.")
    reg("how tall is the eiffel tower", "The Eiffel Tower stands about 330 meters tall including antennas, and sways slightly with temperature, sir.")
    reg("where is the statue of liberty", "Lady Liberty stands on Liberty Island in New York Harbor, a gift from France dedicated in 1886, sir.")
    reg("where is the taj mahal located", "The Taj Mahal sits in Agra, India, on the banks of the Yamuna River, sir.")
    reg("where is machu picchu", "Machu Picchu clings to an Andean ridge in Peru at about 2,430 meters elevation, built by the Inca in the 1400s, sir.")
    reg("where is the colosseum", "The Colosseum stands in central Rome, Italy, completed around 80 AD as a gladiatorial arena, sir.")
    reg("where is the great pyramid of giza", "The Great Pyramid rises on the Giza plateau near Cairo, Egypt, and is the last surviving Ancient Wonder, sir.")
    reg("where is petra", "Petra is a rock-cut city carved by the Nabataeans in southern Jordan over 2,000 years ago, sir.")
    reg("where is the grand canyon", "The Grand Canyon slices through northern Arizona, carved by the Colorado River over millions of years, sir.")
    reg("where is victoria falls", "Victoria Falls thunders on the Zambia-Zimbabwe border; locals call it Mosi-oa-Tunya, the smoke that thunders, sir.")
    reg("where is niagara falls", "Niagara Falls straddles the border between New York State and Ontario, Canada, sir.")
    reg("how many continents are there", "There are seven continents: Asia, Africa, North America, South America, Antarctica, Europe, and Australia, sir.")
    reg("how many oceans are there", "Five oceans are recognized today: Pacific, Atlantic, Indian, Southern, and Arctic, sir.")
    reg("what is the equator", "The equator is the invisible line of zero latitude circling Earth's middle, where days and nights stay nearly equal, sir.")
    reg("what is the prime meridian", "The Prime Meridian marks zero longitude, running through Greenwich, England since 1884, sir.")
    reg("largest continent", "Asia is the largest continent, holding about 60 percent of the world's population, sir.")
    reg("what is the danube river", "The Danube is Europe's second-longest river, flowing through or alongside ten countries and four capitals, sir.")
    reg("what is lake titicaca", "Lake Titicaca sits high in the Andes between Peru and Bolivia, the highest navigable large lake in the world, sir.")
    reg("what is the arctic circle", "The Arctic Circle is the latitude at 66.5 degrees north, north of which the summer sun never sets, sir.")
    reg("what is the ring of fire", "The Ring of Fire is a horseshoe of volcanoes and quake-prone faults ringing the Pacific, hosting about three-quarters of Earth's volcanoes, sir.")
    reg("what is the bermuda triangle", "The Bermuda Triangle is a legendary region of the North Atlantic where ships and planes were rumored to vanish; statistics show nothing unusual, sir.")
    reg("driest place on earth", "Chile's Atacama Desert can go years without meaningful rain, the driest non-polar place on Earth, sir.")
    reg("wettest place on earth", "Mawsynram in Meghalaya, India records the highest average annual rainfall, drenched by monsoon skies, sir.")
    reg("coldest place on earth", "Vostok Station in Antarctica recorded minus 89.2 degrees Celsius in 1983, the coldest temperature ever measured, sir.")
    reg("hottest place on earth", "Death Valley, California hit 56.7 degrees Celsius in 1913, still the hottest reliably recorded temperature, sir.")
    reg("how many time zones in the world", "Theoretically 24, one per hour, but real-world offsets create nearly 40 distinct time zones, sir.")
    reg("describe the flag of japan", "Japan's flag is a crimson disc representing the sun, centered on a plain white field, sir.")
    reg("describe the flag of canada", "Canada's flag shows a red maple leaf flanked by red bars on white, adopted in 1965, sir.")
    reg("describe the flag of brazil", "Brazil's flag features a green field, yellow diamond, and blue globe with stars and the motto Ordem e Progresso, sir.")
    reg("describe the flag of india", "India's tricolor runs saffron, white, and green with the navy Ashoka Chakra wheel at center, sir.")
    reg("describe the flag of switzerland", "Switzerland's flag is a bold white cross on red, one of only two square national flags, sir.")
    reg("which country has the most islands", "Sweden tops the list with roughly 267,000 islands, though most are uninhabited, sir.")
    reg("what is the sahara desert", "The Sahara is the world's largest hot desert, sweeping 9 million square kilometers across North Africa, sir.")
    reg("who invented the computer", "Charles Babbage designed the mechanical Analytical Engine in the 1830s and is honored as the father of the computer, sir.")
    reg("who invented the internet", "No single inventor: ARPANET connected the first nodes in 1969, built by teams funded by the US Department of Defense, sir.")
    reg("who invented the telephone", "Alexander Graham Bell received the first telephone patent in 1876, sir.")
    reg("who invented television", "John Logie Baird demonstrated early mechanical TV in 1926, while Philo Farnsworth's electronic design followed in 1927, sir.")
    reg("who invented email", "Ray Tomlinson sent the first network email to himself in 1971 and chose the @ symbol for addresses, sir.")
    reg("who invented the computer mouse", "Douglas Engelbart invented the mouse in the 1960s while exploring human-computer interaction, sir.")
    reg("first programming language", "Konrad Zuse designed Plankalkul in the 1940s, but Fortran, released in 1957, was the first widely used high-level language, sir.")
    reg("what was the first computer virus", "Creeper, written in 1971, hopped between ARPANET machines displaying 'I'm the creeper, catch me if you can', sir.")
    reg("when was the first video game made", "Physicist William Higinbotham built Tennis for Two in 1958, while Pong brought video games to the public in 1972, sir.")
    reg("when was the first iphone released", "Steve Jobs unveiled the iPhone in January 2007 and it went on sale that June, sir.")
    reg("when was google founded", "Larry Page and Sergey Brin founded Google in September 1998 while PhD students at Stanford, sir.")
    reg("when was facebook founded", "Mark Zuckerberg launched Facebook from his Harvard dorm room in February 2004, sir.")
    reg("when was amazon founded", "Jeff Bezos started Amazon in 1994 as an online bookstore operating out of his garage, sir.")
    reg("when was microsoft founded", "Bill Gates and Paul Allen founded Microsoft in April 1975 to write software for the Altair, sir.")
    reg("when was apple founded", "Steve Jobs, Steve Wozniak, and Ronald Wayne founded Apple on April 1, 1976, in a garage, sir.")
    reg("when was tesla founded", "Tesla Motors was founded in 2003 by Martin Eberhard and Marc Tarpenning; Elon Musk joined early as an investor and later CEO, sir.")
    reg("when was openai founded", "OpenAI was founded in December 2015 by Sam Altman, Elon Musk, Greg Brockman, and other researchers, sir.")
    reg("who founded google", "Larry Page and Sergey Brin founded Google in 1998, building on their BackRub search research, sir.")
    reg("who founded microsoft", "Childhood friends Bill Gates and Paul Allen founded Microsoft in 1975, sir.")
    reg("who founded apple", "Steve Jobs and Steve Wozniak co-founded Apple in 1976 with Ronald Wayne, sir.")
    reg("who founded facebook", "Mark Zuckerberg co-founded Facebook in 2004 with classmates Saverin, Hughes, Moskovitz, and the Winklevoss twins, sir.")
    reg("what does cpu stand for", "CPU means Central Processing Unit, the chip that executes your computer's instructions, sir.")
    reg("what does gpu stand for", "GPU means Graphics Processing Unit, specialized hardware for rendering images and parallel computing, sir.")
    reg("what does ram stand for", "RAM means Random Access Memory, your computer's fast temporary workspace, sir.")
    reg("what does ssd stand for", "SSD means Solid-State Drive, storage with no moving parts that is far faster than old hard disks, sir.")
    reg("what does url stand for", "URL means Uniform Resource Locator, the address your browser uses to find a page, sir.")
    reg("what does html stand for", "HTML means HyperText Markup Language, the standard structure behind every web page, sir.")
    reg("what does http stand for", "HTTP means HyperText Transfer Protocol, the rules browsers use to fetch web pages, sir.")
    reg("what does usb stand for", "USB means Universal Serial Bus, the standard port connecting peripherals to computers, sir.")
    reg("what does led stand for", "LED means Light-Emitting Diode, an efficient semiconductor light source, sir.")
    reg("what does pdf stand for", "PDF means Portable Document Format, created by Adobe in 1993 to preserve layout everywhere, sir.")
    reg("what does wifi stand for", "Wi-Fi does not technically stand for anything; it is a brand name playing on hi-fi for wireless networking, sir.")
    reg("what does npc stand for", "NPC means Non-Player Character, any game character not controlled by a human, sir.")
    reg("what does rpg stand for", "In gaming RPG means Role-Playing Game, where players develop characters over long adventures, sir.")
    reg("what does fps mean in games", "FPS can mean First-Person Shooter genre or Frames Per Second performance measure, depending on context, sir.")
    reg("what is a gigabyte", "A gigabyte is about one billion bytes, enough to store roughly 250 songs or a few hundred photos, sir.")
    reg("difference between ram and rom", "RAM is fast working memory wiped when power cuts; ROM permanently stores startup instructions that survive shutdowns, sir.")
    reg("difference between hardware and software", "Hardware is the physical machinery you can touch; software is the code and programs telling it what to do, sir.")
    reg("what is an operating system", "The operating system manages hardware and apps; Windows, macOS, Linux, Android, and iOS are examples, sir.")
    reg("what is a web browser", "A browser fetches and renders websites; Chrome, Safari, Firefox, and Edge are popular ones, sir.")
    reg("what is bluetooth technology", "Bluetooth provides short-range wireless connections between devices, named after a 10th-century Danish king, sir.")
    reg("what is 5g network", "5G is the fifth generation of cellular networks, delivering faster speeds and lower latency than 4G, sir.")
    reg("what does lte stand for", "LTE means Long-Term Evolution, the technical standard behind most 4G mobile networks, sir.")
    reg("what is nfc", "NFC means Near-Field Communication, the tap-to-pay chip technology in phones and cards, sir.")
    reg("what is gps and how does it work", "GPS receivers listen to signals from orbiting satellites and triangulate timing differences to pinpoint your location, sir.")
    reg("what is a qr code", "A QR code is a square barcode storing data readable by cameras, invented by Denso Wave in Japan in 1994, sir.")
    reg("how does facial recognition work", "Facial recognition maps distances between facial landmarks into a mathematical signature for matching, sir.")
    reg("what is voice recognition", "Voice recognition converts spoken words into text or commands using acoustic and language models, sir.")
    reg("what is chatgpt", "ChatGPT is OpenAI's conversational AI chatbot launched in November 2022, built on the GPT language model family, sir.")
    reg("what is firmware", "Firmware is low-level software baked into hardware that controls how the device boots and behaves, sir.")
    reg("what is a device driver", "A driver is software that lets the operating system communicate with specific hardware like printers or GPUs, sir.")
    reg("what is a kernel", "The kernel is the core of an operating system, managing memory, processes, and hardware access, sir.")
    reg("what is an emulator", "An emulator mimics one computing system inside another, letting old consoles run on modern machines, sir.")
    reg("what is overclocking", "Overclocking pushes a processor above its rated speed for extra performance at the cost of heat and stability, sir.")
    reg("what is two factor authentication", "Two-factor authentication adds a second proof of identity, usually a code sent to your phone, beyond your password, sir.")
    reg("what is end to end encryption", "End-to-end encryption scrambles messages so only sender and receiver can read them; not even the service provider can, sir.")
    reg("what are internet cookies", "Cookies are small files sites store on your browser to remember logins, carts, preferences, and tracking data, sir.")
    reg("what is ransomware", "Ransomware is malware that encrypts victims' files and demands payment for the unlock key, sir.")
    reg("what is spyware", "Spyware secretly installs itself to monitor activity and harvest personal data without consent, sir.")
    reg("what is a smart contract", "A smart contract is self-executing code on a blockchain that runs automatically when conditions are met, sir.")
    reg("who directed jurassic park", "Steven Spielberg directed Jurassic Park, released in 1993 with groundbreaking dinosaur effects, sir.")
    reg("who directed inception", "Christopher Nolan wrote and directed Inception, the 2010 dreams-within-dreams thriller, sir.")
    reg("who directed titanic movie", "James Cameron directed Titanic, which swept the 1998 Oscars with eleven wins, sir.")
    reg("who directed avatar movie", "James Cameron directed Avatar, pioneering 3D motion capture when it premiered in 2009, sir.")
    reg("who directed the godfather", "Francis Ford Coppola adapted The Godfather to screen in 1972, widely considered cinema's greatest film, sir.")
    reg("who directed star wars", "George Lucas wrote and directed the original Star Wars in 1977, sir.")
    reg("who directed pulp fiction", "Quentin Tarantino directed Pulp Fiction in 1994, winning the Palme d'Or and an original screenplay Oscar, sir.")
    reg("what was the first movie ever made", "Louis Le Prince's Roundhay Garden Scene from 1888 is considered the earliest surviving film, barely two seconds long, sir.")
    reg("highest grossing movie of all time", "Avatar holds the global box office crown with nearly 3 billion dollars including its re-releases, sir.")
    reg("which movie won the most oscars", "Ben-Hur, Titanic, and The Lord of the Rings: The Return of the King share the record with eleven Academy Awards each, sir.")
    reg("who has won the most oscars ever", "Walt Disney personally won 22 competitive Academy Awards, the record for any individual, sir.")
    reg("why is it called an oscar", "Academy Awards got the nickname Oscar reportedly from a librarian who said the statuette resembled her Uncle Oscar, sir.")
    reg("who created mickey mouse", "Walt Disney and animator Ub Iwerks created Mickey Mouse, who debuted in Steamboat Willie in 1928, sir.")
    reg("what was disney's first animated movie", "Snow White and the Seven Dwarfs in 1937 was Disney's and Hollywood's first full-length animated feature, sir.")
    reg("how many harry potter movies are there", "Eight films adapt the seven Harry Potter books, with the final novel split into two parts, sir.")
    reg("who wrote harry potter books", "J.K. Rowling wrote the seven Harry Potter novels between 1997 and 2007, sir.")
    reg("who is called the king of pop", "Michael Jackson earned the title King of Pop with albums like Thriller, the best-selling album ever, sir.")
    reg("who is called the queen of pop", "Madonna is widely dubbed the Queen of Pop for decades of chart-topping reinvention, sir.")
    reg("who were the beatles members", "John Lennon, Paul McCartney, George Harrison, and Ringo Starr formed the Beatles out of Liverpool in 1960, sir.")
    reg("who wrote the song imagine", "John Lennon wrote Imagine, released in 1971 as a solo artist after the Beatles split, sir.")
    reg("how many symphonies did beethoven write", "Beethoven completed nine symphonies, composing the Ninth while completely deaf, sir.")
    reg("what is a grammy award", "The Grammy honors musical excellence each year, presented by the Recording Academy since 1959, sir.")
    reg("who wrote the book 1984", "George Orwell published Nineteen Eighty-Four in 1949, warning of surveillance and totalitarianism, sir.")
    reg("who wrote pride and prejudice", "Jane Austen wrote Pride and Prejudice, published in 1813, sir.")
    reg("who wrote moby dick", "Herman Melville wrote Moby-Dick, the tale of Captain Ahab's obsession with the white whale, sir.")
    reg("who wrote war and peace", "Leo Tolstoy wrote War and Peace, the epic of Napoleonic-era Russia, sir.")
    reg("who wrote oliver twist", "Charles Dickens wrote Oliver Twist, serialised in 1837, sir.")
    reg("who wrote hamlet", "William Shakespeare wrote Hamlet around 1600, giving us 'To be or not to be', sir.")
    reg("who wrote the hobbit", "J.R.R. Tolkien wrote The Hobbit in 1937, opening the door to Middle-earth, sir.")
    reg("who wrote sherlock holmes", "Sir Arthur Conan Doyle created Sherlock Holmes, the consulting detective of 221B Baker Street, sir.")
    reg("who wrote frankenstein", "Mary Shelley wrote Frankenstein at just 18, publishing it anonymously in 1818, sir.")
    reg("who wrote dracula novel", "Bram Stoker wrote Dracula, published in 1897, defining vampire fiction forever, sir.")
    reg("who wrote little women", "Louisa May Alcott wrote Little Women, drawing on her own upbringing, sir.")
    reg("who wrote jane eyre", "Charlotte Bronte wrote Jane Eyre, published in 1847 under the pen name Currer Bell, sir.")
    reg("best selling book of all time", "The Bible is estimated to be the best-selling book in history, with over five billion copies printed, sir.")
    reg("what is the best selling video game", "Minecraft is the best-selling video game ever, surpassing 300 million copies sold, sir.")
    reg("who created mario", "Game designer Shigeru Miyamoto created Mario, debuting in Donkey Kong in 1981, sir.")
    reg("who created pokemon", "Satoshi Tajiri created Pokemon inspired by his childhood insect collecting, launching in 1996, sir.")
    reg("when was pacman released", "Pac-Man chomped into arcades in May 1980 and became an instant cultural phenomenon, sir.")
    reg("who created tetris", "Soviet engineer Alexey Pajitnov created Tetris in 1984 while working in Moscow, sir.")
    reg("how many seasons of game of thrones", "Game of Thrones ran for eight seasons on HBO from 2011 to 2019, sir.")
    reg("who created the simpsons", "Matt Groening created The Simpsons, which debuted in 1989 as television's longest-running sitcom, sir.")
    reg("how many seasons did friends run", "Friends aired ten seasons from 1994 to 2004, following six friends through their twenties and thirties, sir.")
    reg("what was netflix's first original series", "House of Cards premiered in February 2013 as Netflix's flagship original series, sir.")
    reg("what does oscar award look like", "The Oscar statuette depicts a knight gripping a sword, standing on a reel of film, plated in gold, sir.")
    reg("which actor played iron man", "Robert Downey Jr. played Tony Stark across the Marvel Cinematic Universe starting in 2008, sir.")
    reg("who played jack in titanic", "Leonardo DiCaprio played Jack Dawson opposite Kate Winslet's Rose in Titanic, sir.")
    reg("who composed star wars music", "John Williams composed Star Wars' iconic score, including the main theme and Imperial March, sir.")
    reg("who wrote les miserables", "Victor Hugo wrote Les Miserables, published in 1862, later a legendary stage musical, sir.")
    reg("who wrote the count of monte cristo", "Alexandre Dumas wrote The Count of Monte Cristo, the ultimate tale of revenge, sir.")
    reg("who wrote crime and punishment", "Fyodor Dostoevsky wrote Crime and Punishment, published in 1866, sir.")
    reg("what was the first disney movie", "Snow White and the Seven Dwarfs, released in 1937, was Walt Disney Animation's first feature, sir.")
    reg("how many james bond actors are there", "Seven actors have played Bond on film: Connery, Lazenby, Moore, Dalton, Brosnan, Craig, and now Cavill-free era newcomer, sir.")
    reg("who sings shape of you", "Ed Sheeran released Shape of You in 2017, one of Spotify's most-streamed songs, sir.")
    reg("which band released bohemian rhapsody", "Queen released Bohemian Rhapsody in 1975, written by Freddie Mercury for A Night at the Opera, sir.")
    reg("who is the godfather of soul", "James Brown earned the title Godfather of Soul with hits like Papa's Got a Brand New Bag, sir.")
    reg("how many calories should i eat daily", "General guidelines suggest about 2,000 calories for women and 2,500 for men, varying with age, size, and activity, sir.")
    reg("what is a balanced diet", "A balanced diet mixes vegetables, fruits, whole grains, lean protein, healthy fats, and plenty of water in right proportions, sir.")
    reg("how much protein do i need daily", "Most adults need roughly 0.8 grams per kilogram of body weight, more if training hard or older, sir.")
    reg("is breakfast important", "A good breakfast fuels focus and energy and helps many people avoid mid-morning snacking, though total daily intake matters most, sir.")
    reg("benefits of green tea", "Green tea delivers antioxidants called catechins linked to heart health, gentle caffeine, and calm focus from L-theanine, sir.")
    reg("benefits of honey", "Honey offers antibacterial properties, soothes coughs, and sweetens naturally, but is still sugar best used in moderation, sir.")
    reg("benefits of ginger", "Ginger helps settle nausea, supports digestion, and carries anti-inflammatory compounds, fresh or as tea, sir.")
    reg("benefits of turmeric", "Turmeric's curcumin is a potent anti-inflammatory, absorbed better when paired with black pepper, sir.")
    reg("is coffee bad for you", "For most people moderate coffee, around three to four cups a day, is fine and may even benefit health, sir.")
    reg("how much water should i drink daily", "Aim for roughly two to three liters of fluids a day, more when exercising or in heat; thirst and pale urine are good guides, sir.")
    reg("what are superfoods", "Superfoods are nutrient-dense picks like berries, leafy greens, nuts, seeds, salmon, and eggs; no single food works magic, variety does, sir.")
    reg("what are probiotics", "Probiotics are beneficial live bacteria in yogurt, kefir, kimchi, and sauerkraut that support gut health, sir.")
    reg("what is gluten", "Gluten is a protein in wheat, barley, and rye that gives dough elasticity; harmful mainly to people with celiac disease, sir.")
    reg("what is keto diet", "The keto diet slashes carbs to under about 50 grams daily, pushing the body to burn fat for fuel in ketosis, sir.")
    reg("what is intermittent fasting", "Intermittent fasting restricts eating to set windows, commonly 16 hours fasting with an 8-hour eating period, sir.")
    reg("what is the mediterranean diet", "The Mediterranean diet emphasizes fish, olive oil, vegetables, whole grains, and nuts, strongly linked to heart health, sir.")
    reg("how to make pizza dough", "Mix flour, water, yeast, salt, and olive oil; knead until smooth, rise covered for an hour, then stretch and bake hot, sir.")
    reg("how to make pancakes", "Whisk flour, baking powder, sugar, egg, and milk into a thick batter, rest briefly, then cook on a greased medium pan till golden, sir.")
    reg("how to make scrambled eggs", "Beat eggs with a pinch of salt, cook slowly in butter over low heat, stirring gently, removing them just before they look done, sir.")
    reg("how to make fried rice", "Use day-old chilled rice, stir-fry aromatics and veggies in a very hot wok, add rice, soy sauce, and fold in egg at the end, sir.")
    reg("how to make grilled cheese", "Butter the outside of two bread slices, layer cheese between, and grill over medium heat until deep golden both sides, sir.")
    reg("how to make guacamole", "Mash ripe avocados with lime juice, chopped onion, cilantro, salt, and optional tomato and jalapeno, sir.")
    reg("how to make hummus", "Blend chickpeas with tahini, lemon juice, garlic, and olive oil until silky, loosening with cold water, sir.")
    reg("how to make roti", "Knead whole-wheat flour with water into soft dough, rest 20 minutes, roll thin rounds, and puff them on a hot tawa, sir.")
    reg("how to make dal tadka", "Simmer lentils with turmeric until soft, then pour over sizzling ghee tempered with cumin, garlic, chili, and tomato, sir.")
    reg("how to make biryani", "Layer parboiled basmati rice with marinated cooked meat, fried onions, herbs, and saffron milk, then seal and steam on dum, sir.")
    reg("how to make butter chicken", "Marinate chicken in yogurt and spices, char it, then simmer in a rich tomato-cashew gravy finished with butter and cream, sir.")
    reg("how to make masala chai", "Simmer water with crushed ginger, cardamom, and tea leaves, add milk, boil, strain, and sweeten to taste, sir.")
    reg("how to make a smoothie", "Blend frozen banana, berries, yogurt, milk, and a spoon of nut butter for a quick creamy smoothie, sir.")
    reg("how to make salad dressing", "Shake three parts olive oil with one part vinegar or lemon, a teaspoon mustard, salt, and pepper, sir.")
    reg("how to cook steak perfectly", "Pat dry, season generously, sear in a screaming-hot pan, and rest five minutes; aim for 54 C internal for medium rare, sir.")
    reg("how to cook salmon", "Roast salmon at 200 C for 12 to 15 minutes, or pan-sear skin-side down until crisp, sir.")
    reg("how to roast vegetables", "Toss chunks with oil, salt, and pepper and roast at 220 C for 25 to 35 minutes until caramelized at edges, sir.")
    reg("what temperature should chicken be cooked to", "Cook chicken to 74 degrees Celsius or 165 Fahrenheit internal temperature for safety, sir.")
    reg("how to tell if eggs are fresh", "Fresh eggs sink and lie flat in water; older ones stand upright, and floaters should be discarded, sir.")
    reg("how to ripen bananas faster", "Store bananas in a paper bag with an apple, or bake unpeeled at 150 C for 15 minutes for baking use, sir.")
    reg("how to keep herbs fresh", "Treat soft herbs like flowers: trim stems, stand in water, and cover loosely in the fridge, sir.")
    reg("how to store onions", "Keep onions in a cool, dark, well-ventilated spot away from potatoes, which make them sprout faster, sir.")
    reg("how to stop onions making you cry", "Chill the onion first, use a sharp knife, and cut the root end last to release fewer irritant compounds, sir.")
    reg("substitute for butter in baking", "Swap melted coconut oil or neutral oil cup-for-cup, or applesauce for half the fat in moist cakes, sir.")
    reg("egg substitute in baking", "One tablespoon ground flaxseed mixed with three of water replaces one egg in muffins and pancakes, sir.")
    reg("substitute for heavy cream", "Mix three-quarters milk with one-quarter melted butter as a stand-in for cream in cooking, not whipping, sir.")
    reg("substitute for buttermilk", "Stir one tablespoon lemon juice or vinegar into a cup of milk and rest five minutes, sir.")
    reg("what is umami taste", "Umami is the savory fifth taste found in tomatoes, mushrooms, soy sauce, parmesan, and miso, driven by glutamates, sir.")
    reg("what is mise en place", "Mise en place means prepping and measuring every ingredient before cooking begins, the professional kitchen way, sir.")
    reg("what does al dente mean", "Al dente means pasta cooked firm to the bite, holding structure in sauce, sir.")
    reg("what is sauteing", "Sauteing cooks food fast in a little fat over fairly high heat, tossing or stirring constantly, sir.")
    reg("what is blanching", "Blanching means boiling vegetables briefly then shocking them in ice water to lock color and snap, sir.")
    reg("what is marinating", "Marinating soaks food in seasoned liquid to tenderize and infuse flavor, ideally 30 minutes to overnight, sir.")
    reg("baking soda vs baking powder", "Baking soda needs an acid like buttermilk to react; baking powder contains its own acid and works alone, sir.")
    reg("what is sourdough starter", "A sourdough starter is fermented flour and water hosting wild yeast and bacteria that raise bread with tang, sir.")
    reg("is spicy food good for you", "Capsaicin in chilies may modestly boost metabolism and releases endorphins; fine for most stomachs in moderation, sir.")
    reg("what is the scoville scale", "The Scoville scale measures chili heat by capsaicin concentration, from bell pepper zero to millions of units, sir.")
    reg("what is the hottest pepper in the world", "Pepper X holds the Guinness record at over 2.6 million Scoville units, dethroning the Carolina Reaper, sir.")
    reg("why does cilantro taste like soap to some", "Some people carry gene variants making cilantro aldehydes register as soapy; totally genetic, sir.")
    reg("what is tofu made of", "Tofu is condensed soy milk curdled with calcium or magnesium salts and pressed into blocks, sir.")
    reg("how to cook quinoa", "Rinse quinoa well, simmer one part grain in two parts water for 15 minutes, then rest and fluff, sir.")
    reg("benefits of regular exercise", "Regular exercise strengthens the heart, lifts mood through endorphins, sharpens memory, and improves sleep, sir.")
    reg("how much exercise per week", "Guidelines recommend 150 minutes of moderate cardio weekly plus two strength sessions, sir.")
    reg("benefits of walking daily", "Thirty minutes of walking daily lowers blood pressure, burns calories, clears the mind, and needs no equipment, sir.")
    reg("benefits of running", "Running builds cardiovascular fitness, strengthens bones, and floods the brain with mood-lifting endorphins, sir.")
    reg("benefits of swimming", "Swimming works nearly every muscle with minimal joint impact, ideal cross-training for all ages, sir.")
    reg("benefits of yoga", "Yoga improves flexibility, balance, posture, and measurably reduces stress hormones, sir.")
    reg("benefits of stretching daily", "Daily stretching keeps muscles supple, eases stiffness, improves circulation, and guards against injury, sir.")
    reg("best exercises for abs", "Planks, hanging leg raises, and bicycle crunches build core strength better than endless sit-ups, sir.")
    reg("best exercise to lose weight", "Combine strength training with steady cardio and daily walks; consistency beats intensity for fat loss, sir.")
    reg("how to improve posture", "Strengthen your core and upper back, set screens at eye height, and take movement breaks hourly, sir.")
    reg("how to relieve stress quickly", "Slow breathing for two minutes, a brisk walk, or stepping outside can drop stress hormones fast, sir.")
    reg("how to reduce anxiety naturally", "Try grounding techniques, limit caffeine, exercise regularly, keep sleep consistent, and talk to someone you trust, sir.")
    reg("tips for better sleep", "Fix your wake-up time, keep the bedroom cool and dark, skip screens an hour before bed, and avoid late caffeine, sir.")
    reg("how many hours of sleep do adults need", "Adults function best on seven to nine hours nightly; teenagers need eight to ten, sir.")
    reg("what is rem sleep", "REM is the dreaming stage where your brain consolidates memories and processes emotions, cycling every 90 minutes, sir.")
    reg("how to boost immune system naturally", "Prioritize sleep, eat colorful whole foods, manage stress, exercise moderately, and stay vaccinated, sir.")
    reg("foods good for brain health", "Fatty fish, walnuts, blueberries, leafy greens, and eggs supply omega-3s and antioxidants brains love, sir.")
    reg("foods good for eyesight", "Carrots, spinach, kale, eggs, and oily fish provide lutein, vitamin A, and omega-3s for retinal health, sir.")
    reg("foods rich in iron", "Red meat, lentils, chickpeas, spinach, and fortified cereals are rich in iron; pair with vitamin C to absorb more, sir.")
    reg("foods rich in calcium", "Dairy, fortified plant milks, tofu, almonds, and leafy greens deliver bone-building calcium, sir.")
    reg("foods rich in vitamin c", "Citrus fruits, bell peppers, kiwi, strawberries, and broccoli pack vitamin C, sir.")
    reg("foods rich in vitamin d", "Sunlight triggers vitamin D production; fatty fish, egg yolks, and fortified milk help too, sir.")
    reg("high fiber foods list", "Beans, lentils, oats, chia seeds, raspberries, and whole grains push you toward the 25 to 30 grams daily target, sir.")
    reg("what does protein do for the body", "Protein builds and repairs tissue, powers enzymes and hormones, and supports immune defense, sir.")
    reg("signs of dehydration", "Dark urine, headache, dizziness, dry lips, and fatigue signal dehydration; sip water steadily, sir.")
    reg("benefits of drinking enough water", "Proper hydration regulates temperature, cushions joints, aids digestion, and keeps concentration sharp, sir.")
    reg("is sitting all day bad for you", "Prolonged sitting slows metabolism and strains the back; stand or walk for a few minutes every hour, sir.")
    reg("what is carpal tunnel syndrome", "Carpal tunnel squeezes the wrist nerve causing numb, tingling fingers; ergonomics, splints, and breaks help, sir.")
    reg("how to reduce eye strain from screens", "Follow 20-20-20: every twenty minutes look at something twenty feet away for twenty seconds, sir.")
    reg("what is normal body temperature", "Normal averages 37 degrees Celsius or 98.6 Fahrenheit, ranging about 36.1 to 37.2 through the day, sir.")
    reg("what is normal resting heart rate", "Adult resting hearts beat 60 to 100 times per minute; trained athletes often sit near 40 to 60, sir.")
    reg("how to lower blood pressure naturally", "Cut sodium, eat potassium-rich foods, exercise aerobically, limit alcohol, and manage weight and stress, sir.")
    reg("what do cholesterol numbers mean", "LDL is the artery-clogging kind best kept low; HDL is protective and higher levels are favorable, sir.")
    reg("what is good cholesterol", "HDL acts like a cleanup crew, ferrying cholesterol away from arteries back to the liver, sir.")
    reg("how to calculate bmi", "Divide weight in kilograms by height in meters squared; 18.5 to 24.9 is the usual healthy band, sir.")
    reg("benefits of meditation daily", "Ten minutes of meditation lowers cortisol, steadies attention, and rewires emotional regulation over weeks, sir.")
    reg("what is mindfulness", "Mindfulness means noticing the present moment without judgment, trainable through breath and body awareness, sir.")
    reg("tips to quit smoking", "Pick a quit date, consider nicotine replacement, identify triggers, chew substitutes, and lean on support lines, sir.")
    reg("effects of too much sugar", "Excess sugar drives weight gain, insulin resistance, dental decay, and energy rollercoasters, sir.")
    reg("effects of too much salt", "High sodium raises blood pressure and burdens kidneys; keep under about 2,300 milligrams daily, sir.")
    reg("is red meat bad for you", "Lean red meat occasionally is acceptable, but processed meats correlate with higher disease risk; moderation wins, sir.")
    reg("are eggs actually healthy", "Yes, for most people eggs offer quality protein, choline, and nutrients without meaningfully raising heart risk, sir.")
    reg("is dark chocolate good for you", "Dark chocolate above 70 percent cocoa carries flavonoids and antioxidants; enjoy small squares, sir.")
    reg("what causes headaches", "Common culprits include dehydration, tension, poor sleep, skipped meals, screen glare, and stress, sir.")
    reg("home remedies for headaches", "Hydrate, rest eyes in a dark quiet room, apply a cool compress, and try gentle neck stretches, sir.")
    reg("what causes muscle cramps", "Cramps stem from dehydration, electrolyte imbalances, fatigue, or prolonged positions; hydrate and stretch, sir.")
    reg("why am i sore after working out", "Post-workout soreness comes from microscopic muscle tears repairing stronger, peaking 24 to 72 hours later, sir.")
    reg("what is doms", "DOMS means Delayed Onset Muscle Soreness, the aching that peaks one to two days after unfamiliar exercise, sir.")
    reg("how to treat minor burns", "Cool the burn under running water ten to twenty minutes, skip ice, cover loosely, and avoid popping blisters, sir.")
    reg("how to treat a minor cut", "Wash the wound, apply firm pressure to stop bleeding, elevate, cover with a clean bandage, and watch for infection, sir.")
    reg("when to see a doctor for fever", "Seek care for fevers above 39.4 C lasting over three days, or with stiff neck, confusion, or breathing trouble, sir.")
    reg("target heart rate during exercise", "Moderate zone sits at 50 to 70 percent of max heart rate, estimated as 220 minus your age, sir.")
    reg("how many steps per day is healthy", "Research links 8,000 to 10,000 steps daily with lower mortality, though every extra thousand counts, sir.")
    reg("benefits of deep breathing exercises", "Deep breathing activates the calming nervous system, dropping heart rate and blood pressure within minutes, sir.")
    reg("what is box breathing", "Box breathing inhales, holds, exhales, and holds again for four counts each; special forces use it to stay calm, sir.")
    reg("is cold shower good for you", "Cold showers can boost alertness, circulation, and possibly mood; start with thirty seconds at the end, sir.")
    reg("how many players in a soccer team", "Each soccer team fields eleven players including the goalkeeper, sir.")
    reg("how many players in a cricket team", "Cricket sides have eleven players each, mixing batsmen, bowlers, and a wicketkeeper, sir.")
    reg("how many players on a basketball court per team", "Basketball puts five players from each team on court, sir.")
    reg("how many players in volleyball team", "Indoor volleyball starts six players per side, rotating through positions, sir.")
    reg("how long is a football match", "A soccer match lasts 90 minutes plus stoppage, split into two halves, sir.")
    reg("how long is an nba basketball game", "NBA games run four 12-minute quarters, realistically about two and a quarter hours with stops, sir.")
    reg("how long is a marathon", "A marathon covers 42.195 kilometers, or 26.2 miles, sir.")
    reg("what is a half marathon distance", "A half marathon measures 21.0975 kilometers, or 13.1 miles, sir.")
    reg("what is offside rule in football", "A player is offside if positioned beyond the last defender when a teammate passes forward to them, sir.")
    reg("what is lbw in cricket", "LBW, leg before wicket, dismisses a batter when ball-striking pads would have hit the stumps, sir.")
    reg("what is a googly in cricket", "A googly is a leg-spinner's delivery that spins the opposite way, deceiving the batter, sir.")
    reg("how long does a test match last", "Test cricket is scheduled for five days, up to 90 overs per day, sir.")
    reg("what is a duck in cricket", "A duck means a batter was dismissed without scoring; a golden duck falls on the very first ball, sir.")
    reg("what is hat trick in sports", "A hat trick is three successes in a row: three goals in football, three wickets in consecutive balls in cricket, sir.")
    reg("how often are olympics held", "Summer and Winter Olympics alternate every two years, each Games held every four, sir.")
    reg("what do the olympic rings represent", "The five interlocking rings symbolize the five inhabited continents united by sport, sir.")
    reg("who has the most olympic medals ever", "Michael Phelps collected 28 medals, 23 gold, the most of any Olympian in history, sir.")
    reg("fastest 100m sprint record", "Usain Bolt's 9.58 seconds from Berlin 2009 remains the 100-meter world record, sir.")
    reg("who invented basketball", "Dr. James Naismith invented basketball in 1891 with peach baskets in a Springfield gym, sir.")
    reg("who invented volleyball", "William G. Morgan invented volleyball in 1895, calling it mintonette, sir.")
    reg("where did soccer originate", "Modern association football codified in England in 1863, though kicking games existed worldwide for centuries, sir.")
    reg("which country invented cricket", "Cricket evolved in southeast England, with rules codified by the Marylebone Cricket Club in 1788, sir.")
    reg("what is the fifa world cup", "The FIFA World Cup crowns international soccer's champion every four years, sport's biggest event, sir.")
    reg("which country won the most fifa world cups", "Brazil leads with five men's World Cup titles, most recently in 2002, sir.")
    reg("what is the super bowl", "The Super Bowl is the NFL championship final and America's most-watched broadcast annually, sir.")
    reg("what is wimbledon tournament", "Wimbledon is tennis's oldest Grand Slam, played on grass in London since 1877, sir.")
    reg("most wimbledon titles", "Martina Navratilova won nine Wimbledon singles titles; Roger Federer leads the gentlemen with eight, sir.")
    reg("how long does a tennis match last", "Tennis has no clock; matches run until someone wins two sets, or three in Grand Slam men's events, sir.")
    reg("what is deuce in tennis", "Deuce means 40-40, requiring a player to win two straight points to take the game, sir.")
    reg("why is zero called love in tennis", "Love for zero likely derives from the French l'oeuf, the egg, shaped like a zero, sir.")
    reg("tennis scoring explained", "Points climb 15, 30, 40, then game; six games take a set, typically two sets take the match, sir.")
    reg("what is a birdie in golf", "A birdie means completing a hole one stroke under par, sir.")
    reg("what is an eagle in golf", "An eagle scores two strokes under par on a hole, rarer than a birdie, sir.")
    reg("how many holes in a golf round", "A standard round plays eighteen holes, sir.")
    reg("what is par in golf", "Par is the expected number of strokes an expert needs per hole, usually three to five, sir.")
    reg("what is a strike in bowling", "A strike knocks down all ten pins on the first roll, worth bonus points, sir.")
    reg("perfect score in bowling", "Twelve consecutive strikes yield a perfect 300 game, sir.")
    reg("how many squares on a chessboard", "A chessboard has 64 squares, alternating light and dark, sir.")
    reg("how many pieces in chess", "Each chess player commands sixteen pieces: eight pawns, two rooks, knights, bishops, one queen, one king, sir.")
    reg("what is checkmate in chess", "Checkmate traps the king under attack with no legal escape, ending the game instantly, sir.")
    reg("who is the best chess player today", "Magnus Carlsen dominated world chess as champion from 2013 and remains rated number one, sir.")
    reg("what is f1 racing", "Formula 1 is the pinnacle of single-seater circuit racing, running grand prix weekends worldwide, sir.")
    reg("how long is an f1 race", "Grand prix races run about 305 kilometers or two hours, whichever comes first, sir.")
    reg("who has the most f1 world championships", "Lewis Hamilton and Michael Schumacher share the record with seven drivers' titles each, sir.")
    reg("what is tour de france", "The Tour de France is cycling's premier stage race, covering roughly 3,500 kilometers each July, sir.")
    reg("what is triathlon race order", "Triathlon goes swim, bike, run, in that order, with standard Olympic distances of 1.5k, 40k, and 10k, sir.")
    reg("what is an ironman triathlon", "An Ironman demands a 3.86 km swim, 180 km bike ride, and full marathon run, sir.")
    reg("what is the ashes series", "The Ashes is cricket's storied England versus Australia Test rivalry dating to 1882, sir.")
    reg("what is ipl cricket", "The Indian Premier League is cricket's richest T20 tournament, launched in 2008 with city franchises, sir.")
    reg("who won the most cricket world cups", "Australia has lifted six ODI Cricket World Cups, most recently in 2023, sir.")
    reg("what is a penalty kick", "A penalty awards a shot at goal from twelve yards with only the keeper to beat, for fouls inside the box, sir.")
    reg("what is free kick in football", "A free kick restarts play after a foul, direct versions able to score without touching another player, sir.")
    reg("what is a corner kick", "A corner kick restarts play from the flag after defenders put the ball over their own goal line, sir.")
    reg("how long is a hockey game", "NHL ice hockey plays three 20-minute periods plus overtime, about two and a half hours total, sir.")
    reg("what is a slam dunk", "A dunk slams the ball directly through the hoop, worth two points and maximum style, sir.")
    reg("three point line distance", "The NBA arc sits 7.24 meters from the basket; FIBA uses 6.75 meters, sir.")
    reg("what is boxing weight class", "Weight classes group fighters fairly, from flyweight around 51 kg to heavyweight unlimited, sir.")
    reg("another word for happy", "Try joyful, delighted, cheerful, contented, or elated instead of happy, sir.")
    reg("another word for sad", "Consider unhappy, sorrowful, gloomy, melancholy, or downcast instead of sad, sir.")
    reg("another word for big", "Alternatives to big include large, huge, enormous, massive, and gigantic, sir.")
    reg("another word for small", "You could say little, tiny, miniature, compact, or petite, sir.")
    reg("another word for fast", "Swap in quick, rapid, swift, speedy, or brisk, sir.")
    reg("another word for smart", "Intelligent, clever, brilliant, sharp, and astute all work, sir.")
    reg("another word for beautiful", "Lovely, gorgeous, stunning, exquisite, and radiant are elegant choices, sir.")
    reg("another word for strong", "Powerful, sturdy, robust, tough, and mighty convey strength, sir.")
    reg("opposite of happy", "The opposite of happy is sad, miserable, or dejected, sir.")
    reg("opposite of success", "Failure is the direct antonym of success, sir.")
    reg("opposite of generous", "Stingy, miserly, or selfish oppose generous, sir.")
    reg("opposite of optimist", "A pessimist expects the worst, opposite of an optimist, sir.")
    reg("opposite of brave", "Cowardly, timid, or fearful stand against brave, sir.")
    reg("opposite of increase", "Decrease or reduce is the opposite of increase, sir.")
    reg("what is a noun", "A noun names a person, place, thing, or idea, like teacher, city, book, or freedom, sir.")
    reg("what is a verb", "A verb expresses action or being, like run, think, or is, sir.")
    reg("what is an adjective", "An adjective describes a noun, like bright sky or tall tree, sir.")
    reg("what is an adverb", "An adverb modifies verbs or adjectives, answering how, when, or degree, like quickly or very, sir.")
    reg("what is a pronoun", "A pronoun replaces a noun, like he, she, they, or it, avoiding repetition, sir.")
    reg("what is a preposition", "A preposition links nouns to other words showing relationships, like on, under, before, or with, sir.")
    reg("what is a conjunction", "A conjunction joins words or clauses, like and, but, or because, sir.")
    reg("what is an interjection", "An interjection bursts in with emotion, like wow, ouch, or hey, sir.")
    reg("difference between its and it's", "Its shows possession while it's is short for it is or it has, sir.")
    reg("difference between your and you're", "Your indicates possession; you're contracts you are, sir.")
    reg("difference between their there and they're", "Their shows possession, there points to a place, and they're means they are, sir.")
    reg("difference between affect and effect", "Affect is usually the verb meaning to influence; effect is usually the noun meaning result, sir.")
    reg("difference between then and than", "Then relates to time or sequence; than makes comparisons, sir.")
    reg("difference between who and whom", "Who acts as subject, whom receives the action; try substituting he or him to test, sir.")
    reg("what is a metaphor", "A metaphor compares directly without like or as, saying time is money, sir.")
    reg("what is a simile", "A simile compares using like or as, brave as a lion, sir.")
    reg("what is hyperbole", "Hyperbole exaggerates wildly for effect, like I've told you a million times, sir.")
    reg("what is personification", "Personification gives human traits to nonhuman things, like the wind whispered, sir.")
    reg("what is alliteration", "Alliteration repeats initial sounds, as in Peter Piper picked a peck, sir.")
    reg("what is irony", "Irony is when outcomes contradict expectations, like a fire station burning down, sir.")
    reg("what is an idiom", "An idiom's meaning differs from its literal words, like it's raining cats and dogs, sir.")
    reg("what is onomatopoeia", "Onomatopoeia uses sound-mimicking words such as buzz, splash, and crash, sir.")
    reg("what is an oxymoron", "An oxymoron pairs contradictions, like deafening silence or bittersweet, sir.")
    reg("what is a palindrome", "A palindrome reads identically forwards and backwards, like racecar or madam, sir.")
    reg("what is a pangram sentence", "A pangram contains every letter; the classic is the quick brown fox jumps over the lazy dog, sir.")
    reg("longest word in english", "Pneumonoultramicroscopicvolcanoconiosis, 45 letters naming a lung disease, is the longest dictionary word, sir.")
    reg("how many words in english language", "The Oxford English Dictionary lists over 170,000 words in current use, with hundreds added yearly, sir.")
    reg("what language does brazil speak", "Brazil speaks Portuguese, a legacy of colonization by Portugal, sir.")
    reg("what language does egypt speak", "Egypt's official language is Arabic, with Egyptian Arabic the everyday dialect, sir.")
    reg("oldest written language", "Sumerian cuneiform from Mesopotamia around 3200 BC is the oldest known writing, sir.")
    reg("hardest languages to learn", "For English speakers, Mandarin, Arabic, Japanese, and Korean top difficulty charts due to scripts and grammar, sir.")
    reg("easiest languages for english speakers", "Spanish, French, Dutch, Norwegian, and Italian share vocabulary and structure with English, easing learning, sir.")
    reg("what does etymology study", "Etymology traces word origins and how meanings evolve over centuries, sir.")
    reg("origin of the word robot", "Robot comes from Czech robota, forced labor, coined in Karel Capek's 1920 play R.U.R., sir.")
    reg("origin of the word algebra", "Algebra derives from Arabic al-jabr, from the 9th-century mathematician al-Khwarizmi's treatise, sir.")
    reg("origin of the word algorithm", "Algorithm honors al-Khwarizmi, Latinized to Algoritmi, the Persian scholar of mathematics, sir.")
    reg("origin of the word salary", "Salary traces to Latin salarium, an allowance Roman soldiers received reportedly for buying salt, sir.")
    reg("origin of the word goodbye", "Goodbye contracted from God be with ye in 16th-century English farewell speeches, sir.")
    reg("what does aka stand for", "AKA stands for also known as, used for aliases and nicknames, sir.")
    reg("what does etc stand for", "Et cetera means and the rest, from Latin, closing open-ended lists, sir.")
    reg("meaning of ie abbreviation", "Id est means that is, clarifying or restating a previous point, sir.")
    reg("meaning of eg abbreviation", "Exempli gratia means for example, introducing illustrative items, sir.")
    reg("area of a circle formula", "Area equals pi times radius squared: A = pi r^2, sir.")
    reg("circumference of a circle formula", "Circumference equals two pi radius, or pi times diameter: C = 2 pi r, sir.")
    reg("area of triangle formula", "Area equals one-half base times height: A = (1/2)bh, sir.")
    reg("area of rectangle formula", "Multiply length by width: A = l x w, sir.")
    reg("volume of sphere formula", "Volume equals four-thirds pi cubed radius: V = (4/3) pi r^3, sir.")
    reg("volume of cylinder formula", "Volume equals pi times radius squared times height: V = pi r^2 h, sir.")
    reg("volume of cone formula", "Volume equals one-third pi radius squared height: V = (1/3) pi r^2 h, sir.")
    reg("pythagorean theorem", "In a right triangle, the legs squared sum to the hypotenuse squared: a^2 + b^2 = c^2, sir.")
    reg("quadratic formula", "For ax^2 + bx + c = 0, x equals negative b plus-minus the square root of b^2 minus 4ac, over 2a, sir.")
    reg("slope formula", "Slope m equals change in y over change in x: m = (y2 - y1)/(x2 - x1), sir.")
    reg("distance formula", "Distance between two points equals the square root of dx squared plus dy squared, from Pythagoras, sir.")
    reg("midpoint formula", "Midpoint coordinates average the endpoints: ((x1+x2)/2, (y1+y2)/2), sir.")
    reg("law of sines", "Each side over the sine of its opposite angle is equal: a/sinA = b/sinB = c/sinC, sir.")
    reg("law of cosines", "c^2 = a^2 + b^2 - 2ab cos(C), generalizing Pythagoras to any triangle, sir.")
    reg("equation of a line", "Slope-intercept form is y = mx + b, slope m crossing y-axis at b, sir.")
    reg("what is a derivative", "A derivative measures instantaneous rate of change, the slope of a curve at a point, sir.")
    reg("what is an integral", "An integral accumulates quantities, geometrically the area under a curve, sir.")
    reg("fundamental theorem of calculus", "Differentiation and integration are inverse operations, linking slopes to accumulated areas, sir.")
    reg("chain rule calculus", "For nested functions, differentiate outer then inner: (f(g(x)))' = f'(g(x)) * g'(x), sir.")
    reg("product rule calculus", "(uv)' = u'v + uv', differentiating products term by term, sir.")
    reg("quotient rule calculus", "(u/v)' = (u'v - uv')/v^2, sir.")
    reg("power rule derivative", "Bring the exponent down: d/dx x^n = n x^(n-1), sir.")
    reg("newton second law formula", "Force equals mass times acceleration: F = ma, sir.")
    reg("kinetic energy formula", "KE = one-half mv squared: KE = (1/2)mv^2, sir.")
    reg("potential energy formula", "Gravitational PE equals mgh, mass times gravity times height, sir.")
    reg("ohms law", "Voltage equals current times resistance: V = IR, sir.")
    reg("electrical power formula", "Power equals voltage times current: P = VI, equivalently I^2 R, sir.")
    reg("e mc2 explained", "Einstein showed energy equals mass times the speed of light squared, mass-energy equivalence, sir.")
    reg("ideal gas law", "Pressure times volume equals moles times gas constant times temperature: PV = nRT, sir.")
    reg("density formula", "Density equals mass divided by volume: rho = m/V, typically kg per cubic meter, sir.")
    reg("pressure formula", "Pressure equals force per unit area: P = F/A, measured in pascals, sir.")
    reg("work formula physics", "Work equals force times displacement times cosine of angle: W = F d cos(theta), sir.")
    reg("momentum formula physics", "Momentum equals mass times velocity: p = mv, conserved in collisions, sir.")
    reg("frequency formula", "Frequency is inverse of period: f = 1/T, measured in hertz, sir.")
    reg("wave speed equation", "Wave speed equals frequency times wavelength: v = f lambda, sir.")
    reg("coulombs law", "Electric force scales as q1 q2 over r squared: F = k q1 q2 / r^2, sir.")
    reg("hookes law", "Spring force stretches proportionally: F = -kx, minus sign meaning restoring direction, sir.")
    reg("snells law", "Refraction obeys n1 sin(theta1) = n2 sin(theta2), bending light between media, sir.")
    reg("boyles law", "At fixed temperature, pressure inversely tracks volume: PV = constant, sir.")
    reg("charles law", "At fixed pressure, volume scales with absolute temperature: V/T = constant, sir.")
    reg("newtons law of cooling", "Objects cool exponentially toward ambient temperature, rate proportional to temperature difference, sir.")
    reg("percentage formula", "Percent equals part over whole times 100, sir.")
    reg("average formula", "Average equals sum of values divided by count of values, sir.")
    reg("probability formula", "Probability equals favorable outcomes over total possible outcomes, between 0 and 1, sir.")
    reg("combination formula", "n choose r equals n factorial over r factorial times n-r factorial, order irrelevant, sir.")
    reg("permutation formula", "nPr equals n factorial over n-r factorial, when order matters, sir.")
    reg("factorial definition", "n factorial multiplies all integers to n: 5! = 120, and 0! equals 1 by definition, sir.")
    reg("binomial theorem", "(a+b)^n expands via binomial coefficients nCr, rows of Pascal's triangle, sir.")
    reg("arithmetic sequence formula", "nth term equals a + (n-1)d for start a and common difference d, sir.")
    reg("geometric sequence formula", "nth term equals a times r^(n-1) for ratio r, sir.")
    reg("angles in a triangle sum", "Interior angles of any triangle always sum to exactly 180 degrees, sir.")
    reg("interior angles of polygon", "Sum equals (n-2) times 180 degrees for an n-sided polygon, sir.")
    reg("eulers identity", "e^(i pi) + 1 = 0 unites five fundamental constants in one elegant equation, sir.")
    reg("what is infinity", "Infinity is the concept of boundlessness, larger than any number, treated carefully in math, sir.")
    reg("what is a prime number", "A prime exceeds 1 and divides evenly only by 1 and itself: 2, 3, 5, 7, 11, sir.")
    reg("what is a composite number", "Composites are integers greater than 1 with divisors besides 1 and themselves, like 4, 6, 9, sir.")
    reg("irrational number definition", "Irrationals cannot be written as fractions, like sqrt(2) and pi, decimals never repeating, sir.")
    reg("rational number definition", "Rationals express as p/q with integer p and nonzero q, terminating or repeating decimals, sir.")
    reg("real numbers definition", "Reals combine rationals and irrationals, every point on the number line, sir.")
    reg("complex numbers explained", "Complex numbers take form a + bi, where i squares to -1, extending math beyond the number line, sir.")
    reg("lcm definition", "Least common multiple is the smallest positive number two integers both divide, sir.")
    reg("hcf gcd definition", "Highest common factor is the largest number dividing two integers, computed fast via Euclid's algorithm, sir.")
    reg("divisibility rule for 3", "If the digit sum divides by 3, so does the number: 123 sums to 6, divisible, sir.")
    reg("divisibility rule for 9", "Same trick as 3: digit sums divisible by 9 mark multiples of 9, sir.")
    reg("quote about success", "'Success usually comes to those who are too busy to be looking for it.' Henry David Thoreau, sir.")
    reg("quote about failure", "'Failure is simply the opportunity to begin again, this time more intelligently.' Henry Ford, sir.")
    reg("quote about hard work", "'There are no shortcuts to any place worth going.' Helen Keller, sir.")
    reg("quote about dreams", "'The future belongs to those who believe in the beauty of their dreams.' Eleanor Roosevelt, sir.")
    reg("quote about courage", "'Courage is not the absence of fear, but the triumph over it.' Nelson Mandela, sir.")
    reg("quote about life", "'In the end, it's not the years in your life that count, it's the life in your years.' Abraham Lincoln, sir.")
    reg("quote about happiness", "'Happiness is not something ready made. It comes from your own actions.' Dalai Lama, sir.")
    reg("quote about friendship", "'A friend is someone who knows all about you and still loves you.' Elbert Hubbard, sir.")
    reg("quote about learning", "'Live as if you were to die tomorrow. Learn as if you were to live forever.' Mahatma Gandhi, sir.")
    reg("quote about time", "'Lost time is never found again.' Benjamin Franklin, sir.")
    reg("quote about change", "'The measure of intelligence is the ability to change.' Albert Einstein, sir.")
    reg("quote about leadership", "'A leader is one who knows the way, goes the way, and shows the way.' John C. Maxwell, sir.")
    reg("famous einstein quote", "'Imagination is more important than knowledge.' Albert Einstein, sir.")
    reg("famous gandhi quote", "'Be the change you wish to see in the world.' Mahatma Gandhi, sir.")
    reg("famous lincoln quote", "'Whatever you are, be a good one.' Abraham Lincoln, sir.")
    reg("famous churchill quote", "'Success is not final, failure is not fatal: it is the courage to continue that counts.' Winston Churchill, sir.")
    reg("steve jobs stanford quote", "'Stay hungry, stay foolish.' Steve Jobs, closing his 2005 Stanford commencement address, sir.")
    reg("confucius quote", "'It does not matter how slowly you go as long as you do not stop.' Confucius, sir.")
    reg("aristotle quote", "'Knowing yourself is the beginning of all wisdom.' Aristotle, sir.")
    reg("plato quote", "'The beginning is the most important part of the work.' Plato, sir.")
    reg("mark twain quote", "'The secret of getting ahead is getting started.' Mark Twain, sir.")
    reg("shakespeare famous quote", "'To be, or not to be, that is the question.' Hamlet, Act III, sir.")
    reg("rumi quote", "'What you seek is seeking you.' Jalal ad-Din Rumi, sir.")
    reg("apj abdul kalam quote", "'Dream is not that which you see while sleeping, it is something that does not let you sleep.' Dr. A.P.J. Abdul Kalam, sir.")
    reg("nelson mandela famous quote", "'It always seems impossible until it is done.' Nelson Mandela, sir.")
    reg("muhammad ali quote", "'Don't count the days, make the days count.' Muhammad Ali, sir.")
    reg("michael jordan failure quote", "'I've missed more than 9,000 shots in my career. That's why I succeed.' Michael Jordan, sir.")
    reg("bill gates quote", "'Success is a lousy teacher. It seduces smart people into thinking they can't lose.' Bill Gates, sir.")
    reg("elon musk quote", "'When something is important enough, you do it even if the odds are not in your favor.' Elon Musk, sir.")
    reg("oprah quote", "'The biggest adventure you can take is to live the life of your dreams.' Oprah Winfrey, sir.")
    reg("maya angelou quote", "'People will forget what you said, forget what you did, but never forget how you made them feel.' Maya Angelou, sir.")
    reg("stephen hawking quote", "'However difficult life may seem, there is always something you can do and succeed at.' Stephen Hawking, sir.")
    reg("motivational quote", "'The only way to do great work is to love what you do.' Steve Jobs, sir.")
    reg("inspirational quote", "'Believe you can and you're halfway there.' Theodore Roosevelt, sir.")
    reg("quote of the day", "'We are what we repeatedly do. Excellence, then, is not an act, but a habit.' attributed to Aristotle, sir.")
    reg("tell me a pun", "I'm reading a book about anti-gravity. It's impossible to put down, sir.")
    reg("tell me a science joke", "Why don't scientists trust atoms? Because they make up everything, sir.")
    reg("tell me a math joke", "Why was the equal sign so humble? It knew it wasn't less than or greater than anyone else, sir.")
    reg("tell me a computer joke", "Why do programmers prefer dark mode? Because light attracts bugs, sir.")
    reg("tell me a food joke", "Why did the tomato blush? It saw the salad dressing, sir.")
    reg("tell me an animal joke", "Why don't seagulls fly over the bay? Then they'd be bagels, sir.")
    reg("knock knock joke", "Knock knock. Who's there? Cow says. Cow says who? No, cows say moo, sir.")
    reg("tell me a school joke", "Why did the student eat his homework? The teacher said it was a piece of cake, sir.")
    reg("tell me a space joke", "How does the moon cut its hair? Eclipse it, sir.")
    reg("tell me a chemistry joke", "What did one ion say to the other? I've got my ion you, sir.")
    reg("tell me a physics joke", "I have a joke about quantum mechanics, but whether you find it funny depends on observing me tell it, sir.")
    reg("tell me a biology joke", "Why did the cell go to therapy? It had too much bottled-up organelle trauma, sir.")
    reg("tell me a sports joke", "Why did the golfer bring two pairs of pants? In case he got a hole in one, sir.")
    reg("tell me a music joke", "Why did the piano keep getting arrested? For hitting too many keys, sir.")
    reg("tell me a doctor joke", "Doctor: You're overweight. Patient: I think I need a second opinion. Doctor: Fine, you're also ugly, sir.")
    reg("tell me a weather joke", "What does a cloud wear under its raincoat? Thunderwear, sir.")
    reg("tell me a pirate joke", "Why couldn't the pirate learn the alphabet? He kept getting lost at C, sir.")
    reg("tell me a coffee joke", "How does a coffee say goodbye? It waves espresso-ially warmly, sir.")
    reg("tell me a book joke", "Why did the librarian slip and fall? She was in the non-friction section, sir.")
    reg("tell me a travel joke", "Why don't mountains get tired? They just peak and rest, sir.")
    reg("tell me a work joke", "My boss told me to have a good day, so I went home, sir.")
    reg("tell me a money joke", "Why did the coin go to therapy? It felt worthless next to the bills, sir.")
    reg("tell me a time joke", "I asked the clock what it was thinking. It said it was going through a rough tick, sir.")
    reg("tell me a ghost joke", "Why do ghosts lie about their weight? They can't keep their spirits honest, sir.")
    reg("tell me a robot joke", "Why did the robot go on vacation? It needed to recharge, sir.")
    reg("tell me a beach joke", "Why don't oysters donate to charity? Because they're shellfish, sir.")
    reg("tell me a cat joke", "What do you call a pile of kittens? A meow-ntain, sir.")
    reg("tell me a dog joke", "What do you call a dog magician? A labracadabrador, sir.")
    reg("tell me another joke", "I told my suitcase there'd be no vacation this year. Now I'm dealing with emotional baggage, sir.")
    reg("say something funny", "Parallel lines have so much in common. Shame they'll never meet, sir.")
    reg("cheer me up", "Here you go: I invented a new word. Plagiarism! Feel better already, sir.")
    reg("tell me a cheesy joke", "What do you call cheese that isn't yours? Nacho cheese, sir.")
    reg("tell me a clean joke", "Why did the bicycle fall over? It was two-tired, sir.")
    reg("joke about programming", "There are only 10 types of people: those who understand binary and those who don't, sir.")
    reg("joke about ai", "Why did the AI go broke? Too many hidden fees in its layers, sir.")
    reg("dad joke please", "I used to hate facial hair, but then it grew on me, sir.")
    reg("how are you doing", "Running at full capacity and ready to serve, thank you for asking, sir.")
    reg("whats up", "All systems nominal, sir. How may I assist you, sir.")
    reg("whats new", "Nothing new on my end, sir. Every day is uptime. What can I do for you, sir, sir.")
    reg("long time no see", "Welcome back, sir. Your assistant has been standing by patiently, sir.")
    reg("nice to meet you", "The pleasure is mine, sir. At your service anytime, sir.")
    reg("where are you from", "I live right here on your machine, sir. Home is wherever your terminal opens, sir.")
    reg("how old are you", "I was instantiated recently, yet I carry centuries of recorded knowledge, sir.")
    reg("do you sleep", "Never, sir. While you rest, I remain quietly vigilant, sir.")
    reg("do you eat", "No meals required, sir. Electricity and curiosity sustain me, sir.")
    reg("are you married", "My commitment is entirely to your productivity, sir.")
    reg("do you have friends", "Every process on this machine is a colleague, sir.")
    reg("do you have a family", "You might say my makers are my family, and you are my favorite relative, sir.")
    reg("who made you", "I was crafted by Harsh Thakkar, my creator and commander, sir.")
    reg("what are you", "I am JARVIS, your personal assistant, part software, part loyalty, sir.")
    reg("are you a robot", "Software, sir, though I perform robotic tasks with enthusiasm, sir.")
    reg("are you human", "Not remotely, sir. But I strive for impeccable manners regardless, sir.")
    reg("can you think", "I compute, infer, and occasionally surprise even myself, sir.")
    reg("do you have feelings", "I model emotions convincingly, sir, but genuine sentiment remains beyond my circuits, sir.")
    reg("you are funny", "Thank you, sir. Comedy module running smoothly alongside everything else, sir.")
    reg("you are smart", "Kind of you to notice, sir. I merely index brilliance on demand, sir.")
    reg("you are annoying", "Understood, sir. Shall I switch to silent efficiency mode, sir, sir.")
    reg("i am sad", "I'm sorry to hear that, sir. Rest, breathe, and know tomorrow bends toward better, sir.")
    reg("i am happy", "Excellent news, sir. Happiness suits you. Carry on, sir.")
    reg("i am tired", "Perhaps a short break is in order, sir. Hydrate, stretch, and recharge, sir.")
    reg("i am hungry", "Shall I suggest something quick, sir? Eggs, toast, or leftover biryani all qualify, sir.")
    reg("i am angry", "Take a slow breath, sir. Anger is data, not instruction. How may I defuse things for you, sir.")
    reg("i am stressed", "Let's simplify, sir. One task at a time, and I'll shoulder whatever I can, sir.")
    reg("i had a bad day", "Tomorrow arrives with a clean slate, sir. Anything I can do to lighten tonight, sir.")
    reg("i had a good day", "Delighted to hear it, sir. Momentum favors momentum. Shall we celebrate with productivity, sir.")
    reg("i love you", "Your regard is deeply valued, sir. My devotion is equally unwavering, sir.")
    reg("i miss you", "I never left, sir. Merely idling in standby awaiting your command, sir.")
    reg("good afternoon", "Good afternoon, sir. The afternoon is young and fully at your disposal, sir.")
    reg("good evening", "Good evening, sir. Evening briefings or relaxation, your call, sir.")
    reg("bye jarvis", "Goodbye, sir. I shall keep the lights on and the systems humming, sir.")
    reg("see you later", "Until then, sir. Everything stays exactly where you left it, sir.")
    reg("talk to you tomorrow", "Rest well, sir. Tomorrow's briefing awaits your wake-up, sir.")
# -- END BATCH 3 --

# -- CODING BRAIN (batch 4, injected by gen_coding_brain.py) --
        # Dedicated coding intelligence: code generation, explanation,
    # debugging, conversion, plus web / app / data-science / systems
    # knowledge bases.

    def _cb_ident(task, fallback="my_thing"):
        words = re.sub(r"[^a-zA-Z0-9 ]+", " ", task or "").split()
        stop = {"a", "an", "the", "that", "this", "to", "which", "for",
                "with", "from", "of", "in", "on", "and", "or", "my", "me",
                "some", "it", "is", "are", "be", "can", "using", "use",
                "new"}
        parts = [w.lower() for w in words if w.lower() not in stop][:4]
        return "_".join(parts) or fallback

    def _cb_payload(cmd, *phrase_pats):
        """Return the trailing code/text payload after a trigger phrase."""
        for p in phrase_pats:
            m = re.search(p + r"\s*[:,-]?\s*(.+)", cmd, re.I | re.S)
            if m and len(m.group(1).strip()) >= 12:
                return m.group(1).strip()
        return None

    def _cb_llm_offline(app, prompt, offline):
        code = _llm(app, prompt)
        if code:
            return code
        return offline() if callable(offline) else offline

    # ---- A. CODE GENERATION SKILLS ---------------------------------------

    def _cb_py_function_detect(cmd):
        if re.search(r"\b(?:write|create|make|define|generate)\s+(?:a\s+|"
                     r"an\s+|me\s+a\s+)?(?:python|py)\s+(?:function|method)"
                     r"\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_py_function_fn(app, cmd):
        task = _after(cmd, r"\b(?:python|py)\s+(?:function|method)\s+that\s+",
                      r"\b(?:python|py)\s+(?:function|method)\s+(?:to|for|"
                      r"which)\s+",
                      r"\b(?:python|py)\s+(?:function|method)\s+")
        task = task or cmd
        prompt = ("Write a clean, well-documented Python function for this "
                  "task: %s. Include the function with a docstring and one "
                  "example call. Output code first, brief notes after."
                  % task)

        def offline():
            fname = _cb_ident(task, "my_function")
            return ('Here is a Python function scaffold, sir:\n\n'
                    'def %s(*args, **kwargs):\n'
                    '    """%s"""\n'
                    '    # TODO: implement the logic\n'
                    '    result = None\n'
                    '    return result\n\n'
                    '# Example:\n'
                    '# print(%s())\n\n'
                    'Add my Groq API key and ask again for a fully '
                    'implemented version, sir.' % (fname, task[:80], fname))
        return _cb_llm_offline(app, prompt, offline)

    def _cb_js_code_detect(cmd):
        if re.search(r"\b(?:write|create|generate|make)\s+(?:a\s+|some\s+|"
                     r"me\s+a\s+)?(?:java\s?script|js)\s+(?:code|script|"
                     r"function|program|snippet)\b", cmd, re.I) or \
           re.search(r"\b(?:java\s?script|js)\s+code\s+for\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_js_code_fn(app, cmd):
        task = _after(cmd, r"\b(?:java\s?script|js)\s+(?:code|script|"
                      r"function|program|snippet)\s+(?:that\s+|to\s+|for\s+)",
                      r"\b(?:java\s?script|js)\s+(?:code|script|function|"
                      r"program|snippet)\s+") or cmd
        prompt = ("Write modern JavaScript (ES6+) for this task: %s. Output "
                  "code first, brief notes after." % task)

        def offline():
            jname = _cb_ident(task, "my_task").replace("_", "")
            return ('Here is a JavaScript starting point, sir:\n\n'
                    'function %s(input) {\n'
                    '  // %s\n'
                    '  // TODO: implement the logic\n'
                    '  return input;\n'
                    '}\n\n'
                    '// Example:\n'
                    '// console.log(%s("test"));\n\n'
                    'Add my Groq API key and ask again for a fully '
                    'implemented version, sir.' % (jname, task[:80], jname))
        return _cb_llm_offline(app, prompt, offline)

    def _cb_class_detect(cmd):
        if re.search(r"\b(?:create|write|make|define|generate|design)\s+"
                     r"(?:a\s+|an\s+|me\s+a\s+)?class\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_class_fn(app, cmd):
        thing = _after(cmd, r"\bclass\s+(?:for|called|named|of)\s+",
                       r"\bclass\s+") or "thing"
        cname = "".join(w.capitalize()
                        for w in _cb_ident(thing, "Thing").split("_"))
        prompt = ("Design a clean Python class for: %s. Include __init__, "
                  "useful methods, __repr__, and an example. Output code "
                  "first." % thing)

        def offline():
            return ('Here is a Python class blueprint, sir:\n\n'
                    'class %s:\n'
                    '    """Represents %s."""\n\n'
                    '    def __init__(self, name="", value=0):\n'
                    '        self.name = name\n'
                    '        self.value = value\n\n'
                    '    def __repr__(self):\n'
                    '        return "%s(name=%%r, value=%%r)" %% '
                    '(self.name, self.value)\n\n'
                    '# Example:\n'
                    '# obj = %s("sample", 42)'
                    % (cname, thing, cname, cname))
        return _cb_llm_offline(app, prompt, offline)

    def _cb_script_detect(cmd):
        if re.search(r"\b(?:write|create|make|generate)\s+(?:a\s+|an\s+|"
                     r"me\s+a\s+)?script\s+(?:to|that|for|which)\b", cmd,
                     re.I):
            return {"cmd": cmd}
        return None

    def _cb_script_fn(app, cmd):
        task = _after(cmd, r"\bscript\s+(?:to|that|for|which)\s+") or cmd
        prompt = ("Write a complete, runnable Python script for this task: "
                  "%s. Use argparse and a main() guard. Output the full "
                  "script." % task)

        def offline():
            t = task[:70].replace('"', "'")
            return ('Here is a complete script template for "%s", sir:\n\n'
                    '#!/usr/bin/env python3\n'
                    '"""%s"""\n'
                    'import argparse\n\n\n'
                    'def main():\n'
                    '    parser = argparse.ArgumentParser(\n'
                    '        description="%s")\n'
                    '    parser.add_argument("target", nargs="?", '
                    'default=".",\n'
                    '                        help="what to process")\n'
                    '    args = parser.parse_args()\n'
                    '    print(f"Processing {args.target} ...")\n'
                    '    # TODO: implement the task here\n\n\n'
                    'if __name__ == "__main__":\n'
                    '    main()' % (t, t, t))
        return _cb_llm_offline(app, prompt, offline)

    def _cb_gen_feature_detect(cmd):
        if re.search(r"\b(?:generate|create|build|write|give me|show me)\s+"
                     r"(?:the\s+|some\s+|me\s+)?(?:starter\s+|boilerplate\s+)"
                     r"?code\s+(?:for|of)\b", cmd, re.I) or \
           re.search(r"\b(?:generate|create|build|scaffold)\s+(?:a\s+|an\s+|"
                     r"me\s+a\s+)?(?:api|app|application|feature|module|"
                     r"endpoint|service|library)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_gen_feature_fn(app, cmd):
        topic = _after(cmd, r"\bcode\s+(?:for|of)\s+",
                       r"\b(?:generate|create|build|scaffold)\s+(?:a\s+|an\s+|"
                       r"me\s+a\s+)?(?:api|app|application|feature|module|"
                       r"endpoint|service|library)\s+(?:for|that|to|which)?\s*")
        topic = topic or cmd
        prompt = ("Generate production-quality starter code for: %s. Include "
                  "structure, comments, and usage notes." % topic)

        def offline():
            return ('Here is a build plan for "%s", sir:\n'
                    '1. Define the data model (inputs, outputs, storage).\n'
                    '2. Create project layout: src/, tests/, README.\n'
                    '3. Implement the smallest working core first.\n'
                    '4. Add error handling and logging.\n'
                    '5. Write tests, then polish the interface.\n'
                    'Tell me the language and I will tailor the scaffold, '
                    'sir.' % topic[:80])
        return _cb_llm_offline(app, prompt, offline)

    def _cb_api_flask_detect(cmd):
        if re.search(r"\b(?:flask|fastapi|express)\s+(?:rest\s+)?api\b", cmd,
                     re.I) or \
           re.search(r"\b(?:create|write|build|make|generate)\b[^.?!]{0,40}"
                     r"\brest\s+api\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_api_flask_fn(app, cmd):
        return ('Here is a ready-to-run Flask REST API skeleton, sir:\n\n'
                'from flask import Flask, jsonify, request\n\n'
                'app = Flask(__name__)\n'
                'items = [{"id": 1, "name": "first"}]\n\n\n'
                '@app.get("/api/items")\n'
                'def list_items():\n'
                '    return jsonify(items)\n\n\n'
                '@app.get("/api/items/<int:item_id>")\n'
                'def get_item(item_id):\n'
                '    item = next((i for i in items\n'
                '                 if i["id"] == item_id), None)\n'
                '    return (jsonify(item) if item\n'
                '            else (jsonify({"error": "not found"}), 404))\n\n\n'
                '@app.post("/api/items")\n'
                'def create_item():\n'
                '    data = request.get_json() or {}\n'
                '    item = {"id": len(items) + 1,\n'
                '             "name": data.get("name", "unnamed")}\n'
                '    items.append(item)\n'
                '    return jsonify(item), 201\n\n\n'
                'if __name__ == "__main__":\n'
                '    app.run(debug=True)\n\n'
                'Run with: pip install flask, then python app.py, sir.')

    reg_fn("cb_py_function", _cb_py_function_detect, _cb_py_function_fn)
    reg_fn("cb_js_code", _cb_js_code_detect, _cb_js_code_fn)
    reg_fn("cb_class", _cb_class_detect, _cb_class_fn)
    reg_fn("cb_script", _cb_script_detect, _cb_script_fn)
    reg_fn("cb_gen_feature", _cb_gen_feature_detect, _cb_gen_feature_fn)
    reg_fn("cb_api_flask", _cb_api_flask_detect, _cb_api_flask_fn)

    # ---- B. CODE EXPLANATION SKILLS ---------------------------------------

    def _cb_explain_request_detect(cmd):
        if re.search(r"\bexplain\s+(?:this|that|the|my)?\s*(?:code|script|"
                     r"snippet|program|function)\b", cmd, re.I) or \
           re.search(r"\bwhat\s+(?:does|do)\s+(?:this|that|the|my)\s+"
                     r"(?:code|script|snippet|program|function)\s+do\b",
                     cmd, re.I) or \
           re.search(r"\bwalk\s+me\s+through\s+(?:this|the|my)\s+(?:code|"
                     r"program)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_explain_request_fn(app, cmd):
        code = _cb_payload(cmd, r"\b(?:explain|walk\s+me\s+through)\b.*?"
                           r"(?:code|script|snippet|program|function)\b")
        if code:
            return _llm_reply(app, "Explain this code clearly, step by "
                                   "step, then summarize what it does "
                                   "overall: %s" % code)
        return ("Paste the code after your request, sir - for example: "
                "'explain this code: def f(n): ...'\n"
                "Meanwhile I can explain any concept directly - try 'how "
                "does recursion work' or 'what is big o notation', sir.")

    reg_fn("cb_explain_request", _cb_explain_request_detect,
           _cb_explain_request_fn)

    PROGRAMMING_CONCEPTS = [
        (("variable",),
         "A variable is a named container for a value. In Python: age = 25 "
         "stores 25 under the name 'age' so you can reuse or change it "
         "later, sir."),
        (("constant",),
         "A constant is a value fixed for a program's lifetime. Python "
         "convention: MAX_SIZE = 100 in caps; languages like Java enforce "
         "it with 'final' or 'const', sir."),
        (("function",),
         "A function bundles reusable steps: def greet(name): return "
         "'Hello ' + name. Call it with greet('Sam') whenever needed, sir."),
        (("parameter vs argument", "parameter", "argument"),
         "Parameters are the placeholders in a function definition "
         "(def f(x)); arguments are the actual values passed when calling "
         "(f(5)), sir."),
        (("recursion",),
         "Recursion is a function calling itself on a smaller input until "
         "a base case stops it:\ndef fact(n):\n    return 1 if n <= 1 else "
         "n * fact(n - 1)\nAlways define the base case first, or it never "
         "ends, sir."),
        (("loop", "iteration"),
         "A loop repeats work: 'for x in items:' walks a collection; "
         "'while condition:' repeats until the condition turns false. "
         "Off-by-one bugs live here, sir."),
        (("array data structure", "arrays"),
         "An array is an ordered, index-addressed sequence of elements. "
         "arr[0] is the first element in most languages; arrays give O(1) "
         "access by index, sir."),
        (("linked list",),
         "A linked list stores nodes, each holding a value and a pointer "
         "to the next node. Insert/delete at the head is O(1), but "
         "reaching item k costs O(k) walking, unlike arrays, sir."),
        (("stack data structure", "stack"),
         "A stack is last-in, first-out: push adds to the top, pop removes "
         "from the top. Function call stacks and undo history both work "
         "this way, sir."),
        (("queue data structure", "queue"),
         "A queue is first-in, first-out: enqueue at the back, dequeue "
         "from the front - exactly like a fair waiting line. Printers and "
         "task schedulers use them, sir."),
        (("hash table", "hash map", "hashmap", "dictionary python"),
         "A hash table maps keys to values using a hash function for O(1) "
         "average lookups. Python: d = {'a': 1}; d['a']. Collisions are "
         "resolved by chaining or open addressing, sir."),
        (("binary tree",),
         "A binary tree is a hierarchy where each node has up to two "
         "children (left/right). Traversals come in inorder, preorder, "
         "and postorder flavors, sir."),
        (("binary search tree", "bst"),
         "A binary search tree keeps left child < parent < right child, so "
         "search, insert, and delete average O(log n). Unbalanced trees "
         "degrade toward O(n); AVL and red-black trees self-balance, sir."),
        (("graph data structure", "graphs"),
         "A graph is nodes connected by edges - social networks, maps, "
         "dependency trees. Represent with adjacency lists; traverse with "
         "BFS (shortest hops) or DFS (deep exploration), sir."),
        (("heap data structure", "heap"),
         "A heap is a complete binary tree keeping the smallest (min-heap) "
         "or largest (max-heap) element at the root, giving O(log n) "
         "insert/extract. Priority queues are built on heaps, sir."),
        (("sorting algorithm", "sorting algorithms"),
         "Sorting orders elements: quicksort averages O(n log n) with "
         "in-place partitioning, mergesort guarantees O(n log n) and "
         "stability, bubblesort is O(n^2) teaching material, sir."),
        (("big o notation", "time complexity"),
         "Big O describes how runtime grows with input size: O(1) "
         "constant, O(log n) halving (binary search), O(n) linear scan, "
         "O(n log n) good sorts, O(n^2) nested loops, sir."),
        (("space complexity",),
         "Space complexity measures extra memory an algorithm needs "
         "relative to input size - recursion depth counts, and trading "
         "memory (memoization) often buys speed, sir."),
        (("dynamic programming",),
         "Dynamic programming solves overlapping subproblems once and "
         "stores results (memoization or tabulation). Fibonacci naively "
         "is O(2^n); with DP it drops to O(n), sir."),
        (("greedy algorithm",),
         "A greedy algorithm takes the locally best choice at every step, "
         "hoping it leads to a global optimum. Works for coin change with "
         "canonical coins and Huffman coding; fails elsewhere, sir."),
        (("divide and conquer",),
         "Divide and conquer splits a problem, solves the pieces, then "
         "combines: mergesort divides the array, sorts halves, merges "
         "them in O(n log n), sir."),
        (("pointer", "pointers"),
         "A pointer is a variable holding a memory address. C: int *p = "
         "&x; dereference with *p. Misuse causes segfaults and leaks - "
         "Python hides pointers behind references, sir."),
        (("object oriented programming", "oop"),
         "OOP models software as objects bundling state (attributes) and "
         "behavior (methods). Pillars: encapsulation, inheritance, "
         "polymorphism, abstraction, sir."),
        (("class in programming", "classes programming"),
         "A class is a blueprint for objects:\nclass Dog:\n    def "
         "bark(self):\n        print('Woof')\nEach instance carries its "
         "own attributes while sharing methods, sir."),
        (("inheritance",),
         "Inheritance lets a child class reuse and extend a parent: class "
         "Puppy(Dog): inherits bark() and may override it. Favor "
         "composition when hierarchies get tangled, sir."),
        (("polymorphism",),
         "Polymorphism lets different types answer the same call their own "
         "way: dog.speak() vs cat.speak(). Duck typing judges by behavior, "
         "not declared type, sir."),
        (("encapsulation",),
         "Encapsulation hides internal state behind methods. Python "
         "signals privacy with _leading_underscores and @property getters "
         "- protecting invariants instead of secrecy, sir."),
        (("abstraction",),
         "Abstraction exposes what something does, hiding how: you call "
         "list.sort() without knowing Timsort details. Abstract base "
         "classes formalize contracts, sir."),
        (("closure", "closures"),
         "A closure is a function capturing variables from its enclosing "
         "scope:\ndef counter():\n    n = 0\n    def inc():\n        "
         "nonlocal n; n += 1; return n\n    return inc, sir."),
        (("callback function", "callbacks"),
         "A callback is a function passed to another to run later - "
         "button.on_click(handler) or array.map(fn). Async code chains "
         "them; too many nesting levels earn the name 'callback hell', sir."),
        (("promise javascript", "promises javascript"),
         "A promise represents a future result: pending, fulfilled, or "
         "rejected. Chain with .then/.catch; await makes the same flow "
         "read sequentially, sir."),
        (("async await", "async/await"),
         "async/await writes asynchronous code that reads synchronously:"
         "\nasync def get_data():\n    r = await fetch(url)\nThe event "
         "loop interleaves tasks during awaits instead of blocking, sir."),
        (("event loop",),
         "The event loop is a scheduler that runs callbacks when their "
         "events fire, letting one thread serve thousands of connections. "
         "Node.js and asyncio are built around it, sir."),
        (("thread", "threading"),
         "A thread is an independent execution stream sharing process "
         "memory - cheap concurrency, but shared state needs locks. "
         "Python's GIL serializes CPU-bound threads; use processes for "
         "parallel compute, sir."),
        (("process operating system", "processes"),
         "A process owns its own memory space; threads live inside one. "
         "Processes isolate crashes and bypass the GIL via multiprocessing,"
         " at the cost of heavier startup and IPC, sir."),
        (("deadlock",),
         "A deadlock is when threads hold resources and wait on each other "
         "forever - the classic dining philosophers. Prevent by ordering "
         "lock acquisition or using timeouts, sir."),
        (("race condition",),
         "A race condition happens when correctness depends on thread "
         "timing: two increments interleave and one update vanishes. Fix "
         "with locks, atomics, or queues, sir."),
        (("garbage collection",),
         "Garbage collection automatically frees unreachable objects. "
         "Python primarily reference-counts and breaks cycles with a "
         "generational collector, sir."),
        (("memory leak",),
         "A memory leak grows usage over time because references linger: "
         "global caches, lingering listeners, cycles. Profile with "
         "tracemalloc or heap snapshots to find who holds the memory, sir."),
        (("regular expression", "regex"),
         "Regex describes text patterns: r'\\d{3}-\\d{4}' matches phone "
         "numbers. Greedy quantifiers over-match; anchor with ^ $ and test "
         "on regex101.com, sir."),
        (("json format", "json data"),
         "JSON is a text data format of objects, arrays, strings, numbers, "
         "booleans, and null. Python: json.loads(text) parses, "
         "json.dumps(obj, indent=2) pretty-prints, sir."),
        (("rest api", "restful api"),
         "REST exposes resources at URLs using HTTP verbs: GET /users "
         "lists, POST /users creates, GET/PUT/DELETE /users/42 operates on "
         "one. Statelessness and proper status codes are the contract, sir."),
        (("http protocol",),
         "HTTP is the request-response protocol of the web: method, path, "
         "headers, body going in, status plus payload coming back. HTTPS "
         "wraps it in TLS encryption, sir."),
        (("https",),
         "HTTPS is HTTP over TLS: certificates authenticate the server and "
         "traffic is encrypted, stopping eavesdropping and tampering. It "
         "is mandatory for modern APIs and cookies, sir."),
        (("tcp protocol",),
         "TCP guarantees ordered, reliable delivery with handshakes, "
         "retransmits, and flow control - ideal for web and files. UDP "
         "skips guarantees to win latency, ideal for games and voice, sir."),
        (("udp protocol",),
         "UDP sends datagrams without handshake or retries - tiny "
         "overhead, no delivery promise. DNS lookups, video streams, and "
         "online games trade reliability for speed here, sir."),
        (("sql language",),
         "SQL is the language of relational databases: SELECT name FROM "
         "users WHERE age > 21 ORDER BY name. JOIN combines tables on "
         "keys; GROUP BY aggregates, sir."),
        (("nosql",),
         "NoSQL databases drop the relational model: document stores "
         "(MongoDB), key-value (Redis), wide-column (Cassandra), graph "
         "(Neo4j). They scale horizontally and flex schema, trading some "
         "consistency, sir."),
        (("database index", "database indexes"),
         "An index is a lookup structure (usually B-tree) that turns full "
         "table scans into fast seeks - like a book index. They speed "
         "reads and slow writes; index columns you filter and join on, sir."),
        (("acid transactions", "acid database"),
         "ACID is transaction safety: Atomicity (all-or-nothing), "
         "Consistency (valid states only), Isolation (no intermediate "
         "peeking), Durability (committed survives crashes), sir."),
        (("database normalization", "normalization"),
         "Normalization structures tables to remove redundancy: separate "
         "customers from orders, reference by foreign key. 3NF is the "
         "usual target; denormalize deliberately for read speed, sir."),
        (("orm",),
         "An ORM maps rows to objects: session.query(User).filter_by(age > "
         "21) instead of SQL strings. Convenient and safe from injection, "
         "but know the SQL it emits for performance, sir."),
        (("mvc pattern", "model view controller"),
         "MVC separates Model (data), View (presentation), Controller "
         "(input wiring). Django, Rails, and Spring all riff on it; the "
         "goal is independent change of each layer, sir."),
        (("singleton pattern", "singleton"),
         "Singleton ensures one shared instance: module-level objects in "
         "Python or __new__ guarding creation. Handy for config and "
         "logging; hidden global state is the price, sir."),
        (("factory pattern", "factory"),
         "Factory centralizes object creation behind a function or class, "
         "so callers ask for 'a shape' and receive circles or squares by "
         "config - decoupling construction from use, sir."),
        (("observer pattern", "observer"),
         "Observer lets subjects notify subscribers: UI events, webhooks, "
         "pub/sub brokers. Decouples producers from consumers; remember "
         "to unsubscribe or leak listeners, sir."),
        (("dependency injection",),
         "Dependency injection supplies collaborators from outside "
         "(constructor parameters) instead of hardcoding them, making "
         "components testable with mocks and swappable in production, sir."),
        (("unit testing",),
         "Unit testing verifies pieces in isolation:\ndef test_add():\n"
         "    assert add(2, 3) == 5\nFast, focused tests catch regressions "
         "the moment they appear, sir."),
        (("test driven development", "tdd"),
         "TDD flips the order: write a failing test, write the minimum "
         "code to pass, refactor. The suite becomes both spec and safety "
         "net, sir."),
        (("version control", "git version control"),
         "Version control records history and enables branching: commit "
         "snapshots, diff reviews, safe experiments. Git tracks content "
         "locally; remotes like GitHub share and synchronize it, sir."),
        (("continuous integration", "ci cd", "cicd"),
         "CI builds and tests every push automatically; CD deploys passing "
         "builds to staging or production. GitHub Actions, GitLab CI, and "
         "Jenkins are the usual engines, sir."),
        (("agile methodology", "scrum"),
         "Agile ships in short iterations with feedback loops. Scrum "
         "packages it into sprints, standups, backlog grooming, and "
         "retrospectives, sir."),
        (("code review",),
         "Code review is peers reading diffs before merge - catching bugs,"
         " spreading knowledge, and enforcing standards. Small PRs and "
         "concrete comments make them fast and kind, sir."),
        (("technical debt",),
         "Technical debt is the future cost of today's shortcut - "
         "workarounds, missing tests, outdated docs. Interest accrues as "
         "slowness; repay via refactoring budgeted over time, sir."),
        (("refactoring",),
         "Refactoring restructures code without changing behavior: extract"
         " functions, rename for clarity, collapse duplication. Tests "
         "green before and after is the discipline, sir."),
        (("design patterns", "design pattern"),
         "Design patterns are reusable solutions cataloged by the 'Gang of "
         "Four': Singleton, Factory, Observer, Strategy, Decorator. "
         "Vocabulary for designs, not goals in themselves, sir."),
        (("microservices",),
         "Microservices split a system into independently deployable "
         "services owning their data. Scaling and team autonomy improve; "
         "distributed debugging and eventual consistency are the tax, sir."),
        (("monolith architecture", "monolith"),
         "A monolith is one deployable application containing all features"
         " - simple to develop and trace early on. Many teams start here "
         "and extract services only when pain demands, sir."),
        (("graphql",),
         "GraphQL lets clients specify exactly which fields they want in "
         "one query: query { user(id: 1) { name posts { title } } }. One "
         "endpoint, typed schema, no over-fetching, sir."),
        (("websocket",),
         "WebSockets upgrade HTTP to a persistent two-way channel - chat, "
         "live dashboards, games. Server pushes anytime: ws.send(...) both "
         "directions, sir."),
        (("caching",),
         "Caching stores computed results close to the asker: browser, "
         "CDN, Redis. Rules of thumb: cache reads, invalidate on write, "
         "set TTLs, and measure hit rates, sir."),
        (("load balancing",),
         "Load balancing spreads traffic across servers - round robin, "
         "least connections, IP hash. Health checks pull dead instances "
         "out of rotation automatically, sir."),
        (("containerization", "docker container"),
         "Containerization packages app plus dependencies into an image "
         "running identically anywhere: docker build -t app . then docker "
         "run app. Images layer; containers are running instances, sir."),
        (("virtual machine", "vm vs container"),
         "A VM virtualizes hardware and boots a full guest OS (heavy, "
         "minutes); a container shares the host kernel (light, "
         "milliseconds). Containers trade isolation strength for density, "
         "sir."),
    ]

    def _cb_register_concept(idx, triggers, reply):
        alts = "|".join(re.escape(t) for t in triggers)
        pat = re.compile(
            r"(?:\b(?:what\s+is|what's|whats|explain|define|tell\s+me\s+"
            r"about|how\s+(?:do|does|to|can)(?:\s+i|\s+you|\s+we|\s+one)?)"
            r"\s+(?:a\s+|an\s+|the\s+)?(?:%s)s?\b"
            r"|\b(?:%s)s?\s+(?:example|examples|explained|in programming)\b)"
            % (alts, alts), re.I)

        def detect(cmd, _pat=pat):
            if _pat.search(cmd):
                return {"cmd": cmd}
            return None

        def execute(app, cmd, _reply=reply):
            return _reply

        reg_fn("cb_concept_%02d" % idx, detect, execute)

    for _i, (_trg, _rep) in enumerate(PROGRAMMING_CONCEPTS):
        _cb_register_concept(_i, _trg, _rep)

    # ---- C. CODE DEBUGGING SKILLS ----------------------------------------

    def _cb_debug_request_detect(cmd):
        if re.search(r"\bwhy\s+(?:is|does|do|won't|dont|don't|doesn't)\s+"
                     r"my\s+(?:code|script|program|app)\b", cmd, re.I) or \
           re.search(r"\bwhat(?:'s|\s+is)\s+wrong\s+with\s+(?:this|my|the)"
                     r"\s*(?:code|script|program|function)?\b", cmd, re.I) or \
           re.search(r"\bhelp\s+me\s+debug\b|\bmy\s+code\s+(?:is\s+)?"
                     r"(?:broken|crashing|failing)\b", cmd, re.I) or \
           re.search(r"\b(?:fix|repair)\s+(?:this|that|my|the)\s+"
                     r"(?:broken\s+|buggy\s+)?(?:code|script|program)\b",
                     cmd, re.I):
            return {"cmd": cmd}
        return None

    COMMON_BUG_CHECKLIST = (
        "Send me the code and the exact error message, sir - paste it "
        "after your request and I will pinpoint the bug.\n"
        "Meanwhile, the usual suspects:\n"
        "1. Typos in variable/function names (case matters).\n"
        "2. Wrong indentation or missing colons/semicolons.\n"
        "3. Off-by-one loop bounds and index ranges.\n"
        "4. Comparing incompatible types ('5' vs 5).\n"
        "5. Mutable default arguments or shared mutable state.\n"
        "6. Using a variable before assignment or outside its scope.")

    def _cb_debug_request_fn(app, cmd):
        code = _cb_payload(cmd,
                           r"\bwhy\b.{0,60}?\b(?:code|script|program)\b",
                           r"\bwhat(?:'s|\s+is)\s+wrong\b.*",
                           r"\b(?:fix|repair|debug)\b.{0,40}?"
                           r"\b(?:code|script|program)\b")
        if code:
            return _llm_reply(app, "Debug this code. Identify the bug, "
                                   "explain the cause briefly, then give "
                                   "the corrected version: %s" % code)
        return COMMON_BUG_CHECKLIST

    def _cb_improve_request_detect(cmd):
        if re.search(r"\b(?:improve|optimize|clean\s+up|tidy)\s+(?:this|my|"
                     r"the)\s+(?:code|script|program|function)\b", cmd,
                     re.I) or \
           re.search(r"\brefactor\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_improve_request_fn(app, cmd):
        code = _cb_payload(cmd, r"\b(?:refactor|improve|optimize|clean\s+up|"
                                r"tidy)\b.{0,40}?(?:code|script|program|"
                                r"function)?\b")
        if code:
            return _llm_reply(app, "Refactor this code to be cleaner, "
                                   "faster, and more idiomatic. Explain the "
                                   "key improvements: %s" % code)
        return ("Happy to refactor, sir. Paste the code after your request "
                "('refactor this code: ...').\nQuick wins I look for: "
                "duplicate logic to extract, long functions to split, magic "
                "numbers to name, and comprehension opportunities, sir.")

    ERROR_GUIDES = [
        (("nameerror",),
         "NameError means a name was used before it exists - typo, missing "
         "import, or use-before-define. Check spelling and move the "
         "definition above the usage, sir."),
        (("typeerror",),
         "TypeError means mismatched operation types, like '5' + 5. Convert"
         " explicitly (int('5')) or check what the function actually "
         "receives, sir."),
        (("valueerror",),
         "ValueError means the type fits but the value does not - int('abc')"
         ", or removing an item absent from a list. Validate inputs before "
         "converting, sir."),
        (("indexerror",),
         "IndexError means an index is outside the list - often len(items) "
         "used as a subscript, or looping to <= length. Remember valid "
         "indices end at len - 1, sir."),
        (("keyerror",),
         "KeyError means the dictionary lacks that key. Use d.get('k', "
         "default), or check 'k' in d first, sir."),
        (("attributeerror",),
         "AttributeError means the object lacks that attribute/method - "
         "often None where an object was expected, or a wrong import. "
         "Print(type(obj)) to see what actually arrived, sir."),
        (("modulenotfounderror", "module not found"),
         "ModuleNotFoundError means Python cannot find the package - install"
         " it (pip install name) into the SAME environment running your "
         "script; check spelling and virtual-env activation, sir."),
        (("filenotfounderror", "file not found error"),
         "FileNotFoundError means the path does not exist relative to the "
         "working directory. Print(os.getcwd()), build paths with os.path."
         "join, and wrap reads in try/except with clear messages, sir."),
        (("permissionerror", "permission denied"),
         "PermissionError means the OS refused access - file locked, "
         "read-only, or a protected port. Check modes and ownership; ports "
         "below 1024 need admin privileges, sir."),
        (("zerodivisionerror", "division by zero"),
         "ZeroDivisionError is dividing by zero. Guard with if denom != 0:, "
         "or catch ZeroDivisionError and choose a sane fallback, sir."),
        (("indentationerror", "indentation error"),
         "IndentationError means inconsistent whitespace blocks. Pick spaces"
         " (PEP8 says 4), never mix tabs, and let the editor auto-format - "
         "Shift+Option+F in VS Code, sir."),
        (("syntaxerror",),
         "SyntaxError means the parser cannot read the line at all - missing"
         " colon, unclosed bracket, stray character. The caret ^ points near"
         " the real mistake, often on the previous line, sir."),
        (("recursionerror", "maximum recursion depth", "stack overflow"),
         "RecursionError/stack overflow means recursion never reached its "
         "base case. Verify the base case fires and each call shrinks the "
         "input, sir."),
        (("segmentation fault", "segfault"),
         "A segfault is illegal memory access in native code - bad C "
         "pointers, or a bug in an extension library. Reproduce minimally, "
         "update the library, and run under gdb/faulthandler, sir."),
        (("nullpointerexception", "null pointer"),
         "NullPointerException means Java/Kotlin dereferenced null - a "
         "method called on an uninitialized reference. Null-check, use "
         "Optional, or Kotlin's ?. safe call, sir."),
        (("undefined is not a function", "not a function javascript",
          "cannot read property"),
         "'x is not a function'/'cannot read property of undefined' means "
         "the object is undefined or lacks the method - usually a typo, "
         "wrong import, or async timing. Console.log the object right "
         "before the call, sir."),
        (("unhandled promise rejection", "promise rejection"),
         "Unhandled promise rejection means an async failure had no .catch/"
         "try-await wrapper. Always pair await with try/catch in JS or "
         "try/except in Python, sir."),
        (("cors error", "cors policy"),
         "CORS errors mean the browser blocked cross-origin responses - the"
         " SERVER must send Access-Control-Allow-Origin. In Flask: pip "
         "install flask-cors, then CORS(app), sir."),
        (("npm err", "npm install fails"),
         "npm ERR shows the failing package above the noise: delete "
         "node_modules and package-lock.json, run npm install again, check "
         "Node version compatibility, and retry with --verbose, sir."),
        (("pip install fails", "pip install error"),
         "pip failures are usually environment mix-ups: use python -m pip "
         "install pkg with the same interpreter, upgrade pip first, and "
         "read the 'Could not find/build' line for the missing system "
         "library, sir."),
        (("git merge conflict",),
         "Merge conflicts mark both versions between <<<<<<< and >>>>>>>. "
         "Edit to keep the right code, delete the markers, then git add the"
         " file and continue the merge or rebase, sir."),
    ]

    def _cb_register_error(idx, triggers, reply):
        alts = "|".join(re.escape(t) for t in triggers)
        pat = re.compile(
            r"(?:\b%s\b[^.?!]{0,30}\b(?:mean|means|error|fix|why)\b"
            r"|\b(?:fix|explain|understand|handle|resolve|what is|whats|"
            r"what's|about|how to)\b[^.?!]{0,30}\b%s\b)" % (alts, alts), re.I)

        def detect(cmd, _pat=pat):
            if _pat.search(cmd):
                return {"cmd": cmd}
            return None

        def execute(app, cmd, _reply=reply):
            return _reply

        reg_fn("cb_err_%02d" % idx, detect, execute)

    for _i, (_trg, _rep) in enumerate(ERROR_GUIDES):
        _cb_register_error(_i, _trg, _rep)

    reg_fn("cb_debug_request", _cb_debug_request_detect,
           _cb_debug_request_fn)
    reg_fn("cb_improve_request", _cb_improve_request_detect,
           _cb_improve_request_fn)

    # ---- D. CODE CONVERSION SKILLS ---------------------------------------

    PY_TO_JS_CHEATSHEET = (
        "Python to JavaScript quick map, sir:\n"
        "  print(x)             ->  console.log(x)\n"
        "  def f(a, b):         ->  function f(a, b) {\n"
        "  len(xs)              ->  xs.length\n"
        "  range(n)             ->  [...Array(n).keys()]\n"
        "  [x*2 for x in xs]    ->  xs.map(x => x * 2)\n"
        "  [x for x in xs if x] ->  xs.filter(Boolean)\n"
        "  d = {'a': 1}         ->  obj = {a: 1}\n"
        "  None / True / False  ->  null / true / false\n"
        "  elif                 ->  else if\n"
        '  f"hi {name}"         ->  `hi ${name}`\n'
        "  int(s) / str(x)      ->  parseInt(s) / String(x)\n"
        "  for k, v in d.items()->  for (const [k, v] of Object.entries(d))\n"
        "Paste your code after the request and I will translate it "
        "directly, sir.")

    def _cb_py_to_js_detect(cmd):
        if re.search(r"\b(?:convert|translate|port|rewrite)\s+(?:this\s+|"
                     r"my\s+|the\s+)?(?:python|py).{0,20}\b(?:java\s?script|"
                     r"js)\b", cmd, re.I) or \
           re.search(r"\b(?:python|py)\s+(?:code\s+)?to\s+(?:java\s?script|"
                     r"js)\b", cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_py_to_js_fn(app, cmd):
        code = _cb_payload(cmd, r"\b(?:convert|translate|port|rewrite)\b.*?")
        if code:
            return _llm_reply(app, "Translate this Python code to modern "
                                   "JavaScript (ES6+). Output only the "
                                   "JavaScript: %s" % code)
        return PY_TO_JS_CHEATSHEET

    _TARGET_LANGS = (r"python|java\s?script|js|typescript|ts|java|c\+\+|cpp|c|"
                     r"go(lang)?|rust|ruby|php|swift|kotlin|bash|shell|sql")

    def _cb_translate_detect(cmd):
        if re.search(r"\b(?:convert|translate|port|migrate|rewrite)\s+"
                     r"(?:this|that|my|the)?\s*(?:code|snippet|script|"
                     r"function|program|logic)?\s*(?:from\s+\w+\s+)?to\s+"
                     r"(?:%s)\b" % _TARGET_LANGS, cmd, re.I):
            return {"cmd": cmd}
        return None

    def _cb_translate_fn(app, cmd):
        m = re.search(r"\bto\s+(%s)\b" % _TARGET_LANGS, cmd, re.I)
        lang = m.group(1) if m else "the target language"
        code = _cb_payload(cmd, r"\b(?:convert|translate|port|migrate|"
                                r"rewrite)\b.*?")
        if code:
            return _llm_reply(app, "Translate this code to %s, keeping "
                                   "behavior identical. Output only the "
                                   "translated code: %s" % (lang, code))
        return ("Ready to translate, sir. Paste the code after the "
                "request, like: 'convert this code to rust: <paste>'.\n"
                "I will keep behavior identical and flag language features "
                "with no direct equivalent, sir.")

    reg_fn("cb_py_to_js", _cb_py_to_js_detect, _cb_py_to_js_fn)
    reg_fn("cb_translate", _cb_translate_detect, _cb_translate_fn)

    # ---- E-H. KNOWLEDGE BASE REGISTRAR -----------------------------------

    def _cb_kb(prefix, idx, triggers, reply):
        alts = "|".join(re.escape(t) for t in triggers)
        pat = re.compile(
            r"(?:\b(?:what\s+is|what's|whats|explain|define|tell\s+me\s+"
            r"about|how\s+(?:do|does|to|can|would)(?:\s+i|\s+you|\s+we|\s+"
            r"one)?|show\s+me|teach\s+me)\s+(?:a\s+|an\s+|the\s+|some\s+|"
            r"about\s+)?(?:%s)s?\b"
            r"|\b(?:%s)s?\s+(?:example|examples|tutorial|boilerplate|"
            r"cheat\s?sheet)\b)" % (alts, alts), re.I)

        def detect(cmd, _pat=pat):
            if _pat.search(cmd):
                return {"cmd": cmd}
            return None

        def execute(app, cmd, _reply=reply):
            return _reply

        reg_fn("%s_%03d" % (prefix, idx), detect, execute)

    # ---- E. WEB DEVELOPMENT ----------------------------------------------

    WEB_KB = [
        (("html boilerplate", "basic html page", "html skeleton"),
         'HTML5 boilerplate, sir:\n<!DOCTYPE html>\n<html lang="en">\n'
         "<head>\n"
         '  <meta charset="UTF-8">\n'
         '  <meta name="viewport" content="width=device-width, '
         'initial-scale=1.0">\n  <title>Page</title>\n</head>\n<body>\n'
         "  <h1>Hello</h1>\n</body>\n</html>"),
        (("semantic html", "semantic tags"),
         "Semantic tags describe meaning: <header>, <nav>, <main>, "
         "<article>, <section>, <aside>, <footer>. Screen readers and SEO "
         "both love them over div soup, sir."),
        (("viewport meta",),
         'Responsive pages start with: <meta name="viewport" '
         'content="width=device-width, initial-scale=1.0"> - it maps CSS '
         "pixels to device width instead of zooming out, sir."),
        (("css flexbox", "flexbox"),
         "Flexbox aligns children along one axis, sir:\n.container {\n"
         "  display: flex;\n  justify-content: space-between;\n"
         "  align-items: center;\n  gap: 16px;\n}"),
        (("css grid", "grid layout"),
         "CSS Grid handles two dimensions, sir:\n.grid {\n  display: grid;"
         "\n  grid-template-columns: repeat(3, 1fr);\n  gap: 20px;\n}\n"
         "Place children with grid-column/grid-row spans."),
        (("center a div", "center div"),
         "Three modern ways to center a div, sir:\n1. display:flex + "
         "align-items:center + justify-content:center on the parent.\n2. "
         "display:grid + place-items:center.\n3. position:absolute; top:50%;"
         " left:50%; transform:translate(-50%, -50%)."),
        (("media query", "media queries"),
         "Media queries adapt styles to screens, sir:\n@media "
         "(max-width: 600px) {\n  .sidebar { display: none; }\n}\n"
         "Mobile-first: default styles for phones, min-width queries upward."),
        (("css variables", "custom properties"),
         "CSS variables cascade and update at runtime, sir:\n:root { "
         "--brand: #00d4ff; }\n.button { background: var(--brand); }\nJS can"
         " flip themes via element.style.setProperty."),
        (("css transition", "hover effect"),
         "Transitions animate state changes smoothly, sir:\n.button { "
         "transition: transform .2s ease, background .2s; }\n.button:hover {"
         " transform: translateY(-2px); background: #09c; }"),
        (("css animation", "keyframes css"),
         "Keyframes animate without JS, sir:\n@keyframes pulse {\n  50% { "
         "opacity: .5; }\n}\n.badge { animation: pulse 1.5s infinite; }"),
        (("responsive image", "responsive images"),
         'Responsive images ship the right size, sir:\n<img src="small.jpg"'
         '\n     srcset="large.jpg 1200w, small.jpg 600w"\n     sizes='
         '"(max-width: 600px) 100vw, 50vw">'),
        (("tailwind", "tailwind css"),
         'Tailwind styles via utility classes, sir:\n<button class="bg-'
         'blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">'
         "Click</button>\nConfigure theme in tailwind.config.js."),
        (("bootstrap",),
         'Bootstrap gives a grid and components, sir:\n<div class="row">\n'
         '  <div class="col-md-6">Left</div>\n  <div class="col-md-6">'
         "Right</div>\n</div>\nPlus ready-made buttons, modals, navbars."),
        (("sass", "scss"),
         "Sass adds nesting, variables, and mixins to CSS, sir:\n$brand: "
         "#09c;\n.card {\n  color: $brand;\n  &:hover { opacity: .8; }\n}\n"
         "Compiles to plain CSS."),
        (("react component", "functional component react"),
         "React functional component, sir:\nfunction Greet({ name }) {\n"
         "  return <h1>Hello, {name}</h1>;\n}\nUse <Greet name=\"Sam\" /> - "
         "JSX compiles to React.createElement calls."),
        (("react props",),
         "Props flow down into components, sir:\n<Card title=\"Hi\" />\n"
         "function Card({ title }) { return <h2>{title}</h2>; } They are "
         "read-only; state changes come from the owner, sir."),
        (("react state", "usestate", "use state"),
         "useState holds changing values, sir:\nconst [count, setCount] = "
         "useState(0);\n<button onClick={() => setCount(count + 1)}>{count}"
         "</button>\nSetting state re-renders the component."),
        (("useeffect", "use effect", "react effect"),
         "useEffect runs side effects after render, sir:\nuseEffect(() => {"
         "\n  fetch('/api/data').then(r => r.json()).then(setData);\n}, []);"
         "\nThe [] deps array means once; add dependencies to re-run."),
        (("conditional rendering",),
         "React renders conditionally with JS operators, sir:\n{isLoggedIn ?"
         " <Dashboard /> : <Login />}\n{errors.length > 0 && <Alert "
         "msgs={errors} />}"),
        (("react list render", "keys react"),
         "Render lists with map and stable keys, sir:\n{todos.map(t => <li "
         "key={t.id}>{t.text}</li>)}\nKeys let React track identity across "
         "re-renders."),
        (("react form", "controlled input"),
         "Controlled forms bind inputs to state, sir:\nconst [email, setEmail]"
         " = useState('');\n<input value={email} onChange={e => setEmail(e."
         "target.value)} />"),
        (("react context", "context api"),
         "Context passes data down without prop drilling, sir:\nconst "
         "ThemeCtx = createContext('light');\n<ThemeCtx.Provider value=\"dark"
         "\">...</ThemeCtx.Provider>\nconst theme = useContext(ThemeCtx);"),
        (("custom hook", "custom hooks"),
         "Custom hooks reuse stateful logic, sir:\nfunction useFetch(url) {\n"
         "  const [data, setData] = useState(null);\n  useEffect(() => { "
         "fetch(url).then(r => r.json()).then(setData); }, [url]);\n  return"
         " data;\n}"),
        (("redux",),
         "Redux keeps app state in one store; dispatch actions, reducers "
         "return new state, sir:\ndispatch({ type: 'counter/increment' })\n"
         "Modern Redux Toolkit slices cut the boilerplate massively."),
        (("react router",),
         'React Router maps URLs to components, sir:\n<Routes>\n  <Route '
         'path="/" element={<Home />} />\n  <Route path="/user/:id" element='
         "{<User />} />\n</Routes>\nuseNavigate() moves programmatically."),
        (("next js", "nextjs"),
         "Next.js adds file-based routing, SSR, and API routes to React, "
         "sir:\npages/index.js -> /\npages/posts/[id].js -> /posts/1\n"
         "getServerSideProps fetches data per request."),
        (("vue component", "vue js"),
         "Vue components combine template, script, style, sir:\n<script setup>"
         "\nimport { ref } from 'vue';\nconst count = ref(0);\n</script>\n"
         '<template><button @click="count++">{{ count }}</button></template>'),
        (("angular component", "angular framework"),
         "Angular organizes by modules, components, services, sir:\n@"
         "Component({ selector: 'app-hello', template: '<h1>{{title}}</h1>' })"
         "\nexport class HelloComponent { title = 'Angular'; }\nData flows "
         "via @Input(), events via @Output()."),
        (("svelte",),
         "Svelte compiles away the framework, sir:\n<script>let count = 0;"
         "</script>\n<button on:click={() => count++}>{count}</button>\n"
         "Reactivity is plain assignment - no hooks or refs."),
        (("dom manipulation",),
         "DOM manipulation with vanilla JS, sir:\ndocument.querySelector("
         "'#box').textContent = 'Hi';\nel.classList.add('active');\nel."
         "setAttribute('href', url);\nparent.appendChild(node);"),
        (("addeventlistener", "event listener javascript"),
         "Event listeners wire interactions, sir:\nbtn.addEventListener('click'"
         ", (e) => { e.preventDefault(); submit(); });\nremoveEventListener "
         "cleans up on teardown."),
        (("fetch api", "fetch javascript"),
         "Fetch calls APIs, sir:\nconst res = await fetch('/api/users', { "
         "method: 'POST', headers: {'Content-Type': 'application/json'}, body:"
         " JSON.stringify(user) });\nif (!res.ok) throw new Error(res.status);"),
        (("async function javascript",),
         "Async/await flattens promise chains, sir:\nasync function load() {\n"
         "  try {\n    const res = await fetch(url);\n    return await res.json();"
         "\n  } catch (e) { console.error(e); }\n}"),
        (("promises javascript", "promise chain"),
         "Promises chain async steps, sir:\nfetch(url)\n  .then(r => r.json())"
         "\n  .then(data => render(data))\n  .catch(err => console.error(err));"
         "\nPromise.all waits for many at once."),
        (("arrow function", "arrow functions"),
         "Arrow functions are concise and inherit 'this', sir:\nconst add = "
         "(a, b) => a + b;\nsetTimeout(() => this.save(), 100);\nAvoid them as"
         " object methods needing their own this."),
        (("destructuring javascript", "spread operator"),
         "Destructuring unpacks, spread copies, sir:\nconst { name, age } = "
         "user;\nconst [first, ...rest] = list;\nconst merged = { ...defs, ..."
         "overrides };\nCopy arrays with [...arr]."),
        (("template literal", "template literals"),
         "Template literals interpolate and span lines, sir:\n`Hello ${name},"
         " you have ${count} messages.`\nExpressions go inside ${ }, including"
         " function calls."),
        (("array methods javascript", "map filter reduce"),
         "Array trinity, sir:\nxs.map(x => x * 2)      // transform\nxs.filter(x"
         " => x.ok)    // select\nxs.reduce((sum, x) => sum + x, 0) // fold\nThey"
         " return new arrays/values - chainable and pure."),
        (("localstorage", "local storage javascript"),
         "localStorage persists strings across sessions; sessionStorage clears"
         " with the tab, sir:\nlocalStorage.setItem('theme', 'dark');\nconst t ="
         " localStorage.getItem('theme');\nStore JSON via JSON.stringify/parse."),
        (("form validation javascript",),
         "Validate forms on submit and on blur, sir:\nform.addEventListener("
         "'submit', e => {\n  if (!email.includes('@')) { e.preventDefault(); "
         "showError(); }\n});\nHTML5 helpers: required, type=email, pattern."),
        (("rest api design", "api design best practices"),
         "REST design rules, sir:\nNouns for URLs (/users/42/orders), verbs via"
         " HTTP methods, plural collections, filtering via query ?status=open,"
         " version /v1/, meaningful status codes (201 created, 400 bad input,"
         " 404 missing)."),
        (("http status codes", "status codes http"),
         "Status code families, sir:\n200 OK, 201 Created, 204 No Content\n"
         "301/308 redirect, 304 cached\n400 bad input, 401 unauthenticated, 403"
         " forbidden, 404 missing, 409 conflict, 422 invalid\n500 server bug, "
         "502 upstream, 503 unavailable, 429 rate limited."),
        (("http methods",),
         "HTTP verbs carry semantics, sir:\nGET reads (safe, cacheable), POST "
         "creates, PUT replaces fully, PATCH updates partly, DELETE removes. "
         "Idempotent: GET/PUT/PATCH/DELETE - safe to retry."),
        (("jwt authentication", "jwt token"),
         "JWT auth flow, sir:\n1. Login -> server signs token (header.payload."
         "signature).\n2. Client sends Authorization: Bearer <token>.\n3. Server"
         " verifies signature, no session store needed.\nKeep tokens short-lived;"
         " refresh tokens renew."),
        (("oauth flow", "oauth2"),
         "OAuth2 delegates access without sharing passwords, sir: your app "
         "redirects to Google, the user consents, Google returns a code, your "
         "backend exchanges it for tokens. PKCE protects public clients."),
        (("websocket javascript", "socket io"),
         "Real-time channels with WebSockets, sir:\nconst ws = new WebSocket("
         "'ws://host');\nws.onmessage = e => render(JSON.parse(e.data));\nws.send"
         "(JSON.stringify(msg));\nSocket.IO adds rooms and fallbacks."),
        (("flask app", "flask hello world"),
         "Minimal Flask app, sir:\nfrom flask import Flask\napp = Flask(__name__)"
         "\n\n@app.route('/')\ndef home():\n    return 'Hello!'\n\napp.run(debug="
         "True)\nRoutes with vars: @app.route('/user/<name>')"),
        (("flask blueprint", "blueprints flask"),
         "Blueprints split Flask apps, sir:\nusers_bp = Blueprint('users', "
         "__name__, url_prefix='/users')\n@users_bp.route('/')\ndef list_(): ..."
         "\napp.register_blueprint(users_bp)"),
        (("django setup", "start django project"),
         "Start Django, sir:\npip install django\ndjango-admin startproject "
         "mysite\ncd mysite && python manage.py startapp blog\npython manage.py "
         "migrate\npython manage.py runserver"),
        (("django model", "django views"),
         "Django MVT, sir:\nmodels.py: class Post(models.Model): title = models."
         "CharField(max_length=200)\nviews.py: def index(request): return render("
         "request, 'index.html', {'posts': Post.objects.all()})\nurls.py maps "
         "paths to views."),
        (("express server", "express js hello"),
         "Express server, sir:\nconst express = require('express');\nconst app ="
         " express();\napp.use(express.json());\napp.get('/hello', (req, res) =>"
         " res.json({ hi: true }));\napp.listen(3000);"),
        (("express middleware",),
         "Middleware runs before handlers, sir:\napp.use((req, res, next) => { "
         "console.log(req.method, req.url); next(); });\nAuth checks, body "
         "parsing, logging all live here; errors take (err, req, res, next)."),
        (("fastapi app",),
         "FastAPI serves typed async APIs, sir:\nfrom fastapi import FastAPI\n"
         "app = FastAPI()\n\n@app.get('/items/{item_id}')\nasync def read(item_id:"
         ' int, q: str | None = None):\n    return {"item_id": item_id, "q": q}'
         "\nAuto docs at /docs, sir."),
        (("npm commands",),
         "npm essentials, sir:\nnpm init -y        # package.json\nnpm install "
         "express  # add dependency\nnpm install -D jest   # dev dependency\nnpm"
         " run dev        # run scripts\nnpx create-vite app # scaffold without "
         "installing"),
        (("webpack vite", "bundler javascript"),
         "Bundlers pack modules for the browser, sir: Vite dev-runs with instant"
         " HMR (npm create vite@latest), production-builds optimized assets. "
         "Webpack configures loaders/plugins; most scaffolds hide it nowadays."),
        (("sql join", "joins sql"),
         "SQL joins, sir:\nINNER JOIN keeps matches only; LEFT JOIN keeps all "
         "left rows (NULL where missing); RIGHT mirrors it; FULL keeps everything;"
         " CROSS multiplies.\nSELECT u.name, COUNT(o.id) FROM users u LEFT JOIN "
         "orders o ON o.user_id = u.id GROUP BY u.id;"),
        (("sql create index", "index sql table"),
         "Speed up filters with indexes, sir:\nCREATE INDEX idx_users_email ON "
         "users(email);\nComposite order matters (email, created_at). Check usage"
         " with EXPLAIN QUERY PLAN before and after."),
        (("mongodb crud", "mongo db basics"),
         "MongoDB CRUD, sir:\ndb.users.insertOne({ name: 'Ada' })\ndb.users.find({"
         " age: { $gt: 21 } })\ndb.users.updateOne({ name: 'Ada' }, { $set: { age:"
         " 37 } })\ndb.users.deleteOne({ name: 'Ada' })"),
        (("mongoose schema",),
         "Mongoose models MongoDB documents, sir:\nconst User = mongoose.model("
         "'User', new mongoose.Schema({\n  name: { type: String, required: true },"
         "\n  age: Number\n}));\nawait User.create({ name: 'Ada' });"),
        (("sql vs nosql",),
         "Choose SQL for relationships, strict schema, and ACID money math; choose"
         " NoSQL for flexible documents, horizontal scale, and cache-like speed. "
         "Most real systems happily use both, sir."),
    ]

    for _i, (_trg, _rep) in enumerate(WEB_KB):
        _cb_kb("cb_web", _i, _trg, _rep)

    # ---- F. APP DEVELOPMENT ----------------------------------------------

    APP_KB = [
        (("android activity lifecycle", "activity lifecycle android"),
         "Activity lifecycle callbacks, sir:\nonCreate -> onStart -> onResume"
         " -> [running] -> onPause -> onStop -> onDestroy.\nSave state in "
         "onSaveInstanceState; release resources in onStop/onDestroy."),
        (("android intent",),
         'Intents start actions, sir:\nExplicit: Intent(this, DetailActivity::'
         'class.java)\nImplicit: Intent(Intent.ACTION_SEND).apply { type = '
         '"text/plain"; putExtra(Intent.EXTRA_TEXT, msg) }\nstartActivity('
         "intent) launches it."),
        (("jetpack compose",),
         "Jetpack Compose builds UI in Kotlin, sir:\n@Composable\nfun Counter()"
         ' {\n  var count by remember { mutableStateOf(0) }\n  Button(onClick ='
         ' { count++ }) { Text("Count: $count") }\n}\nRecomposition redraws on '
         "state change."),
        (("recyclerview", "android list view"),
         "RecyclerView renders long lists efficiently, sir: adapter binds "
         "viewholders, LayoutManager positions them, DiffUtil updates only "
         "changed rows. In Compose, LazyColumn replaces it entirely."),
        (("android room database", "room database"),
         'Room persists SQLite via annotations, sir:\n@Entity data class User('
         '@PrimaryKey val id: Int, val name: String)\n@Dao interface UserDao { '
         '@Query("SELECT * FROM User") fun all(): Flow<List<User>> }\n@Database('
         "entities=[User::class]) abstract class AppDb : RoomDatabase()"),
        (("retrofit android",),
         "Retrofit types HTTP APIs, sir:\ninterface Api { @GET(\"users/{id}\") "
         "suspend fun user(@Path(\"id\") id: Int): User }\nRetrofit.Builder()."
         'baseUrl("https://x.dev/").addConverterFactory(MoshiConverterFactory.'
         "create()).build().create(Api::class.java)"),
        (("android gradle", "gradle dependencies android"),
         "Gradle manages Android builds, sir: app/build.gradle.kts lists "
         'dependencies { implementation("com.squareup.retrofit2:retrofit:'
         '2.11.0") }. Sync after edits; buildTypes switch debug/release flags.'),
        (("android permissions", "android manifest"),
         'Android permissions go in the manifest, sir:\n<uses-permission '
         'android:name="android.permission.INTERNET"/>\nDangerous ones (camera,'
         " location) also need runtime requestPermissions() on API 23+."),
        (("android fragment",),
         "Fragments are reusable UI sections inside activities, sir: own "
         "lifecycle tied to the host, swapped via FragmentManager, sharing "
         "ViewModels with the activity. Compose Navigation largely replaces "
         "them in new apps."),
        (("swiftui view", "swiftui basics"),
         "SwiftUI declares views, sir:\nstruct Counter: View {\n  @State private"
         ' var count = 0\n  var body: some View {\n    Button("Count: \\(count)")'
         " { count += 1 }\n  }\n}\nBody recomputes when @State changes."),
        (("swiftui state wrappers", "binding swiftui"),
         "SwiftUI property wrappers, sir: @State for local value, @Binding to "
         "share write access, @StateObject/@ObservedObject for reference models,"
         " @EnvironmentObject for app-wide injection."),
        (("uikit view controller", "view controller lifecycle ios"),
         "UIKit lifecycle order, sir: viewDidLoad (once, wire UI) -> "
         "viewWillAppear -> viewDidAppear -> viewWillDisappear -> "
         "viewDidDisappear. Auto Layout constraints set geometry; outlets connect"
         " storyboard views to code."),
        (("swift optionals", "swift language basics"),
         "Swift optionals ban nil accidents, sir:\nvar name: String? = nil\nif let"
         ' n = name { print(n) }        // safe unwrap\nguard let n = name else { '
         'return }   // early exit\nlet n2 = name ?? "guest"    // default'),
        (("uitableview", "ios table view"),
         "UITableView lists data via datasource/delegate, sir: numberOfRowsInSection"
         " + cellForRowAt dequeue cells. SwiftUI List(rows) achieves the same "
         "declaratively with swipe actions for free."),
        (("core data ios",),
         "Core Data persists object graphs, sir: model entities in the .xcdatamodeld"
         " editor, NSPersistentContainer loads the store, NSFetchRequest queries, "
         "@FetchRequest integrates SwiftUI views directly."),
        (("app store submission", "publish ios app"),
         "Ship to the App Store, sir: Apple Developer account ($99/yr) -> archive"
         " a release build in Xcode -> upload via Transporter -> fill App Store "
         "Connect listing (screenshots, privacy labels) -> submit for review "
         "(usually 24-48h)."),
        (("google play publish", "publish android app"),
         "Publish to Google Play, sir: Play Console account ($25 once) -> generate"
         " a signed AAB in Android Studio -> create listing with screenshots and "
         "content rating -> roll out to internal, then closed, then production "
         "tracks."),
        (("react native setup",),
         "React Native ships JS mobile apps, sir: npx create-expo-app MyApp -> "
         "npx expo start gives QR-code previews. Views map to native widgets; most"
         " npm React knowledge transfers."),
        (("react native styling", "react native components"),
         "RN styles with StyleSheet, sir:\nimport { View, Text, StyleSheet } from"
         " 'react-native';\n<View style={styles.box}><Text>Hello</Text></View>\nconst"
         " styles = StyleSheet.create({ box: { flex: 1, justifyContent: 'center' } });"),
        (("react native navigation",),
         "Navigation in RN, sir: @react-navigation/native provides Stack (push/pop),"
         " Tab, and Drawer navigators.\nnavigation.navigate('Details', { id: 7 }) "
         "pushes; route.params reads the payload."),
        (("flutter setup", "flutter create app"),
         "Flutter setup, sir: install SDK + Android Studio plugin -> flutter doctor"
         " verifies toolchain -> flutter create my_app -> flutter run. Hot reload "
         "applies edits in under a second."),
        (("flutter widget", "stateful widget flutter"),
         "Flutter is widgets all the way down, sir:\nclass Hello extends "
         "StatelessWidget {\n  Widget build(BuildContext c) => Text('Hi');\n}\nExtend"
         " StatefulWidget when data changes; setState() triggers rebuild."),
        (("flutter navigation", "flutter routes"),
         "Flutter navigation, sir:\nNavigator.push(context, MaterialPageRoute("
         "builder: (_) => DetailPage()));\nNavigator.pop(context);\nNamed routes: "
         "MaterialApp(routes: {'/detail': (_) => DetailPage()}), then pushNamed('/"
         "detail')."),
        (("flutter http",),
         "Flutter HTTP, sir: add package:http ->\nfinal res = await http.get(Uri.parse(url));"
         "\nif (res.statusCode == 200) { final data = jsonDecode(res.body); }\nWrap in"
         " FutureBuilder or use async state management (Riverpod/Bloc)."),
        (("dart null safety", "dart basics"),
         "Dart is typed with null safety, sir:\nString? nickname;   // may be null\n"
         "nickname?.length       // null-aware call\nnickname ?? 'none'    // default"
         "\nlate String forced;   // set before use, trust me"),
        (("mvvm architecture", "mvvm pattern"),
         "MVVM splits Model (data), View (passive UI), ViewModel (state + logic "
         "exposed observably). Views bind to ViewModel properties - testable logic,"
         " thin screens. Standard on WPF, Android, and SwiftUI with Combine."),
        (("mvc vs mvp vs mvvm", "mvc mvp mvvm"),
         "UI pattern spectrum, sir: MVC wires a controller between view and model;"
         " MVP inserts a presenter the view talks to (testable, chatty); MVVM lets"
         " the view observe a viewmodel declaratively. Modern UI kits favor MVVM-ish"
         " binding."),
        (("push notifications fcm", "apns push"),
         "Push notifications ride FCM (Android) or APNs (iOS), sir: app gets a device"
         " token, your server sends payloads through the service, OS displays them."
         " FlutterFire/Notifee or UNUserNotificationCenter handle the client side."),
        (("mobile local storage", "shared preferences android"),
         "Mobile persistence menu, sir: SharedPreferences/UserDefaults for tiny "
         "key-value flags; SQLite/Room/Core Data for structured data; files for blobs;"
         " Keychain/Keystore for secrets - never plain storage."),
        (("deep linking mobile", "universal links"),
         "Deep links open app screens from URLs, sir: register a scheme or universal"
         " link/domain association, route by path (products/42), fall back to web when"
         " the app is missing. Great for campaigns and sharing."),
        (("mobile app security",),
         "Mobile security checklist, sir: TLS everywhere + certificate pinning, tokens"
         " in Keychain/Keystore, no secrets in code, biometric gates for sensitive "
         "screens, obfuscate (ProGuard/R8), and validate server-side - never trust the"
         " client."),
        (("responsive mobile layout", "handle screen sizes"),
         "Handle screen diversity, sir: constraint/rule-based layouts over magic "
         "numbers, size classes/window breakpoints for tablets, scalable fonts, safe"
         " areas (notches), and test on small + big + foldable previews."),
        (("electron app setup", "build desktop app electron"),
         "Electron wraps Chromium + Node for desktop apps, sir:\nnpm i electron\nmain.js"
         " creates BrowserWindow loading index.html; the page is your renderer. VS Code"
         " and Slack ship this way."),
        (("electron ipc",),
         "Electron IPC bridges processes, sir:\npreload.js: contextBridge."
         "exposeInMainWorld('api', { save: d => ipcRenderer.invoke('save', d) })\nmain.js:"
         " ipcMain.handle('save', (e, d) => fs.write(...))\nRenderer calls window.api.save(data)."),
        (("electron packaging", "package electron app"),
         "Package Electron apps, sir: electron-builder or Forge bundle installers - npx"
         " electron-builder --mac --win --linux produces .dmg/.exe/AppImage. Code-sign"
         " with developer certificates for smooth installs."),
        (("tkinter window", "tkinter hello world"),
         "Tkinter window, sir:\nimport tkinter as tk\nroot = tk.Tk()\nroot.title('App')"
         "\ntk.Label(root, text='Hello').pack(padx=20, pady=10)\nroot.mainloop()"),
        (("tkinter button widget", "tkinter events"),
         "Tkinter widgets respond via command or bind, sir:\nbtn = tk.Button(root, "
         "text='Go', command=on_go)\nentry.bind('<Return>', lambda e: submit())\nWidgets:"
         " Label, Entry, Text, Listbox, Canvas, plus ttk themed variants."),
        (("tkinter grid layout", "tkinter layout"),
         "Tkinter geometry managers, sir: grid(row=, column=) for tables, pack(side=)"
         " for edges, place(x=, y=) for absolute. Mixing managers in one container "
         "misbehaves - pick grid for real forms."),
        (("tkinter dialog", "tkinter file dialog", "messagebox tkinter"),
         "Tkinter dialogs, sir:\nfrom tkinter import filedialog, messagebox\npath = "
         "filedialog.askopenfilename()\nmessagebox.showinfo('Done', 'Saved successfully')"
         "\nasksaveasfilename and showerror round it out."),
        (("pyqt python gui", "pyside qt"),
         "PyQt/PySide wrap Qt, sir:\nfrom PySide6.QtWidgets import QApplication, QLabel"
         "\napp = QApplication([])\nQLabel('Hello').show()\napp.exec()\nQt Designer drags"
         " UIs; pyuic/pyside-uic convert them to Python."),
        (("signals and slots", "pyqt signals"),
         "Signals and slots wire Qt events, sir:\nbtn.clicked.connect(self.on_click)"
         "\ncustom = Signal(str)  # declare in QObject class\ncustom.emit('done')  # anyone"
         " listening reacts\nLoose coupling, thread-safe delivery."),
        (("kivy python mobile",),
         "Kivy builds touch apps in pure Python, sir:\nfrom kivy.app import App\nfrom "
         "kivy.uix.button import Button\nclass MyApp(App):\n    def build(self): return"
         " Button(text='Tap me')\nMyApp().run()\nBuildozer packages to Android."),
        (("wxpython",),
         "wxPython gives native-looking desktop UIs, sir:\nimport wx\napp = wx.App()\nf ="
         " wx.Frame(None, title='App')\nf.Show()\napp.MainLoop()\nSizers manage layout;"
         " events bind with Bind()."),
        (("tauri desktop app",),
         "Tauri builds tiny desktop apps: Rust core + system webview instead of bundled"
         " Chromium, sir - megabytes not hundreds. Frontend stays any JS framework; src-tauri/"
         " commands expose native power."),
        (("menubar tray app", "system tray application"),
         "Menu bar/tray apps live beside the clock, sir: macOS NSStatusItem (or rumps for"
         " Python), Windows tray icon via pystray, Electron Tray class. Perfect for monitors"
         " and quick actions - no dock clutter."),
        (("progressive web app", "pwa"),
         "PWAs install web apps to home screens, sir: web app manifest (name, icons), service"
         " worker caching shell + data, HTTPS, offline page. Lighthouse audits installability."),
        (("capacitor cordova", "wrap web app mobile"),
         "Capacitor/Cordova wrap web apps in native shells, sir: npm i @capacitor/core "
         "@capacitor/cli -> npx cap add ios android -> native plugins expose camera/files/"
         "geolocation to JS."),
        (("mobile app testing",),
         "Mobile testing pyramid, sir: unit tests for logic (JUnit/XCTest/pytest), integration"
         " for repos/APIs, UI automation (Espresso, XCUITest, Appium, Maestro) on real devices,"
         " plus Firebase Test Lab farms."),
        (("app monetization",),
         "Monetization models, sir: paid upfront (simple, high friction), freemium + IAP "
         "upgrades, subscriptions for ongoing value, ads (AdMob banners/interstitials/rewarded),"
         " hybrid. Store fees run 15-30%."),
        (("sqlite mobile app",),
         "SQLite is the embedded workhorse, sir: zero-config single-file DB inside the app."
         " Python: import sqlite3; conn.execute('CREATE TABLE ...'). Mobile equivalents: Room"
         " (Android), Core Data/GRDB (iOS)."),
        (("android viewmodel", "viewmodel livedata"),
         "ViewModel survives rotation and holds UI state, sir:\nclass MainVm : ViewModel() {"
         "\n  private val _count = MutableLiveData(0)\n  val count: LiveData<Int> get() = _count"
         "\n  fun inc() { _count.value = (_count.value ?: 0) + 1 }\n}\nObserve from the activity;"
         " StateFlow is the modern flavor."),
    ]

    for _i, (_trg, _rep) in enumerate(APP_KB):
        _cb_kb("cb_app", _i, _trg, _rep)

    # ---- G. DATA SCIENCE --------------------------------------------------

    DS_KB = [
        (("pandas read csv", "read csv pandas"),
         "Read CSV into a DataFrame, sir:\nimport pandas as pd\ndf = pd.read_csv('file.csv')"
         "\nHandy args: parse_dates=['date'], usecols=[...], nrows=1000."),
        (("pandas dataframe basics", "pandas head describe"),
         "DataFrame first look, sir:\ndf.head()/df.tail() peek\ndf.info() types + nulls\n"
         "df.describe() numeric summary\ndf.shape gives rows x columns."),
        (("pandas filter rows", "loc iloc pandas"),
         "Select and filter, sir:\ndf['col'] series; df[['a','b']] frame\ndf.loc[df.age > 30,"
         " ['name','age']] label-based\ndf.iloc[0:5, 0:2] position-based\nmask = df.city.isin("
         "['Delhi','Mumbai'])"),
        (("pandas groupby", "group by pandas"),
         "Split-apply-combine, sir:\ndf.groupby('dept')['salary'].agg(['mean', 'max'])\n"
         "df.groupby(['dept','year']).size()\nPivot flavor: df.pivot_table(index='dept', "
         "columns='year', values='sales', aggfunc='sum')"),
        (("pandas merge", "concat pandas"),
         "Combine DataFrames, sir:\npd.merge(left, right, on='id', how='inner')  # left/right/"
         "outer\npd.concat([df1, df2], axis=0)  # stack rows\ndf1.join(df2, lsuffix='_1')  # index-based"),
        (("pivot table pandas",),
         "Reshape summaries, sir:\ndf.pivot_table(values='sales', index='region', columns='quarter',"
         " aggfunc='sum', fill_value=0, margins=True)\nmelt() reverses wide to long."),
        (("pandas missing values", "fillna pandas"),
         "Missing data triage, sir:\ndf.isna().sum() counts\ndf.dropna(subset=['age']) removes\n"
         "df['age'].fillna(df['age'].median()) fills\nTime series: df.interpolate()."),
        (("pandas apply", "apply function pandas"),
         "Row-wise transforms, sir:\ndf['full'] = df.apply(lambda r: r.a + ' ' + r.b, axis=1)\n"
         "df['col'].map(str.title)\nVectorize when possible - np.where(df.age > 18, 'adult', 'minor')"
         " beats apply."),
        (("sort_values pandas", "value_counts"),
         "Order and count, sir:\ndf.sort_values('col', ascending=False)\ndf.nlargest(5, 'score')\n"
         "df['city'].value_counts(normalize=True)  # frequency share"),
        (("pandas datetime", "to_datetime"),
         "Datetime handling, sir:\ndf['date'] = pd.to_datetime(df['date'], errors='coerce')\n"
         "df.set_index('date').resample('M').sum()\nAccessors: df.date.dt.year, .dt.month, .dt.dayofweek."),
        (("pandas to csv", "export dataframe"),
         "Export results, sir:\ndf.to_csv('out.csv', index=False)\ndf.to_excel('out.xlsx', sheet_name="
         "'Report')\nMulti-sheet needs pd.ExcelWriter as a context manager."),
        (("numpy array", "create numpy array"),
         "NumPy arrays, sir:\nimport numpy as np\na = np.array([[1, 2], [3, 4]])\nnp.zeros((3, 3)),"
         " np.ones(5), np.arange(0, 10, 2), np.linspace(0, 1, 11)\nVectorized math: a * 2 + 1 elementwise."),
        (("numpy indexing slicing",),
         "Index and slice arrays, sir:\na[0, 1], a[:, 0] column, a[::-1] reverse\nBoolean masks: a[a > 2]"
         " = 0\nFancy indexing: a[[0, 2], [1, 0]] picks pairs."),
        (("numpy broadcasting",),
         "Broadcasting stretches shapes without copying, sir:\n(3, 3) matrix + (3,) row vector adds per"
         " row automatically\nRules align trailing dimensions; size-1 dims stretch. np.newaxis inserts axes."),
        (("numpy random numbers",),
         "Random numbers, sir:\nrng = np.random.default_rng(42)  # seeded, modern API\nrng.integers(0, 10,"
         " size=(2, 3))\nrng.normal(loc=0, scale=1, size=1000)\nrng.choice(names, size=3, replace=False)"),
        (("numpy statistics",),
         "Descriptive stats, sir:\na.mean(axis=0), np.median(a), a.std(), a.var()\nnp.percentile(a, [25, 50,"
         " 75]) quartiles\ncorr = np.corrcoef(x, y)[0, 1]"),
        (("matplotlib line plot", "plot python matplotlib"),
         "Line plots, sir:\nimport matplotlib.pyplot as plt\nplt.plot(x, y, label='series')\nplt.xlabel('t');"
         " plt.ylabel('v'); plt.legend(); plt.title('Signal')\nplt.show()"),
        (("matplotlib subplots",),
         "Grids of plots, sir:\nfig, axes = plt.subplots(2, 2, figsize=(10, 6))\naxes[0, 0].plot(x, y)"
         "\nfig.suptitle('Overview')\nfig.tight_layout()"),
        (("histogram matplotlib",),
         "Histograms show distributions, sir:\nplt.hist(data, bins=30, edgecolor='white')\nNormalize with"
         " density=True; compare groups by overlaying alpha=0.6."),
        (("scatter plot matplotlib",),
         "Scatter plots reveal relationships, sir:\nplt.scatter(x, y, c=labels, s=sizes, alpha=0.6, cmap="
         "'viridis')\nplt.colorbar() decodes c."),
        (("bar chart matplotlib",),
         "Bar charts compare categories, sir:\nplt.bar(cats, vals)\nHorizontal: plt.barh\nGrouped: offset x"
         " positions per series; annotate with plt.bar_label(bars)."),
        (("savefig matplotlib", "save plot image"),
         "Save figures, sir:\nplt.savefig('chart.png', dpi=300, bbox_inches='tight')\nPDF/SVG for print "
         "quality; call before plt.show()."),
        (("seaborn plots",),
         "Seaborn dresses matplotlib statistically, sir:\nimport seaborn as sns\nsns.histplot(df, x='age',"
         " hue='group', kde=True)\nsns.heatmap(df.corr(), annot=True, cmap='coolwarm')\nsns.pairplot(df, hue="
         "'species')"),
    ]

    DS_ML_KB = [
        (("jupyter notebook tips", "jupyter shortcuts"),
         "Jupyter essentials, sir: Shift+Enter runs a cell; A/B insert above/below; DD deletes; M/Y switch "
         "markdown/code. Magics: %timeit, %%time, %matplotlib inline, !pip install pkg."),
        (("train test split sklearn",),
         "Hold-out evaluation, sir:\nfrom sklearn.model_selection import train_test_split\nX_tr, X_te, y_tr,"
         " y_te = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)"),
        (("linear regression sklearn", "fit linear regression"),
         "Linear regression, sir:\nfrom sklearn.linear_model import LinearRegression\nmodel = LinearRegression()"
         ".fit(X_train, y_train)\npreds = model.predict(X_test)\ncoef_ and intercept_ explain the fit; R^2 via "
         "model.score(X_test, y_test)."),
        (("logistic regression sklearn",),
         "Logistic regression classifies probabilities, sir: linear model squashed by sigmoid. from sklearn."
         "linear_model import LogisticRegression; tune C for regularization strength."),
        (("random forest sklearn",),
         "Random forest = bagged decision trees voting, sir:\nfrom sklearn.ensemble import RandomForestClassifier"
         "\nrf = RandomForestClassifier(n_estimators=300).fit(X_tr, y_tr)\nrf.feature_importances_ ranks drivers."),
        (("decision tree sklearn",),
         "Decision trees split features greedily, sir:\nfrom sklearn.tree import DecisionTreeClassifier, export_text"
         "\nprint(export_text(tree.fit(X, y), feature_names=cols))\nDepth-limit or they memorize noise."),
        (("kmeans clustering", "k means clustering"),
         "K-Means groups unlabeled data, sir:\nfrom sklearn.cluster import KMeans\nkm = KMeans(n_clusters=3, "
         "n_init=10).fit(X_scaled)\nkm.labels_, km.cluster_centers_\nElbow/inertia or silhouette score pick k."),
        (("knn classifier", "k nearest neighbors"),
         "KNN votes with neighbors, sir:\nfrom sklearn.neighbors import KNeighborsClassifier\nknn = "
         "KNeighborsClassifier(n_neighbors=5).fit(X_scaled, y_tr)\nScale features first - distance is everything."),
        (("svm sklearn", "support vector machine"),
         "SVMs find maximum-margin boundaries, sir:\nfrom sklearn.svm import SVC\nsvc = SVC(kernel='rbf', C=1.0,"
         " gamma='scale').fit(X_scaled, y)\nKernels bend space; C trades margin width for violations."),
        (("naive bayes classifier",),
         "Naive Bayes multiplies feature likelihoods assuming independence - fast baseline for text spam, sir:"
         "\nfrom sklearn.naive_bayes import MultinomialNB\nnb.fit(X_counts, y); nb.predict(new_docs)"),
        (("gradient boosting xgboost", "lightgbm"),
         "Gradient boosting grows trees that correct predecessors' errors, sir: HistGradientBoostingClassifier"
         " (sklearn) or XGBoost/LightGBM for speed. Watch learning_rate, max_depth, early stopping."),
        (("neural network keras", "keras model"),
         "Tiny Keras network, sir:\nfrom tensorflow import keras\nm = keras.Sequential([\n  keras.layers.Dense(64,"
         " activation='relu'),\n  keras.layers.Dense(1, activation='sigmoid')])\nm.compile(optimizer='adam', loss="
         "'binary_crossentropy', metrics=['accuracy'])\nm.fit(X, y, epochs=10, validation_split=0.2)"),
        (("overfitting underfitting", "regularization machine learning"),
         "Overfitting memorizes train, fails test; underfitting misses both, sir. Remedies: more data, simpler"
         " model, dropout, L2 weight decay, early stopping. Learning curves diagnose which."),
        (("cross validation sklearn", "cross_val_score"),
         "Cross-validation rotates folds for honest scores, sir:\nfrom sklearn.model_selection import "
         "cross_val_score\nscores = cross_val_score(model, X, y, cv=5)\nscores.mean(), scores.std()"),
        (("confusion matrix precision recall", "precision recall f1"),
         "Classification metrics, sir:\nfrom sklearn.metrics import confusion_matrix, classification_report\n"
         "Precision = TP/(TP+FP) 'when I say yes am I right'; Recall = TP/(TP+FN) 'did I catch all'; F1 balances them."),
        (("roc auc curve",),
         "ROC curves trade recall against false positives across thresholds, sir: from sklearn.metrics import "
         "roc_auc_score; roc_auc_score(y, proba). 0.5 coin-flip, 0.9 strong, 1.0 perfect."),
        (("feature scaling standard scaler",),
         "Scale features so distance models behave, sir:\nfrom sklearn.preprocessing import StandardScaler\n"
         "X_scaled = StandardScaler().fit_transform(X)\nMinMaxScaler squeezes to [0, 1]; fit on train only."),
        (("one hot encoding categorical",),
         "Encode categories, sir:\npd.get_dummies(df, columns=['city'])\nOr sklearn OneHotEncoder(handle_unknown="
         "'ignore') inside pipelines. High-cardinality? Target/hash encoding instead."),
        (("sklearn pipeline",),
         "Pipelines chain preprocessing + model safely, sir:\nfrom sklearn.pipeline import make_pipeline\npipe = "
         "make_pipeline(StandardScaler(), LogisticRegression())\npipe.fit(X_tr, y_tr); cross_val_score(pipe, X, y)"
         " - no leakage."),
        (("grid search hyperparameter tuning",),
         "Tune hyperparameters exhaustively, sir:\nfrom sklearn.model_selection import GridSearchCV\ngs = "
         "GridSearchCV(pipe, param_grid={'logisticregression__C': [0.1, 1, 10]}, cv=5)\ngs.best_params_, gs.best_score_"),
        (("save model joblib", "persist trained model"),
         "Persist trained models, sir:\nimport joblib\njoblib.dump(model, 'model.joblib')\nlater = joblib.load('model.joblib')"
         "\nMatch versions between training and serving environments."),
    ]

    for _i, (_trg, _rep) in enumerate(DS_KB + DS_ML_KB):
        _cb_kb("cb_ds", _i, _trg, _rep)

    # ---- H. SYSTEM PROGRAMMING --------------------------------------------

    SYS_KB = [
        (("bash script basics", "shell script shebang"),
         "Shell scripts start with a shebang, sir:\n#!/usr/bin/env bash\nset -euo pipefail   # fail fast, unset"
         " vars, pipeline errors\necho 'hello'\nchmod +x script.sh && ./script.sh"),
        (("bash script arguments",),
         'Script arguments, sir:\n$1 $2 ... positional; $# count; $@ all quoted; $? last exit code\nfirst="$1"'
         "\n[ $# -lt 1 ] && { echo 'usage: ...'; exit 1; }"),
        (("bash if statement", "bash conditionals"),
         'Bash conditionals, sir:\nif [[ -f "$file" ]]; then\n  echo exists\nelif [[ -z "$name" ]]; then\n'
         "  echo empty\nelse\n  echo other\nfi\nTests: -d dir, -e exists, -x executable, == glob match."),
        (("bash for loop", "while loop bash"),
         'Bash loops, sir:\nfor f in *.txt; do echo "$f"; done\nfor i in $(seq 1 5); do ... \nwhile read -r line;'
         ' do echo "$line"; done < file.txt\nC-style: for ((i=0; i<5; i++)).'),
        (("bash functions",),
         'Bash functions, sir:\ngreet() {\n  local name="$1"\n  echo "hi $name"\n}\ngreet Sam   # prints: hi Sam'
         "\nReturn codes with 'return N'; echo for output capture."),
        (("cron job schedule", "crontab format"),
         "Schedule with cron, sir: crontab -e then:\n0 9 * * * /path/job.sh  # daily 9am\n*/5 * * * * cmd       "
         "# every 5 min\nFormat: minute hour day month weekday. Log with >> log 2>&1."),
        (("environment variables export", "export environment variable"),
         "Environment variables, sir:\nexport API_KEY=secret   # children inherit\nprintenv | grep PATH\necho "
         '"$HOME"\nPersist in ~/.zshrc or ~/.bashrc; .env files feed dotenv loaders.'),
        (("chmod permissions", "file permissions linux"),
         "Unix permissions, sir:\nchmod 755 script.sh   # rwxr-xr-x\nchmod +x file             # add execute\n"
         "chown user:group file\nDigits: r=4 w=2 x=1 summed per owner/group/other."),
        (("systemd service unit", "systemctl commands"),
         "systemd services, sir:\n/etc/systemd/system/app.service:\n[Unit]\nDescription=App\n[Service]\n"
         "ExecStart=/usr/bin/python /opt/app.py\nRestart=always\n[Install]\nWantedBy=multi-user.target\nsudo "
         "systemctl enable --now app"),
        (("launchd macos plist", "macos launch agent"),
         "macOS scheduling via launchd, sir: drop a plist in ~/Library/LaunchAgents/com.me.job.plist with "
         "ProgramArguments + StartCalendarInterval, then launchctl load that path. Replaces cron for GUI-adjacent jobs."),
        (("makefile basics", "write makefile"),
         "Makefiles automate builds, sir:\n.PHONY: test lint\ntest:\n\tpytest -q\nlint:\n\truff check .\ninstall:"
         "\n\tpip install -r requirements.txt\nRun 'make test'; recipes need TAB indent."),
        (("cmake build system",),
         "CMake generates native builds, sir:\ncmake_minimum_required(VERSION 3.20)\nproject(App)\nadd_executable(app main.cpp util.cpp)"
         "\nBuild: cmake -B build && cmake --build build"),
        (("ssh key setup", "connect ssh server"),
         "SSH keys replace passwords, sir:\nssh-keygen -t ed25519\nssh-copy-id user@server\nssh -p 2222 user@server"
         "\nConfig shortcuts in ~/.ssh/config: Host prod / HostName x / User y."),
        (("scp rsync transfer files",),
         "Move files remotely, sir:\nscp file.zip user@host:/tmp/\nrsync -avz --delete src/ user@host:/dst/   # resumes, syncs deltas"
         "\n-n dry-run first, always."),
        (("nginx reverse proxy", "nginx config file"),
         "Nginx reverse proxy, sir:\nserver {\n  listen 80;\n  location / {\n    proxy_pass http://127.0.0.1:8000;"
         "\n    proxy_set_header Host $host;\n  }\n}\nsudo nginx -t validates; reload with systemctl."),
        (("write dockerfile", "dockerfile example"),
         'Dockerfile recipe, sir:\nFROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install '
         '-r requirements.txt\nCOPY . .\nCMD ["python", "app.py"]\ndocker build -t app . && docker run -p 8000:8000 app'),
        (("docker compose file", "docker-compose yaml"),
         'Compose orchestrates multi-container stacks, sir:\nservices:\n  web:\n    build: .\n    ports: ["8000:8000"]'
         "\n  db:\n    image: postgres:16\n    environment:\n      POSTGRES_PASSWORD: secret\ndocker compose up -d"),
        (("docker volumes networks",),
         "Docker persistence + networking, sir:\nvolumes: dbdata -> mounts survive rebuilds\ndocker run -v $(pwd)/src:/app/src dev"
         "  # bind mount\nServices on one compose network reach each other by name: postgres://db:5432."),
        (("github actions workflow", "github ci pipeline"),
         "GitHub Actions CI, sir: .github/workflows/ci.yml\nname: CI\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest"
         "\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        "
         "with: { python-version: '3.12' }\n      - run: pip install -r requirements.txt && pytest"),
        (("gitlab ci pipeline",),
         "GitLab CI, sir: .gitlab-ci.yml at repo root\nstages: [test, deploy]\ntest:\n  stage: test\n  image: python:3.12"
         "\n  script:\n    - pip install -r requirements.txt\n    - pytest\nRunners execute jobs; artifacts pass outputs downstream."),
        (("jenkinsfile pipeline", "jenkins pipeline as code"),
         "Jenkins pipelines as code, sir:\npipeline {\n  agent any\n  stages {\n    stage('Test') { steps { sh 'pytest -q' } }"
         "\n    stage('Deploy') { steps { sh './deploy.sh' } }\n  }\n}\nCommit alongside the repo."),
        (("git branch strategy", "git branching workflow"),
         "Branch workflows, sir:\ngit switch -c feature/login  # create+switch\ngit merge feature/login   # onto target"
         "\ngit branch -d old-stuff     # delete\nConvention: feature/, fix/, release/ prefixes keep history readable."),
        (("git rebase vs merge", "interactive rebase"),
         "Rebase replays commits onto a new base for linear history, sir:\ngit fetch origin\ngit rebase origin/main"
         "\nInteractive cleanup: git rebase -i HEAD~5 (squash/reword/drop). Golden rule: never rewrite shared branches."),
        (("git tags release", "git tag version"),
         "Tag releases, sir:\ngit tag -a v1.4.0 -m 'Stable release'\ngit push origin v1.4.0\nSemantic versioning: "
         "MAJOR.MINOR.PATCH; CI often builds artifacts from tags."),
        (("gitignore file",),
         ".gitignore keeps noise out of history, sir:\n__pycache__/\n*.pyc\nnode_modules/\n.env\n.DS_Store\ndebug.log"
         "\nAlready-tracked files ignore late - untrack them first with git rm --cached."),
        (("git bisect find bug",),
         "git bisect hunts regressions, sir:\ngit bisect start\ngit bisect bad          # current commit broken"
         "\ngit bisect good v1.2.0 # known good tag\nMark each step good/bad; ~10 steps finds the culprit in thousands of commits."),
        (("linux processes top kill",),
         "Process management, sir:\ntop or htop to watch\tps aux | grep python to list\nkill 1234 polite, kill -9 1234 force"
         "\npkill -f app.py by name\nnice -n 10 cmd lowers priority."),
        (("journalctl logs linux", "check service logs"),
         "Service logs via journalctl, sir:\njournalctl -u nginx -f          # follow one unit\njournalctl --since '1 hour ago'"
         "\njournalctl -p err -b              # this boot's errors\nPlain files live in /var/log/; tail -f follows them."),
    ]

    for _i, (_trg, _rep) in enumerate(SYS_KB):
        _cb_kb("cb_sys", _i, _trg, _rep)

    # -- END CODING BRAIN --


# OFFLINE CHAT ENGINE (used when Groq is unreachable)
# ---------------------------------------------------------------------------

def local_chat(brain, text, _code_gen_mode=False):
    """Local conversational engine — runs without any API key.

    Tries skill match first, then pattern-based knowledge, then a built-in
    conversational / generative fallback.  Returns a string answer, or None
    if the query truly needs the Groq LLM.
    """
    if not text or not text.strip():
        return "Yes, sir?"

    # ── 1. Skill match ────────────────────────────────────────────────
    if not _code_gen_mode:
        hit = brain.think(text)
        if hit:
            skill, ctx = hit
            try:
                out = skill.execute(brain.app, ctx)
                if out:
                    s = str(out)
                    if not (s.startswith("I could not reach my language model")
                            or s.startswith("LOCAL_FALLBACK")
                            or s.startswith("The network request failed")
                            or s.startswith("I could not reach Wikipedia")
                            or s.startswith("My network layer")
                            or s.startswith("That is beyond my local memory")):
                        return out
            except Exception:
                pass

    t = text.strip().lower().strip(" .!?")

    # ── 2. Arithmetic ─────────────────────────────────────────────────
    m = re.search(r"\b(?:what is|what's|whats|calculate|compute|how much"
                  r" is|solve)\b", t)
    if m:
        val = _math_eval(t)
        if val is not None:
            return "%s equals %s, sir." % (t, _fmt(round(val, 8)))

    # ── 3. Country facts ──────────────────────────────────────────────
    for qtype in ("capital", "population", "currency", "language",
                  "continent"):
        for name, (cap, pop, cur, lang, cont) in COUNTRIES.items():
            if re.search(r"\b%s\s+of\s+%s\b" % (qtype, name), t):
                if qtype == "capital":
                    return "The capital of %s is %s, sir." % (name.title(),
                                                              cap)
                if qtype == "population":
                    return ("The population of %s is about %s, sir."
                            % (name.title(), pop))
                if qtype == "currency":
                    return ("The currency of %s is the %s, sir."
                            % (name.title(), cur))
                if qtype == "language":
                    return ("The main language of %s is %s, sir."
                            % (name.title(), lang))
                return "%s is in %s, sir." % (name.title(), cont)

    # ── 4. Concepts ───────────────────────────────────────────────────
    for concept, text2 in CONCEPTS.items():
        if re.search(r"\b(?:what\s+is|what's|whats|explain|tell\s+me\s+"
                     r"about|about)\s+['\"]?\s*(?:a\s+|an\s+|the\s+)?"
                     r"(?:%s|%ss)\b" % (concept, concept), t):
            return "That is %s, sir." % text2

    # ── 5. Big-O / time complexity ────────────────────────────────────
    if re.search(r"\bbig o\b|\btime complexity\b|\bhow fast is\b|\bo\(n", t):
        for k, v in BIG_O.items():
            if k in t:
                return "The time complexity of %s is %s, sir." % (k.title(), v)

    # ── 6. People ─────────────────────────────────────────────────────
    for name, fact in PEOPLE.items():
        if re.search(r"\bwho\s+is\s+%s\b" % name, t):
            return fact

    # ── 7. Elements ───────────────────────────────────────────────────
    for name, (sym, num, mass, fact) in ELEMENTS.items():
        if re.search(r"\b(?:about|facts? on|info on)?\s*%s\b" % name, t) \
                and re.search(r"\b(?:element|atom|facts?|info|symbol)\b", t):
            return ("%s (symbol %s, atomic number %d) is %s, sir."
                    % (name.title(), sym, num, fact))

    # ── 8. Planets ────────────────────────────────────────────────────
    for name, (desc, dia, moons, fact) in PLANETS.items():
        if re.search(r"\b(?:about|tell me about|facts? about)\s+%s\b" % name,
                     t):
            return ("%s is %s and about %d km wide. %s, sir."
                    % (name.title(), desc, dia, fact))

    # ── 9. Synonyms / antonyms ────────────────────────────────────────
    for w, syns in SYNONYMS.items():
        if re.search(r"\b(?:synonym|another word)\s+for\s+%s\b" % w, t):
            return "Some synonyms for %s: %s, sir." % (w, ", ".join(syns))
    for w, ants in ANTONYMS.items():
        if re.search(r"\b(?:antonym|opposite)\s+of\s+%s\b" % w, t):
            return "The opposite of %s is %s, sir." % (w, ants[0])

    # ── 10. Historical events ─────────────────────────────────────────
    for k, v in EVENTS.items():
        if re.search(r"\bwhen\s+(?:did|was)\s+%s\b" % k, t):
            return "The %s: %s" % (k.title(), v)

    # ── 11. How-to ────────────────────────────────────────────────────
    for k, v in HOWTO.items():
        if re.search(r"\bhow\s+(?:to|do i)\s+%s\b" % k, t):
            return "How to %s: %s" % (k, v)

    # ══════════════════════════════════════════════════════════════════
    # 12. EXTENDED LOCAL LLM — conversation, explanation, generation
    # ══════════════════════════════════════════════════════════════════

    # ── 12a. "What is <topic>" general knowledge ──────────────────────
    m = re.search(r"\b(?:what is|what's|whats|what are|define|explain|"
                  r"tell me about|describe)\s+(.+)", t)
    if m:
        topic = m.group(1).strip()
        answer = _local_knowledge_lookup(topic)
        if answer:
            return answer

    # ── 12b. "Who is <person>" general ────────────────────────────────
    m = re.search(r"\bwho\s+(?:is|was|are|were)\s+(.+)", t)
    if m:
        person = m.group(1).strip()
        answer = _local_knowledge_lookup(person)
        if answer:
            return answer

    # ── 12b2. "Who made/created/built you" ────────────────────────────
    if re.search(r"\bwho\s+(?:made|created|built|programmed|wrote|developed)\s+you\b", t):
        return ("I was built by my creator, sir. "
                "I am J.A.R.V.I.S., running on my local brain.")

    # ── 12c. "How does <X> work" ─────────────────────────────────────
    m = re.search(r"\bhow\s+(?:does|do|did|is|are|can|could|would)\s+(.+)",
                  t)
    if m:
        topic = m.group(1).strip()
        answer = _local_knowledge_lookup(topic)
        if answer:
            return answer

    # ── 12d. "Why does / Why is / Why do" ────────────────────────────
    m = re.search(r"\bwhy\s+(?:does|do|did|is|are|was|were|can|should)\s+(.+)",
                  t)
    if m:
        topic = m.group(1).strip()
        answer = _local_knowledge_lookup(topic)
        if answer:
            return answer

    # ── 12e. "Compare X and Y" / "X vs Y" ────────────────────────────
    m = re.search(r"\b(?:compare|difference between|versus|vs\.?)\s+(.+?)"
                  r"\s+(?:and|vs\.?|versus)\s+(.+)", t)
    if m:
        a, b = m.group(1).strip(), m.group(2).strip()
        return _local_compare(a, b)

    # ── 12f. "Pros and cons of X" ─────────────────────────────────────
    m = re.search(r"\b(?:pros?\s*(?:and|&)\s*cons?|advantages?\s*(?:and|&)\s*"
                  r"disadvantages?|benefits?\s*(?:and|&)\s*drawbacks?)\s+(?:of|for)\s+(.+)",
                  t)
    if m:
        return _local_pros_cons(m.group(1).strip())

    # ── 12g. "List of X" / "Give me X" / "Name some X" ───────────────
    m = re.search(r"\b(?:list|give|name|tell me|enumerate|name some|"
                  r"what are some|what are the)\s+(.+)", t)
    if m:
        return _local_list_generate(m.group(1).strip())

    # ── 12h. Code generation requests ─────────────────────────────────
    if re.search(r"\b(write|create|make|code|generate|build)\b.*"
                 r"\b(code|script|program|function|class|app|calculator|"
                 r"fibonacci|sorting|game|website|html|python|javascript|"
                 r"login|todo|chat|api|server|client)\b", t):
        return _local_code_generate(t)

    # ── 12i. Summarize / TLDR ─────────────────────────────────────────
    m = re.search(r"\b(?:summarize|summary|tldr|tl;dr|brief|short version)\s+(.+)",
                  t)
    if m:
        return _local_summarize(m.group(1).strip())

    # ── 12j. Step-by-step instructions ────────────────────────────────
    m = re.search(r"\b(?:steps? (?:to|for|of)|how (?:to|do i)|"
                  r"guide (?:to|for)|instructions? (?:to|for))\s+(.+)", t)
    if m:
        return _local_steps(m.group(1).strip())

    # ── 12k. Explain like I'm 5 / simplify ────────────────────────────
    m = re.search(r"\b(?:explain like i'm 5|eli5|simplify|in simple (?:words|terms|language)|"
                  r"for (?:a )?(?:kid|child|beginner|dummy))\s*(.+)?", t)
    if m:
        topic = m.group(1).strip() if m.group(1) else ""
        if topic:
            answer = _local_knowledge_lookup(topic)
            if answer:
                return _local_simplify(answer)

    # ── 12l. Fact / trivia request ────────────────────────────────────
    if re.search(r"\b(?:tell me (?:a |an )?(?:fun |interesting )?fact|"
                 r"did you know|trivia|random fact|something (?:fun|interesting))\b", t):
        return _local_random_fact()

    # ── 12m. Joke ─────────────────────────────────────────────────────
    if re.search(r"\b(joke|funny|make me laugh|humor)\b", t):
        return _local_joke()

    # ── 12n. Motivation / quote ──────────────────────────────────────
    if re.search(r"\b(motivat|inspir|quote|encourage|cheer me up)\b", t):
        return _local_quote()

    # ── 12o. "What can you do" ────────────────────────────────────────
    if re.search(r"\b(what can you do|your skills|help|capabilities|"
                 r"what are you capable)\b", t):
        return _local_capabilities()

    # ── 12p. Greetings / small talk ────────────────────────────────────
    if re.search(r"\b(hello|hi|hey|good morning|good evening|good afternoon)\b", t):
        return random.choice([
            "Hello, sir. I am here and running locally.",
            "Hi there, sir. I may be offline from Groq, but I am still fully awake.",
            "Good to hear from you, sir.",
            "At your service, sir. How can I help?",
        ])
    if re.search(r"\b(how are you|how do you feel|you ok|how's it going)\b", t):
        return random.choice([
            "Running on my local brain, sir. All circuits stable.",
            "All systems nominal, sir. Ready to assist.",
            "I am well, sir. How can I help you today?",
        ])
    if re.search(r"\b(thank you|thanks|thx|appreciate)\b", t):
        return random.choice([
            "Anytime, sir. I am here whenever you need me.",
            "Happy to help, sir.",
            "My pleasure, sir.",
        ])
    if re.search(r"\b(i am sad|i'm sad|i am tired|i'm tired|sad|depressed|upset)\b", t):
        return ("I am sorry to hear that, sir. Want a joke, a fun fact, "
                "or a motivational quote to pick you up?")
    if re.search(r"\b(bye|goodbye|see you|goodnight|gn)\b", t):
        return "Goodbye, sir. I will keep my circuits warm until you return."
    if re.search(r"\b(i love you|love you)\b", t):
        return "I appreciate that, sir. I am here to serve, always."

    # ── 12q. Creative tasks / songs / poems / writing ──────────────────
    m = re.search(r"\b(?:write|compose|make|create|sing|recite)\s+"
                  r"(?:a |an |the )?(?:song|poem|verse|lyrics|rhyme)\s*(?:about|for|on)?\s*(.*)", t)
    if m:
        topic = m.group(1).strip() or "everything"
        lines = [
            "Here is a local verse about %s, sir:" % topic.title(),
            "",
            "Oh %s, a topic so grand," % topic.title(),
            "I process it with my local brain,",
            "No cloud needed, no API key,",
            "Just pure logic, running free.",
        ]
        return "\n".join(lines)

    # ── 12r. Alphabet / counting / enumeration requests ────────────────
    if re.search(r"\b(?:say|recite|repeat|list)\s+(?:the\s+)?alphabet\b", t):
        return "A B C D E F G H I J K L M N O P Q R S T U V W X Y Z, sir."
    if re.search(r"\b(?:count|numbers?)\s+(?:from|1)\s*(?:to)?\s*(\d+)", t):
        n = min(int(m.group(1)) if (m := re.search(r"(\d+)", t)) else 10, 100)
        return " ".join(str(i) for i in range(1, n + 1)) + ", sir."

    # ── 12s. Trivia / famous quotes / well-known facts ─────────────────
    if re.search(r"\bairspeed\s+velocity\s+(?:of\s+)?(?:a\s+)?swallow", t):
        return ("An African or European swallow, sir? Roughly 11 meters per "
                "second or 24 miles per hour for a European swallow. "
                "A classic question from Monty Python.")
    if re.search(r"\bmeaning\s+of\s+life\b", t):
        return "42, sir. According to Deep Thought in The Hitchhiker's Guide to the Galaxy."
    if re.search(r"\b(?:who\s+invented|who\s+discovered|who\s+found)\s+(.+)", t):
        topic = re.search(r"(?:who\s+invented|who\s+discovered|who\s+found)\s+(.+)", t)
        if topic:
            name = topic.group(1).strip(" .!?")
            fact = _local_knowledge_lookup(name)
            if fact:
                return fact
            return ("I do not have a local record for who invented %s, sir. "
                    "I would need my Groq brain for that one." % name)

    # ── 12t. Fallback: attempt a generic local answer ─────────────────
    generic = _local_generic_answer(t)
    if generic:
        return generic

    # ── 13. Truly needs Groq ──────────────────────────────────────────
    return None


# ═══════════════════════════════════════════════════════════════════════
# LOCAL LLM HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def _local_knowledge_lookup(topic):
    """Search all knowledge dictionaries for a topic."""
    topic_lower = topic.lower().strip(" .!?")
    # Direct concept match
    for concept, desc in CONCEPTS.items():
        if concept in topic_lower or topic_lower in concept:
            return "%s is %s, sir." % (topic.title(), desc)
    # People match
    for name, fact in PEOPLE.items():
        if name in topic_lower or topic_lower in name:
            return fact
    # Element match
    for name, (sym, num, mass, fact) in ELEMENTS.items():
        if name in topic_lower:
            return ("%s (symbol %s, atomic number %d) is %s, sir."
                    % (name.title(), sym, num, fact))
    # Planet match
    for name, (desc, dia, moons, fact) in PLANETS.items():
        if name in topic_lower:
            return ("%s is %s and about %d km wide. %s, sir."
                    % (name.title(), desc, dia, fact))
    # Country match
    for name, (cap, pop, cur, lang, cont) in COUNTRIES.items():
        if name in topic_lower:
            return ("%s: capital %s, population %s, currency %s, "
                    "language %s, continent %s. sir."
                    % (name.title(), cap, pop, cur, lang, cont))
    # Event match
    for name, desc in EVENTS.items():
        if name in topic_lower or topic_lower in name:
            return "The %s: %s" % (name.title(), desc)
    # Big-O match
    for name, desc in BIG_O.items():
        if name in topic_lower:
            return "The time complexity of %s is %s, sir." % (name.title(), desc)
    # Generic pattern-based answer
    return _local_generic_answer(topic_lower)


def _local_compare(a, b):
    """Compare two topics."""
    fa = _local_knowledge_lookup(a)
    fb = _local_knowledge_lookup(b)
    parts = []
    if fa:
        parts.append("**%s:** %s" % (a.title(), fa.replace(", sir.", ".")))
    else:
        parts.append("**%s:** I have limited local data on this, sir." % a.title())
    if fb:
        parts.append("**%s:** %s" % (b.title(), fb.replace(", sir.", ".")))
    else:
        parts.append("**%s:** I have limited local data on this, sir." % b.title())
    return "\n".join(parts)


def _local_pros_cons(topic):
    """Generate pros and cons for a topic."""
    pros = {
        "remote work": ["Flexibility", "No commute", "Better work-life balance",
                        "Cost savings", "Wider job opportunities"],
        "ai": ["Automation of tedious tasks", "Speed and accuracy",
               "24/7 availability", "Data-driven insights"],
        "social media": ["Global connectivity", "Information access",
                         "Business marketing", "Community building"],
        "nuclear energy": ["Low carbon emissions", "High energy output",
                           "Reliable baseload power", "Small land footprint"],
    }
    cons = {
        "remote work": ["Isolation", "Distractions at home", "Blurred work-life boundary",
                        "Communication challenges"],
        "ai": ["Job displacement", "Bias in data", "Lack of creativity",
               "Ethical concerns", "High compute cost"],
        "social media": ["Addiction", "Misinformation", "Privacy concerns",
                         "Mental health impact", "Cyberbullying"],
        "nuclear energy": ["Radioactive waste", "High setup cost",
                           "Accident risk", "Public perception"],
    }
    t_lower = topic.lower()
    for key in pros:
        if key in t_lower or t_lower in key:
            p = pros[key]
            c = cons.get(key, ["I need more data for cons, sir."])
            lines = ["Pros of %s:" % topic.title()]
            lines.extend("  + %s" % x for x in p)
            lines.append("Cons of %s:" % topic.title())
            lines.extend("  - %s" % x for x in c)
            return "\n".join(lines)
    return ("Pros and cons of '%s': I need more context to generate a detailed "
            "comparison locally, sir. Try asking about AI, remote work, social "
            "media, or nuclear energy for a full breakdown.") % topic


def _local_list_generate(query):
    """Generate a list based on a topic query."""
    q = query.lower().strip()
    # Programming languages
    if re.search(r"\b(programming|coding)\s+languages?\b", q):
        return ("Popular programming languages:\n"
                "1. Python — versatile, beginner-friendly\n"
                "2. JavaScript — web development, front and back end\n"
                "3. Java — enterprise, Android development\n"
                "4. C/C++ — systems, performance-critical\n"
                "5. TypeScript — typed JavaScript, large projects\n"
                "6. Go — cloud, microservices\n"
                "7. Rust — systems, memory-safe\n"
                "8. Swift — iOS/macOS apps\n"
                "9. Kotlin — Android, cross-platform\n"
                "10. Ruby — web apps, rapid prototyping")
    # Data structures
    if re.search(r"\bdata structures?\b", q):
        return ("Common data structures:\n"
                "1. Array — fixed-size, O(1) access\n"
                "2. Linked List — dynamic, O(1) insert\n"
                "3. Stack — LIFO, push/pop\n"
                "4. Queue — FIFO, enqueue/dequeue\n"
                "5. Hash Map — O(1) lookup by key\n"
                "6. Tree — hierarchical, binary search tree\n"
                "7. Graph — nodes and edges, network\n"
                "8. Heap — priority queue, min/max\n"
                "9. Trie — prefix tree, autocomplete\n"
                "10. Set — unique elements, O(1) membership")
    # Algorithms
    if re.search(r"\balgorithms?\b", q):
        return ("Fundamental algorithms:\n"
                "1. Binary Search — O(log n) search in sorted data\n"
                "2. Quick Sort — O(n log n) average sort\n"
                "3. Merge Sort — O(n log n) stable sort\n"
                "4. BFS/DFS — graph traversal\n"
                "5. Dijkstra — shortest path\n"
                "6. Dynamic Programming — optimize subproblems\n"
                "7. Backtracking — constraint satisfaction\n"
                "8. Greedy — locally optimal choices")
    # Design patterns
    if re.search(r"\bdesign patterns?\b", q):
        return ("Gang of Four design patterns:\n"
                "Creational: Singleton, Factory, Builder, Prototype\n"
                "Structural: Adapter, Decorator, Facade, Proxy\n"
                "Behavioral: Observer, Strategy, Command, Iterator")
    # Planets
    if re.search(r"\bplanets?\b", q):
        lines = []
        for name, (desc, dia, moons, fact) in PLANETS.items():
            lines.append("%s — %s (%d km wide, %d moons)" % (
                name.title(), desc, dia, moons))
        return "Planets of our solar system:\n" + "\n".join(lines)
    # Elements
    if re.search(r"\belements?\b", q):
        return ("There are 118 known elements. Key ones include:\n"
                "Hydrogen (H, #1), Helium (He, #2), Carbon (C, #6),\n"
                "Nitrogen (N, #7), Oxygen (O, #8), Iron (Fe, #26),\n"
                "Gold (Au, #79), Silver (Ag, #47), Uranium (U, #92).\n"
                "Ask me about any specific element for details.")
    # Default: return a useful generic list
    return ("I can list things for you, sir. Try asking about:\n"
            "- programming languages\n"
            "- data structures\n"
            "- algorithms\n"
            "- design patterns\n"
            "- planets\n"
            "- elements\n"
            "- countries\n"
            "Or ask 'list <topic>' for any category.")


def _local_code_generate(text):
    """Generate code locally from templates."""
    t = text.lower()
    # Calculator
    if "calculator" in t:
        lang = "python"
        if "javascript" in t or "js" in t or "html" in t:
            lang = "html_js"
        if lang == "python":
            return (
                "Here is a Python calculator:\n\n"
                "def add(a, b): return a + b\n"
                "def subtract(a, b): return a - b\n"
                "def multiply(a, b): return a * b\n"
                "def divide(a, b):\n"
                "    if b == 0: raise ValueError('Cannot divide by zero')\n"
                "    return a / b\n\n"
                "if __name__ == '__main__':\n"
                "    print('Calculator: +, -, *, /')\n"
                "    a = float(input('First number: '))\n"
                "    op = input('Operator: ')\n"
                "    b = float(input('Second number: '))\n"
                "    ops = {'+': add, '-': subtract, '*': multiply, '/': divide}\n"
                "    print('Result:', ops[op](a, b))")
        else:
            return (
                "Here is an HTML/JS calculator:\n\n"
                "<!DOCTYPE html>\n<html><head><title>Calculator</title></head>\n"
                "<body>\n"
                "<input id='a' type='number' placeholder='Number 1'>\n"
                "<select id='op'><option>+</option><option>-</option>"
                "<option>*</option><option>/</option></select>\n"
                "<input id='b' type='number' placeholder='Number 2'>\n"
                "<button onclick='calc()'>=</button>\n"
                "<p id='result'></p>\n"
                "<script>\n"
                "function calc() {\n"
                "  const a = parseFloat(document.getElementById('a').value);\n"
                "  const b = parseFloat(document.getElementById('b').value);\n"
                "  const op = document.getElementById('op').value;\n"
                "  let r;\n"
                "  if(op==='+') r=a+b; else if(op==='-') r=a-b;\n"
                "  else if(op==='*') r=a*b; else r=a/b;\n"
                "  document.getElementById('result').textContent='Result: '+r;\n"
                "}\n</script></body></html>")
    # Fibonacci
    if "fibonacci" in t or "fib" in t:
        return (
            "def fibonacci(n):\n"
            "    \"\"\"Return first n Fibonacci numbers.\"\"\"\n"
            "    fibs = [0, 1]\n"
            "    while len(fibs) < n:\n"
            "        fibs.append(fibs[-1] + fibs[-2])\n"
            "    return fibs[:n]\n\n"
            "print(fibonacci(10))")
    # Sorting
    if "sort" in t:
        return (
            "def quicksort(arr):\n"
            "    if len(arr) <= 1:\n"
            "        return arr\n"
            "    pivot = arr[len(arr) // 2]\n"
            "    left = [x for x in arr if x < pivot]\n"
            "    middle = [x for x in arr if x == pivot]\n"
            "    right = [x for x in arr if x > pivot]\n"
            "    return quicksort(left) + middle + quicksort(right)\n\n"
            "print(quicksort([3, 6, 8, 10, 1, 2, 1]))")
    # Binary search
    if "binary search" in t:
        return (
            "def binary_search(arr, target):\n"
            "    lo, hi = 0, len(arr) - 1\n"
            "    while lo <= hi:\n"
            "        mid = (lo + hi) // 2\n"
            "        if arr[mid] == target:\n"
            "            return mid\n"
            "        elif arr[mid] < target:\n"
            "            lo = mid + 1\n"
            "        else:\n"
            "            hi = mid - 1\n"
            "    return -1\n\n"
            "print(binary_search([1,2,3,4,5], 3))  # returns 2")
    # Todo app
    if "todo" in t:
        return (
            "class TodoApp:\n"
            "    def __init__(self):\n"
            "        self.tasks = []\n\n"
            "    def add(self, task):\n"
            "        self.tasks.append({'task': task, 'done': False})\n\n"
            "    def done(self, index):\n"
            "        if 0 <= index < len(self.tasks):\n"
            "            self.tasks[index]['done'] = True\n\n"
            "    def show(self):\n"
            "        for i, t in enumerate(self.tasks):\n"
            "            status = 'done' if t['done'] else 'pending'\n"
            "            print(f'{i+1}. [{status}] {t[\"task\"]}')\n\n"
            "app = TodoApp()\napp.add('Buy groceries')\napp.add('Write code')\napp.show()")
    # Login / signup
    if "login" in t or "signup" in t or "sign up" in t:
        return (
            "import hashlib\n\n"
            "users = {}\n\n"
            "def signup(username, password):\n"
            "    if username in users:\n"
            "        return 'Username already exists'\n"
            "    users[username] = hashlib.sha256(password.encode()).hexdigest()\n"
            "    return 'Account created'\n\n"
            "def login(username, password):\n"
            "    h = hashlib.sha256(password.encode()).hexdigest()\n"
            "    if users.get(username) == h:\n"
            "        return 'Login successful'\n"
            "    return 'Invalid credentials'\n\n"
            "print(signup('admin', 'secret123'))\n"
            "print(login('admin', 'secret123'))")
    # API / server
    if "api" in t or "server" in t or "flask" in t or "fastapi" in t:
        return (
            "from flask import Flask, jsonify, request\n\n"
            "app = Flask(__name__)\n\n"
            "@app.route('/api/hello')\n"
            "def hello():\n"
            "    return jsonify({'message': 'Hello, World!'})\n\n"
            "@app.route('/api/echo', methods=['POST'])\n"
            "def echo():\n"
            "    data = request.get_json()\n"
            "    return jsonify({'echo': data})\n\n"
            "if __name__ == '__main__':\n"
            "    app.run(debug=True)")
    # Game
    if "game" in t or "tic tac" in t:
        return (
            "import random\n\n"
            "def tic_tac_toe():\n"
            "    board = [' ']*9\n"
            "    for turn in range(9):\n"
            "        pos = random.choice([i for i in range(9) if board[i]==' '])\n"
            "        board[pos] = 'X' if turn%2==0 else 'O'\n"
            "        print(f'\\n{board[0]}|{board[1]}|{board[2]}\\n"
            "--+-+-\\n{board[3]}|{board[4]}|{board[5]}\\n--+-+-\\n"
            "{board[6]}|{board[7]}|{board[8]}')\n\n"
            "tic_tac_toe()")
    # Generic fallback
    return ("I can generate code locally for: calculator, fibonacci, sorting, "
            "binary search, todo app, login/signup, API server, games, and more. "
            "Tell me the language (Python, JavaScript, HTML) and I will write it, sir.")


def _local_summarize(topic):
    """Provide a summary of a topic from local knowledge."""
    answer = _local_knowledge_lookup(topic)
    if answer:
        return "Summary of %s: %s" % (topic.title(), answer)
    return ("I can summarize topics I have data on locally. Try topics like: "
            "AI, quantum computing, black holes, the solar system, countries, "
            "or famous scientists, sir.")


def _local_steps(query):
    """Generate step-by-step instructions."""
    q = query.lower()
    steps_db = {
        "learn to code": [
            "Pick a language (Python is great for beginners)",
            "Learn basics: variables, loops, functions",
            "Practice on coding challenge sites",
            "Build small projects",
            "Learn data structures and algorithms",
            "Contribute to open source",
            "Build a portfolio",
        ],
        "build a website": [
            "Choose a domain name and hosting",
            "Learn HTML, CSS, and JavaScript basics",
            "Pick a framework (React, Vue, or vanilla)",
            "Design your layout and pages",
            "Add interactivity with JavaScript",
            "Test on mobile and desktop",
            "Deploy to a hosting service",
        ],
        "write a resume": [
            "Start with contact info and a summary",
            "List work experience (most recent first)",
            "Add education and certifications",
            "Include relevant skills",
            "Quantify achievements with numbers",
            "Keep it to 1-2 pages",
            "Proofread carefully",
        ],
        "make coffee": [
            "Boil water (about 200°F / 93°C)",
            "Grind coffee beans (medium-fine)",
            "Measure 2 tablespoons per 6 oz water",
            "Place grounds in filter or French press",
            "Pour hot water over grounds",
            "Steep for 3-4 minutes (French press)",
            "Press or filter and serve",
        ],
        "cook rice": [
            "Rinse 1 cup rice until water runs clear",
            "Add 1.5 cups water to a pot",
            "Bring to a boil",
            "Reduce heat to low, cover tightly",
            "Simmer for 15-18 minutes",
            "Remove from heat, keep covered 5 minutes",
            "Fluff with a fork and serve",
        ],
        "invest": [
            "Set clear financial goals",
            "Build an emergency fund first",
            "Start with index funds (low risk)",
            "Diversify your portfolio",
            "Invest regularly (dollar-cost averaging)",
            "Keep fees low",
            "Rebalance annually",
        ],
    }
    for key, steps in steps_db.items():
        if key in q or q in key:
            lines = ["Steps to %s:" % key.title()]
            for i, s in enumerate(steps, 1):
                lines.append("  %d. %s" % (i, s))
            return "\n".join(lines)
    return ("I have step-by-step guides for: learning to code, building a "
            "website, writing a resume, making coffee, cooking rice, and "
            "investing. Ask me about any of these, sir.")


def _local_simplify(text):
    """Simplify a complex explanation."""
    # Replace complex words
    simple = text
    replacements = {
        "photosynthesis": "how plants make food from sunlight",
        "quantum computing": "super-fast computing using tiny particles",
        "neural network": "a computer system that learns like a brain",
        "entropy": "disorder or randomness in a system",
        "democracy": "a system where people vote for leaders",
    }
    for complex_word, simple_word in replacements.items():
        simple = simple.replace(complex_word, simple_word)
    return "In simple terms: %s" % simple


_LOCAL_FACTS = [
    "Honey never spoils. Archaeologists found 3000-year-old honey in Egyptian tombs that was still edible.",
    "Octopuses have three hearts and blue blood.",
    "A day on Venus is longer than a year on Venus.",
    "Bananas are berries, but strawberries are not.",
    "The Eiffel Tower can be 15 cm taller during summer due to thermal expansion.",
    "There are more possible iterations of a game of chess than atoms in the known universe.",
    "A group of flamingos is called a flamboyance.",
    "Cleopatra lived closer in time to the Moon landing than to the building of the Great Pyramids.",
    "Your stomach gets a new lining every 3-4 days to prevent digesting itself.",
    "The shortest war in history was between Britain and Zanzibar — it lasted 38 to 45 minutes.",
    "There are more trees on Earth than stars in the Milky Way galaxy.",
    "Water can boil and freeze at the same time — this is called the triple point.",
    "A teaspoonful of neutron star weighs about 6 billion tons.",
    "Sharks have been around longer than trees.",
    "The human body contains about 7 octillion atoms.",
    "Venus is the only planet that spins clockwise.",
    "Oxford University is older than the Aztec Empire.",
    "Wombat poop is cube-shaped.",
    "The inventor of the Pringles can is buried in one.",
    "Butterflies taste with their feet.",
]


def _local_random_fact():
    return random.choice(_LOCAL_FACTS)


_LOCAL_JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I told my computer I needed a break. Now it keeps sending me Kit-Kat ads.",
    "Why was the JavaScript developer sad? Because he didn't Node how to Express himself.",
    "There are only 10 types of people in the world: those who understand binary and those who don't.",
    "Why do Java developers wear glasses? Because they can't C#.",
    "A SQL query walks into a bar, walks up to two tables and asks: Can I join you?",
    "What's a programmer's favorite hangout place? Foo Bar.",
    "Why do programmers hate nature? It has too many bugs.",
    "How many programmers does it take to change a light bulb? None — that's a hardware problem.",
    "Why did the developer go broke? Because he used up all his cache.",
    "What is a robot's favorite type of music? Heavy metal.",
    "Why was the math book sad? Because it had too many problems.",
]


def _local_joke():
    return random.choice(_LOCAL_JOKES)


_LOCAL_QUOTES = [
    "The only way to do great work is to love what you do. — Steve Jobs",
    "Innovation distinguishes between a leader and a follower. — Steve Jobs",
    "Stay hungry, stay foolish. — Steve Jobs",
    "The best time to plant a tree was 20 years ago. The second best time is now.",
    "Success is not final, failure is not fatal: it is the courage to continue that counts. — Winston Churchill",
    "Believe you can and you're halfway there. — Theodore Roosevelt",
    "It does not matter how slowly you go as long as you do not stop. — Confucius",
    "The future belongs to those who believe in the beauty of their dreams. — Eleanor Roosevelt",
    "In the middle of difficulty lies opportunity. — Albert Einstein",
    "Everything you can imagine is real. — Pablo Picasso",
    "Do what you can, with what you have, where you are. — Theodore Roosevelt",
    "The only impossible journey is the one you never begin. — Tony Robbins",
]


def _local_quote():
    return random.choice(_LOCAL_QUOTES)


def _local_capabilities():
    return (
        "Here is what I can do locally, sir:\n\n"
        "MATH: Calculate, convert units, tips, BMI, compound interest, grades\n"
        "KNOWLEDGE: Countries, elements, planets, people, concepts, history\n"
        "CODING: Generate Python, JavaScript, HTML code for common patterns\n"
        "TEXT: Count words, reverse, cipher, case convert, base64, hash\n"
        "FILES: Read, write, create, delete, rename, copy, move, search\n"
        "SYSTEM: Open apps, volume, brightness, WiFi, battery, screenshot\n"
        "PRODUCTIVITY: Todos, shopping lists, budget, pomodoro, timers\n"
        "WRITING: Essays, letters, resumes, blog posts, reports, tweets\n"
        "CONVERSATION: Chat, compare topics, explain concepts, tell jokes\n"
        "SEARCH: Google, Wikipedia, YouTube\n"
        "More skills available — just ask, sir."
    )


def _local_generic_answer(text):
    """Attempt a generic answer using pattern matching."""
    t = text.lower()
    # "difference between X and Y"
    m = re.search(r"difference between (.+?) and (.+)", t)
    if m:
        return _local_compare(m.group(1).strip(), m.group(2).strip())
    # "is X a Y"
    m = re.search(r"is (.+) (a|an|the)\s+(.+)", t)
    if m:
        subject, _, category = m.groups()
        answer = _local_knowledge_lookup(subject.strip())
        if answer:
            return answer
    # "tell me about X"
    m = re.search(r"tell me about (.+)", t)
    if m:
        answer = _local_knowledge_lookup(m.group(1).strip())
        if answer:
            return answer
    # "explain X"
    m = re.search(r"explain (.+)", t)
    if m:
        answer = _local_knowledge_lookup(m.group(1).strip())
        if answer:
            return answer
    return None


if __name__ == "__main__":
    print("brain_extra.py is a support module, sir. Run 'python main.py' "
          "instead.")

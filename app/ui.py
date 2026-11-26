"""Telegram xabarlari uchun dizayn elementlari.

Bu yerda Telegramning rasmiy "Animated Emoji" to'plamidagi
(``t.me/addemoji/RestrictedEmoji``) animatsiyali custom emoji ID'lari
saqlanadi. Har bir ID ``getStickerSet("RestrictedEmoji")`` orqali olingan
va ``getCustomEmojiStickers`` bilan tekshirilgan (``python -m app.check_emoji``).

Muhim: Telegram qoidasiga ko'ra bot custom emoji yubora olishi uchun
bot egasining (BotFather'dagi akkaunt) Telegram Premium obunasi bo'lishi
kerak. Aks holda Telegram xabarni rad etmaydi, balki oddiy emoji
(fallback) ko'rsatiladi — shuning uchun har bir emoji uchun fallback bor.
"""

from __future__ import annotations

from html import escape


# ================================================================
# ANIMATSIYALI EMOJI REESTRI: kalit -> (custom_emoji_id, fallback)
# ================================================================

EMOJI: dict[str, tuple[str, str]] = {
    # Bayram
    "cake": ("5370999492914976897", "🎂"),
    "cupcake": ("5372907046804920585", "🧁"),
    "party": ("5436040291507247633", "🎉"),
    "confetti": ("5435933711893797296", "🎊"),
    "gift": ("5199749070830197566", "🎁"),
    "balloon": ("5472091323571903308", "🎈"),
    "partying_face": ("5370870691140737817", "🥳"),
    "fireworks": ("5431783411981228752", "🎆"),
    "sparkler": ("5431585985219534209", "🎇"),
    "candle": ("5350571717922167592", "🕯"),
    "champagne": ("5370900768796711127", "🍾"),
    "ribbon": ("5375152498656961898", "🎀"),
    # Yorqinlik
    "sparkles": ("5472164874886846699", "✨"),
    "star": ("5435957248314579621", "⭐️"),
    "glowing_star": ("5458799228719472718", "🌟"),
    "dizzy": ("5469741319330996757", "💫"),
    "crown": ("5467406098367521267", "👑"),
    "trophy": ("5409008750893734809", "🏆"),
    "medal": ("5280735858926822987", "🥇"),
    "gem": ("5471952986970267163", "💎"),
    "rainbow": ("5427042798878610107", "🌈"),
    "clover": ("5395325195542078574", "🍀"),
    "sun": ("5469947168523558652", "☀️"),
    # Gullar va mehr
    "bouquet": ("5190661263629243818", "💐"),
    "blossom": ("5440354006335495210", "🌸"),
    "rose": ("5440911110838425969", "🌹"),
    "tulip": ("5404835520150773707", "🌷"),
    "heart": ("5449505950283078474", "❤️"),
    "yellow_heart": ("5449366943666543715", "💛"),
    "sparkling_heart": ("5465540480538254161", "💖"),
    "heart_gift": ("5465263910414195580", "💝"),
    "love_letter": ("5472019095106886003", "💌"),
    "heart_hands": ("5357107687484038897", "🫶"),
    "pray": ("5472189549473963781", "🙏"),
    "palms_up": ("5471895949804575096", "🤲"),
    "dove": ("5434121252874756456", "🕊"),
    # Musiqa va media
    "music": ("5188621441926438751", "🎵"),
    "notes": ("5188705588925702510", "🎶"),
    "picture": ("5375074927252621134", "🖼"),
    # Interfeys
    "wave": ("5472055112702629499", "👋"),
    "robot": ("5372981976804366741", "🤖"),
    "family": ("5386539642369614675", "👨‍👩‍👧‍👦"),
    "person": ("5373012449597335010", "👤"),
    "people": ("5372926953978341366", "👥"),
    "house": ("5465226866321268133", "🏠"),
    "calendar": ("5431897022456145283", "📆"),
    "hourglass": ("5451732530048802485", "⏳"),
    "alarm": ("5413704112220949842", "⏰"),
    "globe": ("5399898266265475100", "🌍"),
    "check": ("5427009714745517609", "✅"),
    "cross": ("5465665476971471368", "❌"),
    "warning": ("5467928559664242360", "❗️"),
    "lock": ("5472308992514464048", "🔐"),
    "key": ("5330115548900501467", "🔑"),
    "plus": ("5226945370684140473", "➕"),
    "pencil": ("5334673106202010226", "✏️"),
    "memo": ("5334882760735598374", "📝"),
    "chart": ("5431577498364158238", "📊"),
    "search": ("5188311512791393083", "🔎"),
    "mailbox": ("5352896944496728039", "📭"),
    "bell": ("5242628160297641831", "🔔"),
    "megaphone": ("5469903029144657419", "📣"),
    "rocket": ("5445284980978621387", "🚀"),
    "bulb": ("5472146462362048818", "💡"),
    "target": ("5350460637182993292", "🎯"),
    "folder": ("5433653135799228968", "📁"),
    "chat": ("5465300082628763143", "💬"),
    "fire": ("5420315771991497307", "🔥"),
    "hundred": ("5188208446461188962", "💯"),
    "clap": ("5471921242866981303", "👏"),
    "handshake": ("5357080225463149588", "🤝"),
    "teddy": ("5397915559037785261", "🧸"),
}


def e(key: str) -> str:
    """Animatsiyali emoji uchun ``<tg-emoji>`` HTML tegini qaytaradi."""

    emoji_id, fallback = EMOJI[key]
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


def plain(key: str) -> str:
    """Faqat oddiy emoji (masalan, tugma yoki log matni uchun)."""

    return EMOJI[key][1]


# ================================================================
# MATN BEZAKLARI
# ================================================================

DIVIDER = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"


def safe(value: object) -> str:
    """Foydalanuvchi matnini HTML uchun xavfsiz qiladi."""

    return escape(str(value), quote=False)


def title(emoji_key: str, text: str) -> str:
    return f"{e(emoji_key)} <b>{safe(text)}</b>"


def row(emoji_key: str, label: str, value: str) -> str:
    """``emoji Label: value`` ko'rinishidagi qator (value HTML bo'lishi mumkin)."""

    return f"{e(emoji_key)} {safe(label)}: {value}"


def card(header: str, *sections: str) -> str:
    """Sarlavha va bo'limlardan iborat chiroyli xabar kartasi."""

    parts = [header]

    for section in sections:
        if section:
            parts.append(section)

    return "\n\n".join(parts)


def quote(text: str, expandable: bool = False) -> str:
    tag = "blockquote expandable" if expandable else "blockquote"
    return f"<{tag}>{text}</blockquote>"


def hint(text: str) -> str:
    return f"<i>{text}</i>"


def plural_days(days: int) -> str:
    if days == 0:
        return "bugun"

    if days == 1:
        return "ertaga"

    return f"{days} kundan so'ng"

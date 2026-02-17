"""
Offline translation using Argos Translate.

Supports: English <-> Hindi, English <-> Japanese
Language packs must be pre-installed using setup_languages.py.

Uses argostranslate.translate.translate() — the simplest, most
version-proof API that works across all Argos versions.
"""

import logging

import config

logger = logging.getLogger(__name__)


def translate_text(text: str, from_lang: str, to_lang: str) -> str:
    """
    Translate text from one language to another.

    Args:
        text: Source text to translate
        from_lang: Source language code ("en", "ja", "hi")
        to_lang: Target language code ("en", "ja", "hi")

    Returns:
        Translated text string
    """
    if not text or not text.strip():
        return ""

    if from_lang == to_lang:
        return text

    try:
        # This is the simplest Argos API — works across all versions
        import argostranslate.translate
        result = argostranslate.translate.translate(text.strip(), from_lang, to_lang)

        logger.debug(
            f"Translate [{from_lang}->{to_lang}]: "
            f"\"{text[:50]}\" -> \"{result[:50]}\""
        )

        return result

    except Exception as e:
        logger.error(f"Translation error ({from_lang}->{to_lang}): {e}")
        return f"[Translation error: {text}]"


def verify_pairs():
    """Verify that all required translation pairs are installed."""
    required_pairs = set()

    if config.ENABLE_MIC_CHANNEL:
        required_pairs.add((config.MIC_SOURCE_LANG, config.MIC_TARGET_LANG))
    if config.ENABLE_LOOPBACK_CHANNEL:
        required_pairs.add((config.LOOPBACK_SOURCE_LANG, config.LOOPBACK_TARGET_LANG))

    all_ok = True
    for from_code, to_code in required_pairs:
        if from_code == to_code:
            continue
        try:
            # Test translate with a short string
            import argostranslate.translate
            test_result = argostranslate.translate.translate("hello", from_code, to_code)

            if test_result and test_result != "hello":
                print(f"  Translation pair OK: {from_code} -> {to_code} (test: 'hello' -> '{test_result}')")
            else:
                # It returned the same text — might not actually be translating
                # Check if packages are installed
                import argostranslate.package
                installed = argostranslate.package.get_installed_packages()
                found = any(
                    p.from_code == from_code and p.to_code == to_code
                    for p in installed
                )
                if found:
                    print(f"  Translation pair OK: {from_code} -> {to_code} (package installed)")
                else:
                    print(f"  Translation pair MISSING: {from_code} -> {to_code}")
                    print(f"    Installed packages: {[(p.from_code, p.to_code) for p in installed]}")
                    all_ok = False

        except Exception as e:
            print(f"  Translation pair ERROR: {from_code} -> {to_code} — {e}")
            all_ok = False

    return all_ok

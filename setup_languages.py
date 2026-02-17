"""
Downloads Argos Translate language packs for offline translation.
Run this once before using the translator.

Supported pairs: en<->hi, en<->ja
"""

import argostranslate.package
import argostranslate.translate


LANGUAGE_PAIRS = [
    ("en", "hi"),
    ("hi", "en"),
    ("en", "ja"),
    ("ja", "en"),
]


def setup():
    print("=" * 60)
    print("Argos Translate — Downloading Offline Language Packs")
    print("=" * 60)

    print("\n[1/2] Updating package index...")
    argostranslate.package.update_package_index()
    available_packages = argostranslate.package.get_available_packages()

    print(f"\n[2/2] Installing {len(LANGUAGE_PAIRS)} language pairs...\n")

    for from_code, to_code in LANGUAGE_PAIRS:
        pair_name = f"{from_code} -> {to_code}"

        matching = [
            p for p in available_packages
            if p.from_code == from_code and p.to_code == to_code
        ]

        if not matching:
            print(f"  WARNING: No package found for {pair_name}")
            continue

        pkg = matching[0]
        print(f"  Installing {pair_name}...", end=" ", flush=True)

        try:
            download_path = pkg.download()
            argostranslate.package.install_from_path(download_path)
            print("OK")
        except Exception as e:
            print(f"FAILED: {e}")

    # Verify using installed packages (most reliable method)
    print("\n" + "=" * 60)
    print("Installed language packages:")
    installed_packages = argostranslate.package.get_installed_packages()
    for pkg in installed_packages:
        print(f"  {pkg.from_code} -> {pkg.to_code}")

    # Quick translation test
    print("\nQuick test:")
    for from_code, to_code in LANGUAGE_PAIRS:
        try:
            result = argostranslate.translate.translate("hello", from_code, to_code)
            print(f"  {from_code}->{to_code}: 'hello' -> '{result}'")
        except Exception as e:
            print(f"  {from_code}->{to_code}: FAILED — {e}")

    print("\nDone! You can now run the translator offline.")


if __name__ == "__main__":
    setup()

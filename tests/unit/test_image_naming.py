from __future__ import annotations

from core.image_naming import build_image_filename, guess_extension, sanitize_title


def test_sanitize_title_matches_spreadsheet_owners_example():
    # Spec example: "SDVoE ( 1 0 G )" -> "Sdvoe_(_1_0_G_)"
    assert sanitize_title("SDVoE ( 1 0 G )") == "Sdvoe_(_1_0_G_)"


def test_sanitize_title_strips_illegal_windows_filename_characters():
    # ':' isn't a legal Windows filename character; str.capitalize() also
    # lowercases everything after each word's first letter, matching the
    # spec ("SDVoE" -> "Sdvoe" above).
    assert sanitize_title("Extron:Pro Series") == "Extron_pro_Series"


def test_sanitize_title_falls_back_to_image_when_blank():
    assert sanitize_title("   ") == "image"


def test_guess_extension_prefers_url_suffix():
    assert guess_extension("https://example.com/a/photo.PNG?v=2") == ".png"


def test_guess_extension_falls_back_to_content_type_then_default():
    assert guess_extension("https://example.com/a/photo", content_type="image/webp") == ".webp"
    assert guess_extension("https://example.com/a/photo") == ".jpg"


def test_build_image_filename_first_image_has_no_suffix():
    name = build_image_filename("SDVoE ( 1 0 G )", 0, "https://example.com/x.jpg")
    assert name == "Sdvoe_(_1_0_G_).jpg"


def test_build_image_filename_subsequent_images_get_windows_style_suffix():
    name = build_image_filename("SDVoE ( 1 0 G )", 1, "https://example.com/x.jpg")
    assert name == "Sdvoe_(_1_0_G_)_(1).jpg"

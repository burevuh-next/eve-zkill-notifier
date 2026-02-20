from src.image_generator_large import LargeKillImageGenerator

def test_format_isk():
    gen = LargeKillImageGenerator()
    assert gen.format_isk(1_500_000) == "1.5M"
    assert gen.format_isk(2_300_000_000) == "2.30B"
    assert gen.format_isk(999) == "999"

def test_calculate_card_width():
    gen = LargeKillImageGenerator()
    gen.load_fonts()
    width = gen.calculate_card_width("VeryLongName", "VeryLongCorpName",
                                     gen.font_medium, gen.font_small)
    assert 250 <= width <= 400
from pipeline.downloader import vtt_to_text

ROLLING_VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000 align:start position:0%
add<00:00:00.500><c> two</c><00:00:01.000><c> cloves</c>

00:00:02.000 --> 00:00:02.010 align:start position:0%
add two cloves

00:00:02.010 --> 00:00:04.000 align:start position:0%
add two cloves
of garlic &amp; butter
"""


def test_vtt_to_text_dedupes_rolling_captions():
    assert vtt_to_text(ROLLING_VTT) == "add two cloves of garlic & butter"

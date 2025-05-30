from hwbench.environment.oui import OUI

ouidb = OUI()


class TestOui:
    def test_hex_to_manufcaturer(self):
        assert ouidb.hex_to_manufacturer("FCFFAA") == "IEEE Registration Authority"

    def test_wwn_oui_manufacturer(self):
        wwns = {
            "eui.001b448b48079c11": "SanDisk Corporation",
            "eui.000000000000000100a075244ca80119": "MICRON TECHNOLOGY, INC.",
            "eui.000000000000000100a075244ca800f9": "MICRON TECHNOLOGY, INC.",
            "eui.01000000000000008ce38ee306207dd3": "Kioxia Corporation",
            "eui.2ae0aa97f0000510ace42e0025000333": "SK hynix",
            "eui.01000000000000008ce38ee3062081a2": "Kioxia Corporation",
            "eui.2ae0aa97f0000510ace42e0025000230": "SK hynix",
            "0x5000c500e9be0d1f": "Seagate Technology",
            "0x5000c500e9be01b8": "Seagate Technology",
            "0x5000cca2f7c11e28": "HGST a Western Digital Company",
            "0x5000cca405da3a83": "HGST a Western Digital Company",
            "0x5000039d78d8e7c9": "TOSHIBA CORPORATION",
            "0x5000039d78d8e7ca": "TOSHIBA CORPORATION",
        }
        for wwn in wwns:
            oui = ouidb.wwn_to_oui(wwn)
            assert wwns[wwn] == ouidb.hex_to_manufacturer(oui)

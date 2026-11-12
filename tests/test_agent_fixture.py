import struct
import unittest

from swg_test_studio import agent_fixture as af
from swg_test_studio import model

BOT = {"player": "123456789", "station": "4242", "character": "Capabcdefghijkl"}


def bitwise_crc(text):
    """Independent MSB-first CRC-32 (poly 0x04C11DB7, init/xorout 0xFFFFFFFF), no table."""
    value = 0xFFFFFFFF
    for byte in text.encode("latin-1"):
        value ^= byte << 24
        for _ in range(8):
            value = ((value << 1) ^ 0x04C11DB7) if value & 0x80000000 else (value << 1)
            value &= 0xFFFFFFFF
    return value ^ 0xFFFFFFFF


def suite(steps):
    return {"format": "swg-test-studio", "schema_version": 1, "id": "arrange_probe", "title": "Arrange probe",
            "category": "regression", "roles": ["actor"], "steps": steps,
            "review": {"approved": True, "recording": None, "unsupported": []}}


class FramingTests(unittest.TestCase):
    def test_crc_matches_independent_implementation(self):
        for text in ("", "a", "ConGenericMessage", "ExecuteConsoleCommand"):
            self.assertEqual(af.crc(text), bitwise_crc(text))

    def test_pack_layout_and_round_trip(self):
        frame = af.pack("game 1 runScript fixture.agent_fixture inspect x", msg_id=7)
        (size,) = struct.unpack_from("<i", frame)
        self.assertEqual(size, len(frame) - 4)
        count, kind, length = struct.unpack_from("<HIH", frame, 4)
        self.assertEqual((count, kind), (3, af.crc("ConGenericMessage")))
        self.assertEqual(struct.unpack_from("<I", frame, 4 + 8 + length)[0], 7)
        self.assertEqual(af.unpack(frame[4:]), "game 1 runScript fixture.agent_fixture inspect x")

    def test_unpack_ignores_other_messages(self):
        other = struct.pack("<HIH", 3, af.crc("SomethingElse"), 2) + b"hi" + struct.pack("<I", 1)
        self.assertIsNone(af.unpack(other))

    def test_send_skips_keepalive_and_reads_reply(self):
        reply = af.pack("agent_fixture=ok scene=tatooine")

        class Conn:
            def __init__(self):
                self.data, self.sent = struct.pack("<i", 0) + reply, b""

            def sendall(self, b):
                self.sent += b

            def recv(self, n):
                out, self.data = self.data[:n], self.data[n:]
                return out

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        conn = Conn()
        text = af.send("172.18.0.5", "game 1 x", connect=lambda addr, timeout: conn)
        self.assertEqual(text, "agent_fixture=ok scene=tatooine")
        self.assertEqual(af.unpack(conn.sent[4:]), "game 1 x")

    def test_public_console_refused(self):
        for host in ("8.8.8.8", "::1", "2001:db8::1"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                af.private_address(host)
        self.assertEqual(af.private_address("10.1.2.3"), "10.1.2.3")


class CommandTests(unittest.TestCase):
    def test_exact_typed_line(self):
        line = af.command(3, BOT, "place", ["987654321", "r2", "1.5", "0", "-2.25", "90"])
        self.assertEqual(line, "game 3 runScript fixture.agent_fixture place "
                               "123456789:4242:Capabcdefghijkl 987654321 r2 1.5 0 -2.25 90")

    def test_refusals(self):
        bad = [
            (3, BOT, "exec", ["/setGod 50"]),                      # not a fixture method
            (3, BOT, "place", ["1", "r2", "0", "0", "0"]),          # missing yaw
            (3, BOT, "warp", ["1", "2", "3;game"]),                 # injection in a number
            (3, BOT, "grantSkills", ["a b"]),                       # space would split the console line
            (3, BOT, "describe", ["0"]),                            # not a valid oid
            (0, BOT, "inspect", []),                                # bad server id
            (3, dict(BOT, character="Someplayer"), "inspect", []),    # not a fixture bot name
            (3, BOT, "scale", ["1", "25"]),                         # beyond the fixture's 0.05..20
            (3, BOT, "transform", ["1", "0", "0", "400"]),          # yaw beyond 360
            (3, BOT, "itemBonuses", ["1", "luck=20000"]),           # bonus beyond 10000
            (3, BOT, "warp", ["123456", "0", "0"]),                 # more digits than the fixture parses
        ]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(ValueError):
                af.command(*args)

    def test_optional_argument(self):
        self.assertTrue(af.command(1, BOT, "grantExpertise", []).endswith("Capabcdefghijkl"))
        self.assertTrue(af.command(1, BOT, "grantExpertise", ["3,7"]).endswith(" 3,7"))

    def test_parse_and_check(self):
        reply = af.parse("agent_fixture=ok building=55 cell=r2 row=1:a row=2:b\nignored")
        self.assertEqual(reply["fields"], {"building": "55", "cell": "r2"})
        self.assertEqual(reply["rows"], ["1:a", "2:b"])
        self.assertIsNone(af.check(reply, {"cell": "r2"}))
        self.assertIn("expected", af.check(reply, {"cell": "r3"}))
        self.assertEqual(af.check(af.parse("agent_fixture=out-of-scope"), {}), "fixture status out-of-scope")
        self.assertEqual(af.parse("protocol_bot=ok")["status"], "unrecognized")


class InstallTests(unittest.TestCase):
    def test_reload_line_is_typed(self):
        self.assertEqual(af.reload_command(4), "game 4 reloadScript fixture.agent_fixture")
        with self.assertRaises(ValueError):
            af.reload_command("4; game 1 runScript x")

    def test_class_release_from_major_version(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"\xca\xfe\xba\xbe\x00\x00\x00\x34")
        try:
            self.assertEqual(af.class_release(f.name), "8")
        finally:
            os.unlink(f.name)

    def test_workers_from_central_log(self):
        log = "x\nAdding server 7 for scene tatooine\nAdding server 9 for scene naboo\nAdding server 7 for scene tatooine\n"
        self.assertEqual(af.fixture_workers("p", lambda argv: log), [7, 9])
        with self.assertRaises(RuntimeError):
            af.fixture_workers("p", lambda argv: "nothing")


class ModelTests(unittest.TestCase):
    def step(self, **options):
        return {"id": "arrange", "action": "agent_fixture",
                "options": dict({"role": "actor", "op": "inspect", "args": []}, **options)}

    def test_step_validates_and_compiles(self):
        data = suite([{"id": "login", "action": "session", "options": {"role": "actor"}},
                      self.step(op="place", args=["5", "r1", "0", "0", "0", "180"], expect={"cell": "r1"})])
        model.validate(data, runnable=True)
        from pathlib import Path
        manifest = model.compile_suite(data, Path("."))
        self.assertEqual([c["kind"] for c in manifest["tests"]], ["protocol_session", "agent_fixture"])

    def test_step_refusals(self):
        for options in ({"op": "exec", "args": ["x"]}, {"role": "ghost"}, {"expect": {"cell": "a b"}},
                        {"args": "inspect"}, {"extra": 1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                model.validate(suite([self.step(**options)]), runnable=True)


if __name__ == "__main__":
    unittest.main()

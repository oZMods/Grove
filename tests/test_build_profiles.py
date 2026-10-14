import unittest
from grove.clients.osrs import ClientState,PROFILES,BUILD,BASELINE_BUILD

class BuildProfileTests(unittest.TestCase):
    def test_current_profile_moves_only_reviewed_fields(self):
        reader=ClientState.__new__(ClientState)
        reader.profile=PROFILES[BUILD]
        self.assertEqual(reader.s(1000,13352),1000+13336)
        self.assertEqual(reader.s(1000,4275176),1000+4275160)
        self.assertEqual(reader.s(1000,144),1144)
        self.assertEqual(reader.s(1000,8544),9544)
        self.assertEqual(reader.fingerprint(0x38EE0),0x38EF0)
        self.assertEqual(reader.fingerprint(0x6D16D0),0x6D15E0)

    def test_old_profile_preserves_its_original_layout(self):
        reader=ClientState.__new__(ClientState)
        reader.profile=PROFILES[BASELINE_BUILD]
        self.assertEqual(reader.s(1000,13352),14352)
        self.assertEqual(reader.fingerprint(0x38EE0),0x38EE0)

    def test_profiles_do_not_accept_unknown_hash(self):
        self.assertNotIn('0'*64,PROFILES)

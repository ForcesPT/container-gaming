import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
import sys
sys.modules["packages"] = SourceFileLoader("packages", str(Path(__file__).with_name("dpad-stock595-codecs.py"))).load_module()
sys.modules["apt_hook"] = SourceFileLoader("apt_hook", str(Path(__file__).with_name("dpad-stock595-apt-hook.py"))).load_module()
from packages import select_version, validate_plan, choose_missing
from apt_hook import validate_debs

class PackageChecks(unittest.TestCase):
    def test_exact_driver_not_latest(self):
        self.assertEqual(select_version('595.58.03', ['600.1-1', '595.58.03-1ubuntu1']), '595.58.03-1ubuntu1')
    def test_epoch(self):
        with self.assertRaises(ValueError): select_version('595.58.03', ['1:595.58.03-1ubuntu1'])
    def test_bad_driver(self):
        for v in ['580.1', '595', '595.1;id', '595.1\n600.1']:
            with self.subTest(v=v), self.assertRaises(ValueError): select_version(v, ['595.1-1'])
    def test_missing_or_ambiguous_version(self):
        for versions in [[], ['595.58.030-1'], ['595.58.03-1ubuntu1', '595.58.03-2']]:
            with self.subTest(versions=versions), self.assertRaises(ValueError): select_version('595.58.03', versions)
    def test_missing_packages(self):
        chosen = {'libnvidia-encode': '595.58.03-1ubuntu1', 'libnvidia-decode': '595.58.03-1ubuntu1'}
        self.assertEqual(choose_missing(chosen, {}), chosen)
        self.assertEqual(choose_missing(chosen, chosen), {})
        self.assertEqual(choose_missing(chosen, {'libnvidia-encode': '595.58.03-1ubuntu1'}), {'libnvidia-decode': '595.58.03-1ubuntu1'})
        with self.assertRaises(ValueError): choose_missing(chosen, {'libnvidia-encode': '580.1-1'})
    def plan(self):
        return ('Inst libnvidia-encode (595.58.03-1ubuntu1 repo [amd64])\n'
                'Inst libnvidia-decode:amd64 (595.58.03-1ubuntu1 repo [amd64])\n'
                'Conf libnvidia-encode (595.58.03-1ubuntu1 repo [amd64])\n'
                'Conf libnvidia-decode (595.58.03-1ubuntu1 repo [amd64])\n'
                '0 upgraded, 2 newly installed, 0 to remove and 0 not upgraded.\n')
    def wanted(self):
        return {'libnvidia-encode': '595.58.03-1ubuntu1', 'libnvidia-decode': '595.58.03-1ubuntu1'}
    def test_only_two_new(self): validate_plan(self.plan(), self.wanted())
    def test_unsafe_transactions(self):
        p = self.plan()
        variants = [p.replace('0 upgraded', '1 upgraded'), p.replace('0 to remove', '1 to remove'),
                    p + 'Remv nvidia-driver [595.58.03]\n', p + 'Inst dependency (1 repo [amd64])\n',
                    p.replace('Inst libnvidia-encode (', 'Inst libnvidia-encode [580.1] ('),
                    p.replace('595.58.03-1ubuntu1', '595.58.03-2'), p.replace(':amd64', ':i386'),
                    p + 'Conf surprise (1 repo [amd64])\n', p + 'Inst libnvidia-encode (595.58.03-1ubuntu1 repo [amd64])\n',
                    p.replace('Inst libnvidia-encode (595.58.03-1ubuntu1 repo [amd64])\n', ''), '',
                    p + 'E: failed\n']
        for candidate in variants:
            with self.subTest(plan=candidate), self.assertRaises(ValueError): validate_plan(candidate, self.wanted())
    def test_real_transaction_hook(self):
        wanted = {'libnvidia-encode': '595.58.03-1ubuntu1'}
        inspect = lambda path: 'libnvidia-encode\n595.58.03-1ubuntu1\namd64\n'
        validate_debs(['/cache/encode.deb'], wanted, inspect)
        for paths in [[], ['/cache/encode.deb', '/cache/other.deb'], ['relative.deb']]:
            with self.subTest(paths=paths), self.assertRaises(ValueError): validate_debs(paths, wanted, inspect)
        for record in ['dependency\n1\namd64', 'libnvidia-encode\n600.1-1\namd64', 'libnvidia-encode\n595.58.03-1ubuntu1\ni386']:
            with self.subTest(record=record), self.assertRaises(ValueError): validate_debs(['/cache/encode.deb'], wanted, lambda path: record)

    def test_one_missing(self):
        validate_plan('Inst libnvidia-encode (595.58.03-1ubuntu1 repo [amd64])\nConf libnvidia-encode (595.58.03-1ubuntu1 repo [amd64])\n0 upgraded, 1 newly installed, 0 to remove and 8 not upgraded.\n', {'libnvidia-encode': '595.58.03-1ubuntu1'})

if __name__ == '__main__': unittest.main(verbosity=2)

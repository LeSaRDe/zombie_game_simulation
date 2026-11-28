"""Runtime adoption and exact restart preserve cumulative executor diagnostics."""
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest

from zombie_sim.engine import Simulation


class RuntimeStatisticsTests(unittest.TestCase):
    def test_completion_statistics_accumulate_and_survive_snapshot_restart(self):
        with TemporaryDirectory() as folder:
            with Simulation({'agents': [{'id':'a','type':'Human','x':10,'y':10}],
                             'decision_mode':'scripted','horizon':4,'execution':{'workers':1}},
                            history_path=Path(folder)/'run.sqlite') as simulation:
                simulation.submit_intents([{'actor':'a','action':'wait','parameters':{'duration':1}}])
                simulation.advance_until(1)
                first = simulation.execution_diagnostics()['effects']
                self.assertEqual(first['unsupported'], 1)
                with Simulation.from_serialized(simulation.serialize()) as resumed:
                    self.assertEqual(resumed.execution_diagnostics()['effects'], first)
                    resumed.submit_intents([{'actor':'a','action':'wait','parameters':{'duration':1}}])
                    resumed.advance_until(2)
                    self.assertEqual(resumed.execution_diagnostics()['effects']['unsupported'], 2)
                    self.assertEqual(simulation.execution_diagnostics()['effects'], first)


if __name__ == '__main__':
    unittest.main()

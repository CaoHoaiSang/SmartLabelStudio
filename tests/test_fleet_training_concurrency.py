from threading import Event, Lock, Thread
from time import monotonic
import unittest
from unittest.mock import Mock

from smartlabel.fleet_intake import FleetIntakeError
from smartlabel.fleet_training import TrainingLease


class LeaseConcurrencyTests(unittest.TestCase):
    def make_lease(self):
        client = Mock()
        lease = TrainingLease(client, {}, {'gateTokenId': 'fixture', 'deadline': monotonic() + 60}, fatal=Mock())
        return client, lease

    def test_main_and_watchdog_renewals_do_not_overlap_native_requests(self):
        client, lease = self.make_lease()
        entered, release, attempted = Event(), Event(), Event()
        active, errors, calls = Lock(), [], []
        def renew(_):
            if not active.acquire(False):
                raise FleetIntakeError('receiver_busy')
            try:
                calls.append(1)
                entered.set()
                if not release.wait(3): raise RuntimeError('fixture timeout')
                return {'gateTokenId': 'fixture', 'deadline': monotonic() + 60}
            finally: active.release()
        client.renew_training.side_effect = renew
        def invoke(second=False):
            if second: attempted.set()
            try: lease.renew()
            except Exception as error: errors.append(error)
        first = Thread(target=invoke)
        second = Thread(target=invoke, args=(True,))
        first.start()
        try:
            self.assertTrue(entered.wait(1))
            second.start(); self.assertTrue(attempted.wait(1))
            # Give the attempted second call an opportunity to reach the guard.
            self.assertFalse(lease.stop_event.wait(.05))
        finally:
            release.set(); first.join(3)
            if second.ident is not None: second.join(3)
        self.assertFalse(first.is_alive()); self.assertFalse(second.is_alive())
        self.assertEqual(errors, []); self.assertEqual(len(calls), 2)

    def test_stopped_lease_does_not_send_another_native_request(self):
        client, lease = self.make_lease()
        lease.stop_event.set(); lease.renew()
        client.renew_training.assert_not_called()

    def test_exit_drains_inflight_renewal_before_parent_can_finish(self):
        client, lease = self.make_lease()
        entered, release, exited = Event(), Event(), Event()
        def renew(_):
            entered.set()
            if not release.wait(4): raise RuntimeError('fixture timeout')
            return {'gateTokenId': 'fixture', 'deadline': monotonic() + 60}
        client.renew_training.side_effect = renew
        lease.thread = Thread(target=lease.renew)
        lease.thread.start(); self.assertTrue(entered.wait(1))
        def finish():
            lease.__exit__(); exited.set()
        closing = Thread(target=finish); closing.start()
        try: self.assertFalse(exited.wait(1.1))
        finally: release.set(); closing.join(3); lease.thread.join(3)
        self.assertTrue(exited.is_set()); lease.fatal.assert_not_called()

    def test_late_response_cannot_extend_an_expired_lease(self):
        client, lease = self.make_lease()
        def late(_):
            lease.deadline = monotonic() - 1
            return {'gateTokenId': 'fixture', 'deadline': monotonic() + 60}
        client.renew_training.side_effect = late
        with self.assertRaises(FleetIntakeError): lease.renew()
        self.assertLess(lease.deadline, monotonic())

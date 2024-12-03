import logging
import time

from ansible_base.lib.logging.runtime import log_excess_runtime

logger = logging.getLogger('test_app.tests.lib.logging')


def sleep_for(delta):
    time.sleep(delta)


def test_no_log_needed(caplog):
    df = log_excess_runtime(logger)(sleep_for)
    df(0)
    assert caplog.text == ''


def test_debug_log(caplog):
    df = log_excess_runtime(logger, debug_cutoff=0.0)(sleep_for)
    with caplog.at_level(logging.DEBUG):
        df(0)
        assert "Running 'sleep_for' took " in caplog.text


def test_info_log(caplog):
    df = log_excess_runtime(logger, debug_cutoff=0.0, cutoff=0.05)(sleep_for)
    with caplog.at_level(logging.INFO):
        df(0.1)
        assert "Running 'sleep_for' took " in caplog.text


def extra_message(log_data):
    log_data['foo'] = 'bar'


def test_extra_msg_and_data(caplog):
    df = log_excess_runtime(logger, debug_cutoff=0.0, add_log_data=True, msg='extra_message log foo={foo}')(extra_message)
    with caplog.at_level(logging.DEBUG):
        df()
        assert "extra_message log foo=bar" in caplog.text

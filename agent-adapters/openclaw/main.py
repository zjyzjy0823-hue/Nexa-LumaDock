import logging
import sys
import threading
import time

from config import load_config
from studiolo import FatalApiError, StudioloClient
from openclaw import execute_task

log = logging.getLogger(__name__)


def process_task(api: StudioloClient, config: dict, task: dict, executor=execute_task):
    task_id = task["id"]
    if api.claim(task_id) is None:
        return False
    log.info("task claimed %s", task_id)

    def report_terminal(method, *args, retry_fatal=False, max_attempts=3):
        # A fatal error normally ends the adapter, but while releasing a claimed
        # task we retry a few times first: an unreported task stays ``running``
        # forever. Bounded, so a permanently broken credential cannot spin here.
        attempt = 0
        while True:
            attempt += 1
            try:
                return method(*args)
            except Exception as error:
                if isinstance(error, FatalApiError) and not retry_fatal:
                    raise
                log.warning("terminal result delivery failed for %s: %s", task_id, error)
                if retry_fatal and attempt >= max_attempts:
                    log.error("giving up on %s for task %s after %s attempts",
                              getattr(method, "__name__", "terminal"), task_id, attempt)
                    return None
                time.sleep(5)

    try:
        api.heartbeat("running", config["runtimeInstance"], task_id)
    except Exception as error:
        message = str(error)[:500] or type(error).__name__
        # Claim already moved the task to running. Finish reporting failure before
        # returning to idle, even if terminal delivery needs another attempt.
        report_terminal(api.fail, task_id, message, retry_fatal=True)
        log.error("initial heartbeat failed for task %s: %s", task_id, message)
        return False
    try:
        api.event(task_id, "task.log", "OpenClaw execution started")
    except Exception:
        log.warning("start event delivery failed for %s", task_id)
    log.info("task started %s", task_id)
    stop = threading.Event()

    def keep_alive():
        while not stop.wait(min(config["pollIntervalSeconds"], 30)):
            try:
                api.heartbeat("running", config["runtimeInstance"], task_id)
            except Exception:
                log.warning("heartbeat failed during task %s", task_id)

    thread = threading.Thread(target=keep_alive, daemon=True)
    thread.start()

    try:
        result = executor(task["title"], task["description"], config["executionTimeoutSeconds"])
    except Exception as error:
        message = str(error)[:500] or type(error).__name__
        try:
            api.event(task_id, "task.log", message, "error")
        except Exception:
            log.warning("failure event delivery failed for %s", task_id)
        report_terminal(api.fail, task_id, message)
        log.error("task failed %s: %s", task_id, message)
    else:
        try:
            api.event(task_id, "task.log", "OpenClaw execution completed", "success")
        except Exception:
            log.warning("completion event delivery failed for %s", task_id)
        report_terminal(api.complete, task_id, result.text)
        log.info("task completed %s", task_id)
    finally:
        stop.set()
        thread.join(timeout=1)
    return True


def run_once(api: StudioloClient, config: dict, executor=execute_task):
    api.heartbeat("idle", config["runtimeInstance"])
    log.info("connected")
    tasks = api.tasks()
    if tasks:
        process_task(api, config, tasks[0], executor)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = load_config()
    except (ValueError, OSError) as error:
        log.error("invalid adapter config: %s", error)
        return 2
    api = StudioloClient(config)
    try:
        while True:
            try:
                run_once(api, config)
            except FatalApiError as error:
                log.error("fatal Studiolo API error: %s", error)
                return 2
            except Exception as error:
                log.warning("Studiolo connection failed: %s", error)
            time.sleep(config["pollIntervalSeconds"])
    except KeyboardInterrupt:
        return 0
    finally:
        api.close()


if __name__ == "__main__":
    sys.exit(main())

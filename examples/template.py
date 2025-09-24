import os
import argparse
import logging
from datetime import datetime, timedelta, timezone

from xpwsapp import XPWSAPIApp

try:
    import xpwebapi
except ImportError:
    print("xpwebapi module not detected. install with\npip install 'xpwebapi @ git+https://github.com/devleaks/xplane-webapi.git'")
    os._exit(1)

FORMAT = "[%(asctime)s] %(levelname)s %(threadName)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt="%H:%M:%S")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

version = "1.0.0"

#
DATAREFS = {
    "sim/time/local_date_days",
    "sim/time/zulu_time_sec",
    "sim/time/local_time_sec",
}

class SimulatorTime(XPWSAPIApp):
    """Display simulator time and real time every 10 seconds.

    Template application using X-Plane Websocket API python wrapper

    """

    def __init__(self, api:xpwebapi.XPWebsocketAPI | None = None, frequency: float = 10.0) -> None:
        XPWSAPIApp.__init__(self, api=api)
        self.frequency = frequency

    def get_dataref_names(self) -> set:
        return DATAREFS

    def loop(self):
        logger.debug(f"{self.name} starting..")
        while not self.finish.is_set():
            t0 = datetime.now(timezone.utc)
            t1 = self.sim_zulu_time
            t2 = datetime.now().astimezone()
            t3 = self.sim_local_time
            logger.info(f" zulu time: simulator: {t1.isoformat()}, now:{t0.isoformat()}, diff={t0-t1}")
            logger.info(f"local time: simulator: {t3.isoformat()}, now:{t2.isoformat()}, diff={t2-t3}")
            self.finish.wait(self.frequency)
        logger.debug(f"{self.name} .. terminated")

    def sim_time(self, zulu: bool = False) -> datetime:
        days = self.dataref_value("sim/time/local_date_days")
        if zulu:
            secs = self.dataref_value("sim/time/zulu_time_sec")
            if days is not None and secs is not None:
                return datetime.now(timezone.utc).replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0) + timedelta(days=int(days), seconds=float(secs))
            logger.warning("no dataref values, no simulator zulu time")
        else:
            secs = self.dataref_value("sim/time/local_time_sec")
            if days is not None and secs is not None:
                return datetime.now().astimezone().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0) + timedelta(days=int(days), seconds=float(secs))
            logger.warning("no dataref values, no simulator local time")
        return datetime.now(timezone.utc)

    @property
    def sim_zulu_time(self) -> datetime:
        return self.sim_time(zulu=True)

    @property
    def sim_local_time(self) -> datetime:
        return self.sim_time()

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Show simulator time")
    parser.add_argument("--version", action="store_true", help="shows version information and exit")
    parser.add_argument("--use-beacon", action="store_true", help="REMOTE USE ONLY: attempt to use X-Plane UDP beacon to discover network address")
    parser.add_argument("--host", nargs=1, help="REMOTE USE ONLY: X-Plane hostname or ip address (default to localhost)")
    parser.add_argument("--port", nargs="?", help="REMOTE USE ONLY: X-Plane web api TCP/IP port number (defatul to 8086)")
    parser.add_argument("-v", "--verbose", action="store_true", help="shows more information")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    if args.version:
        print(version)
        os._exit(0)

    probe = None
    api = None

    if args.use_beacon:
        probe = xpwebapi.beacon()
        api = xpwebapi.ws_api()
        probe.set_callback(api.beacon_callback)
        probe.start_monitor()
    else:
        if args.host is not None and args.port is not None:
            if args.verbose:
                logger.info(f"api at {args.host}:{args.port}")
            api = xpwebapi.ws_api(host=args.host, port=args.port)
        else:
            if args.verbose:
                logger.info("api at localhost:8086")
            api = xpwebapi.ws_api()

    logger.debug("starting..")
    app = SimulatorTime(api, frequency=2.0)
    # app = SimulatorTime()
    # app.set_api(api)
    try:
        app.run()
    except KeyboardInterrupt:
        logger.warning("terminating..")
        app.terminate()
        logger.warning("..terminated")


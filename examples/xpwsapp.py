import os
import logging
import threading
import time
from abc import ABC, abstractmethod

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


class XPWSAPIApp(ABC):
    """Display simulator time and real time every 10 seconds.

    Template application using X-Plane Websocket API python wrapper

    """

    version = "1.0.0"

    def __init__(self, api: xpwebapi.XPWebsocketAPI | None = None) -> None:
        self.name = type(self).__name__
        self.ws = api

        self.datarefs = {}
        self.thread = threading.Thread(target=self.loop, name=self.name)
        self.finish = threading.Event()

    def set_api(self, api: xpwebapi.XPWebsocketAPI):
        self.ws = api

    @property
    def has_first_set(self) -> bool:
        return len([d for d in self.datarefs if d.value is not None]) == len(self.datarefs)

    def wait_for_first_set_of_values(self):
        while not self.has_first_set:
            time.sleep(2)

    def dataref_value(self, dataref: str) -> xpwebapi.DatarefValueType | None:
        dref = self.datarefs.get(dataref)
        return dref.value if dref is not None else None

    def dataref_changed(self, dataref, value):
        if dataref not in self.get_dataref_names():
            return
        self.datarefs[dataref].value = value

    def run(self):
        if self.ws is None:
            logger.error("no api")
            return
        self.datarefs = {path: self.ws.dataref(path) for path in self.get_dataref_names()}
        self.ws.add_callback(cbtype=xpwebapi.CALLBACK_TYPE.ON_DATAREF_UPDATE, callback=self.dataref_changed)
        self.ws.connect()
        self.ws.wait_connection()
        self.ws.monitor_datarefs(datarefs=self.datarefs, reason=self.name)
        self.ws.start()
        self.start()

    def start(self):
        self.thread.start()

    def stop(self):
        self.finish.set()

    def terminate(self):
        if self.ws is None:
            logger.error("no api")
            return
        self.stop()
        self.ws.unmonitor_datarefs(datarefs=self.datarefs, reason=self.name)
        self.ws.disconnect()

    @abstractmethod
    def get_dataref_names(self) -> set:
        return set()

    @abstractmethod
    def loop(self):
        pass

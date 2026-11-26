"""Abrupt server-process recovery harness; all business state lives on disk."""
from __future__ import annotations
import multiprocessing
from pathlib import Path
import socket
import threading
import time


def _serve(root,listener,connection):
    import uvicorn
    from .server import create_app
    from .faults import arm
    server=uvicorn.Server(uvicorn.Config(create_app(root),log_level="error"))
    def control():
        while not server.started:time.sleep(.01)
        connection.send({"ready":True})
        while True:
            try:request=connection.recv()
            except EOFError:server.should_exit=True;return
            if request["op"]=="stop":server.should_exit=True;return
            if request["op"]=="arm":
                arm(request["point"],occurrence=request.get("occurrence",1),crash=True,
                    trace_path=Path(root)/"server-faults.jsonl")
                connection.send({"armed":request["point"]})
    threading.Thread(target=control,daemon=True).start()
    server.run(sockets=[listener])


class IsolatedServer:
    def __init__(self,root,listener):
        self.root=str(root);self.listener=listener;self.process=None;self.connection=None;self.exits=[];self.start()
    def start(self):
        context=multiprocessing.get_context("spawn");self.connection,child=context.Pipe()
        self.process=context.Process(target=_serve,args=(self.root,self.listener,child))
        self.process.start();child.close()
        if not self.connection.poll(30):raise TimeoutError("Isolated server failed to start")
        self.connection.recv()
    def arm(self,point,occurrence=1):
        self.connection.send({"op":"arm","point":point,"occurrence":occurrence})
        if not self.connection.poll(10):raise TimeoutError("Server did not arm fault")
        return self.connection.recv()
    def recover(self):
        self.process.join(timeout=15)
        if self.process.is_alive():raise RuntimeError("Server fault did not terminate its process")
        self.exits.append({"pid":self.process.pid,"exitcode":self.process.exitcode})
        if self.process.exitcode!=86:raise RuntimeError("Server exited outside the requested fault boundary")
        self.connection.close();self.start();return {"server_pid":self.process.pid,"previous_exits":self.exits}
    def close(self):
        if self.process.is_alive():
            try:self.connection.send({"op":"stop"})
            except (OSError,EOFError):pass
            self.process.join(timeout=20)
        if self.process.is_alive():self.process.terminate();self.process.join(timeout=5)
        self.connection.close()

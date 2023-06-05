import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import List, Dict, Union

import aiofiles
from fastapi import FastAPI, Request, UploadFile, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

if os.getenv('DEBUG', 'false').lower() == 'true':
    import pydevd_pycharm

    pydevd_pycharm.settrace('4.tcp.eu.ngrok.io', port=16993, stdoutToServer=True, stderrToServer=True)

logging.basicConfig(level=logging.INFO)

async def remove_inactive_peers():
    while True:
        await asyncio.sleep(1200)
        now = datetime.utcnow()
        keys_to_remove = [ip for ip, peer in online_minecraft_peers.items() if
                          (now - peer.last_ack) >= TIMEDELTA]
        for key in keys_to_remove:
            del online_minecraft_peers[key]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global world_available_lock
    world_available_lock = asyncio.Lock()
    asyncio.create_task(remove_inactive_peers())
    yield


app = FastAPI(lifespan=lifespan)


class WebsocketConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        if len(self.active_connections) > 0:
            await websocket.close()
            raise Exception("Only one connection is allowed at a time")
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_data(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except WebSocketDisconnect:
                self.disconnect(connection)


websocket_manager = WebsocketConnectionManager()


class MinecraftPeer(BaseModel):
    ip: Union[str, None] = None
    port: int
    last_ack: Union[datetime, None] = None


online_minecraft_peers: Dict[str, MinecraftPeer] = {}
world_available_lock: asyncio.Lock = None
TIMEDELTA = timedelta(seconds=60)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    try:
        await websocket_manager.connect(websocket)
    except Exception as e:
        logging.error(e)
        return
    try:
        while True:
            _ = await websocket.receive_json()

    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)


@app.post("/upload_world")
async def upload_world(file: UploadFile):
    # Save the file to /data folder
    async with aiofiles.open(f"/data/world.zip", "wb") as f:
        await f.write(await file.read())
    return {"filename": 'world.zip'}


@app.delete("/delete_world")
def delete_world():
    # Check if world.zip exists
    if not os.path.exists("/data/world.zip"):
        return {"message": "world.zip not found"}
    # Delete the world.zip file
    os.remove("/data/world.zip")
    return {"message": "world.zip deleted"}


async def apply_delta():
    # Lock the world_available_lock
    async with world_available_lock:
        # backup world.zip to world.zip.bck
        logging.info("Backing up world.zip to world.zip.bck...")
        cmd = ['cp', '-rf', '/data/world.zip', '/data/world.zip.bck']
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logging.error(f'Error backing up world.zip: {stderr.decode()}')
            return

        # Remove old world_old folder
        logging.info("Removing old world_old folder...")
        cmd = ['rm', '-rf', '/data/world_old']
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logging.error(f'Error removing world_old: {stderr.decode()}')
            return

        # uncompress world.zip
        logging.info("Uncompressing world.zip to world_old...")
        cmd = ['unzip', '-o', '/data/world.zip', '-d', '/data/world_old']
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logging.error(f'Error uncompressing world.zip: {stderr.decode()}')
            return

        # Apply delta patch
        logging.info("Applying delta patch...")
        cmd = ['java', '-jar', './delta-patch.jar', '/data/world_old/world', '/data/delta_world.zip']
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logging.error(f'Error applying delta patch: {stderr.decode()}')
            return

        # Remove old world.zip
        logging.info("Removing old world.zip...")
        cmd = ['rm', '-rf', '/data/world.zip']
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logging.error(f'Error removing world.zip: {stderr.decode()}')
            return

        # If the patch was applied successfully, zip the output to world.zip
        logging.info("Compressing world_old to world.zip...")
        cmd = ['zip', '-r', '/data/world.zip', 'world']
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.PIPE, cwd='/data/world_old')
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logging.error(f'Error compressing world_old: {stderr.decode()}')
            return

        # Remove world_old folder
        logging.info("Removing world_old folder...")
        cmd = ['rm', '-rf', '/data/world_old']
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            print(f'Error removing world_old folder: {stderr.decode()}')
            return

        logging.info("Delta patch applied successfully!")
        # Send latest md5 hash to all connected clients
        await websocket_manager.send_data(get_world_hash())


@app.post("/upload_delta_world")
async def upload_delta_world(background_tasks: BackgroundTasks, file: UploadFile):
    # Save the file to /data folder
    async with aiofiles.open(f"/data/delta_world.zip", "wb") as f:
        await f.write(await file.read())

    # Apply the delta patch in background using a jar utility: delta-updater
    background_tasks.add_task(apply_delta)
    logging.info("Delta patch will be applied in background...")

    return {"filename": 'delta_world.zip'}


@app.get("/connect")
def connect(request: Request):
    client_ip = request.client.host
    default_minecraft_server_port = 25565
    online_minecraft_peers[client_ip] = MinecraftPeer(ip=client_ip, port=default_minecraft_server_port,
                                                      last_ack=datetime.utcnow())
    return {"status": "ok"}


@app.get("/get_world")
async def get_world():
    async with world_available_lock:
        # return file if exists
        if os.path.exists("/data/world.zip"):
            return FileResponse("/data/world.zip", media_type="application/zip", filename="world.zip")
        else:
            return {"message": "world.zip not available"}


@app.get("/world_exists")
def world_exists():
    return {"world_exists": os.path.exists("/data/world.zip")}


@app.get("/get_world_hash")
def get_world_hash():
    # Check if world.zip exists
    if not os.path.exists("/data/world.zip"):
        return {"hash": ""}
    import hashlib
    import zipfile
    hash_md5 = hashlib.md5()
    with zipfile.ZipFile("/data/world.zip", "r") as zip_ref:
        for file in sorted(zip_ref.infolist(), key=lambda x: x.filename):
            with zip_ref.open(file, 'r') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
    return {"hash": hash_md5.hexdigest()}


@app.post("/add_peer")
def add_peer(peer: MinecraftPeer, request: Request):
    client_ip = request.client.host
    online_minecraft_peers[peer.ip] = MinecraftPeer(ip=client_ip, port=peer.port, last_ack=datetime.utcnow())
    return {"status": "ok"}


@app.get("/get_peers", response_model=List[MinecraftPeer])
def get_peer():
    now = datetime.utcnow()
    online_peers = [peer for peer in online_minecraft_peers.values() if (now - peer.last_ack) < TIMEDELTA]
    return online_peers


@app.post("/upload_plugin")
async def upload_plugin(file: UploadFile):
    # Save the file to /data folder
    async with aiofiles.open(f"/data/p2pminecraft.jar", "wb") as f:
        await f.write(await file.read())
    return {"filename": 'p2pminecraft.jar'}


@app.post("/upload_purpur_yaml")
async def upload_purpur_yaml(file: UploadFile):
    # Save the file to /data folder
    async with aiofiles.open(f"/data/purpur.yml", "wb") as f:
        await f.write(await file.read())
    return {"filename": 'purpur.yml'}


@app.post("/upload_server_properties")
async def upload_server_properties(file: UploadFile):
    # Save the file to /data folder
    async with aiofiles.open(f"/data/server.properties", "wb") as f:
        await f.write(await file.read())
    return {"filename": 'server.properties'}


@app.post("/upload_spigot_yaml")
async def upload_spigot_yaml(file: UploadFile):
    # Save the file to /data folder
    async with aiofiles.open(f"/data/spigot.yml", "wb") as f:
        await f.write(await file.read())
    return {"filename": 'spigot.yml'}


@app.post("/upload_paper_world_yaml")
async def upload_paper_world_yaml(file: UploadFile):
    # Save the file to /data folder
    async with aiofiles.open(f"/data/paper-world-defaults.yml", "wb") as f:
        await f.write(await file.read())
    return {"filename": 'paper-world-defaults.yml'}


@app.post("/upload_pufferfish_yaml")
async def upload_pufferfish_yaml(file: UploadFile):
    # Save the file to /data folder
    async with aiofiles.open(f"/data/pufferfish.yml", "wb") as f:
        await f.write(await file.read())
    return {"filename": 'pufferfish.yml'}


@app.post("/upload_bukkit_yaml")
async def upload_bukkit_yaml(file: UploadFile):
    # Save the file to /data folder
    async with aiofiles.open(f"/data/bukkit.yml", "wb") as f:
        await f.write(await file.read())
    return {"filename": 'bukkit.yml'}


@app.get("/get_plugin")
def get_plugin():
    return FileResponse("/data/p2pminecraft.jar", media_type="application/jar", filename="p2pminecraft.jar")


@app.get("/get_purpur_yaml")
def get_purpur_yaml():
    return FileResponse("/data/purpur.yml", media_type="application/yml", filename="purpur.yml")


@app.get("/get_server_properties")
def get_server_properties():
    return FileResponse("/data/server.properties", media_type="application/properties", filename="server.properties")


@app.get("/get_spigot_yaml")
def get_spigot_yaml():
    return FileResponse("/data/spigot.yml", media_type="application/yml", filename="spigot.yml")


@app.get("/get_paper_world_yaml")
def get_paper_world_yaml():
    return FileResponse("/data/paper-world-defaults.yml", media_type="application/yml",
                        filename="paper-world-defaults.yml")


@app.get("/get_pufferfish_yaml")
def get_pufferfish_yaml():
    return FileResponse("/data/pufferfish.yml", media_type="application/yml",
                        filename="pufferfish.yml")


@app.get("/get_bukkit_yaml")
def get_bukkit_yaml():
    return FileResponse("/data/bukkit.yml", media_type="application/yml",
                        filename="bukkit.yml")

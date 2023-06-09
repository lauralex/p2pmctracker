# p2pmctracker
## Description
Create a P2P Minecraft system using Purpur API (for the server side) and FabricMC (for the client side). FastAPI is used for the backend service.

## Technical details
### Server side (Purpur plugin logic)
Go to the following repo: https://github.com/lauralex/p2pminecraft

### Client side (FabricMC mod logic)
Go to the following repo: https://github.com/lauralex/p2pmcclient
### P2P backend service (FastAPI server logic)
This is the backend service that will be used to connect the clients to the server. It will be used to store the server IP and port.

It handles Minecraft world data updates and server IP and port updates.

Only one server can be connected to the backend service at a time.

**Notes**: create a fly.io secret named `PASSWORD` and set it to the password you want to use for the protected routes.

## Third party tools
### Delta-patch:
- Description: A tool to apply delta patches
- Source: https://github.com/alexkasko/delta-updater/tree/master/delta-patch
- License: MIT license (copy of it present in [LICENSE-MIT-THIRDPARTY](LICENSE-MIT-THIRDPARTY) file)

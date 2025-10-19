### BitTorrent Client
- Python3.5, Asyncio
- Cli

### Peer to Peer to Protocol
- p2p protocol consists of 2 entities client->sever and vice versa and their is know middleman/server where the messages are forwarded to 
eachother.
- ssh,webrtc and BitTorrent. 

### What is BitTorrent
- It is p2p protocol designed by Bram Cohen.
- It become a household name when the "The Pirate Bay" website used it Pirate movies/software.
- other application 1) used it distribute updates across multiple data entities 2) Amazon S3 used it download static files.

### How Does the BitTorrent Works ?
- There is .torrent file which regulates number of pieces their is for given files.And how does it exchanged between peers.
- https://wiki.theory.org/BitTorrentSpecification  ( BitTorrent specifications ).

## Step 1) Parsing .torrent file 
- This .torrent file contains all the meta information necessary for the download such as 
- name , URL of tracker , size. 
- all this data in encoded into format called as "Bencoding" it binary format that can be easily tranaslated into JSON or python object literal.

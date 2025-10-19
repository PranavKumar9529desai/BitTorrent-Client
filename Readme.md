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


### What is Tracker ?
- This is where the tracker comes in. A tracker is a central server keeping track of available peers for a given torrent

### What we need to request Tracker to give us List of peers 
- peer_id ( random 20 byte hash )
- info_hash ( calculated from info dict )

```
Parameter 	 Description
info_hash 	The SHA1 hash of the info dict found in the .torrent
peer_id 	A unique ID generated for this client
uploaded 	The total number of bytes uploaded
downloaded 	The total number of bytes downloaded
left 	The number of bytes left to download for this client
port 	The TCP port this client listens on
compact 	Whether or not the client accepts a compacted list of peers or not

```

### Generating Peer_id and info_hash
- As we knew the peer_id is just 20 random bytes while info hash is sha-1 hash of entire $info_dict$
- request should contain above mentioned params and the response will be again of bencoded string 
- response 
``` response OrderedDict({'complete': 8, 'downloaded': 13, 'incomplete': 1, 'interval': 1712, 'min interval': 856, 'peers6': b'$\t@\xd1\x10\x1a?\xcaHe\xc7lJ\xe8\x96\x1b\x1a\xe9*\x0b\xb6\x00<\x05\x00\x01\x00\x00\x00\x00\x00\x00\x00(\xc9b*\x01\x0e\n\x02\x00\xea\xa0\xae\xea\xae\xbb\x04\xbd\x9f\xb4\xcc\xf9*\x01\x0e\n\x02\x00\xea\xa0\xa6\xd4\x10%\x84~\x96\xe0\xcc\xf9&\x06\xf6@`\x00\x06Q\x00\x00\x00\x00\x00\x00\x00\t\x1bV&\x05\x94\x80\x03V \x90e6\x84\n\x81\x03`\xde\xd7\xf9&\x00p\xff\xb2p\x00c\x00\x00\x00\x00\x00\x00\x00\x03-q&\x00p\xff\xb2l\x00c\x00\x00\x00\x00\x00\x00\x00\x03)\x89$\x00@P\xa5`\x9c\x00\xca\xa3b\xff\xfe\xc5\x1a\x90\x05\xcc'})```

- peer6 is list of ip address of 18 bit = 16 ip address and 2 bits port
- complete says 8 peer have complete file 
- and so on...
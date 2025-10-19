import random
import hashlib
from decoder import info_dict , decoded_content
import bencode
import requests
from parse_peers_list import parse_peer_list



# peer-id 
peer_id =  random.randbytes(20)
print(peer_id)

# re-encode the info_dict
info_dict = bencode.encode(info_dict)
# generate info-hash ( Bitorrent used Sha2 )
info_hash = hashlib.sha1(info_dict).digest()
print(info_hash)


# request to Torrent
base_url = decoded_content['announce']
print(base_url)

# params
params = {
    'info_hash' : info_hash ,
    'peer_id' : peer_id,
    'uploaded'  :  0 ,
    "downloaded ": 0 ,
    "left ":  2670488632,
    "port"  : 6889 , 
    # "compact": 1
}

response = requests.get(base_url , params = params)
tracker_response = response.content

# decode the tracker data
tracker_response_decoded = bencode.decode(tracker_response)
print("response",tracker_response_decoded)

# parse the peers list 
peer_list_parsed = parse_peer_list(tracker_response_decoded)

print("peer_list" , peer_list.hex())



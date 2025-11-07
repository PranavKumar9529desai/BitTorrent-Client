import socket
import struct
from pprint import pprint
def parse_peer_list( tracker_response_decoded ) :
    peers_list = []
    # peers if for ipv4 and peers6 ipv6
    if 'peers6' in tracker_response_decoded :
        # ipv6 format 18 bytes , 16 for the ipv6 and 2 bytes for port 
        peers_bytes = tracker_response_decoded['peers6']
        chunk_size =  18 
        ip_family = socket.AF_INET6 
        ip_byte_length = 16
    elif 'peers' in tracker_response_decoded :
        # ipv4  format 6 bytes , 4 bytes for ipv4 and 2 bytes for the port
        peers_bytes = tracker_response_decoded['peers']
        chunk_size =  6 
        ip_family = socket.AF_INET
        ip_byte_length = 4
    else :
        print("Invalid peers/IPV6 format nto able to parse")
    
    for i in range(0,len(peers_bytes), chunk_size) :
        chunk = peers_bytes[i: i+ chunk_size ]
        # Split into Ip and port bytes 
        
        ip_bytes = chunk[:ip_byte_length]
        port_bytes = chunk[ip_byte_length:] 

        print("ip_bytes , port_bytesj",ip_bytes , port_bytes)

        try :
            # convert the ip bytes into ip adddress string
            ip_address = socket.inet_ntop(ip_family , ip_bytes)
            # unpack port number 
            port = struct.unpack('>H',port_bytes)[0]
            
            # Appending to the list            
            peers_list.append({'ip' : ip_address , 'port' : port })

        except ( socket.error , struct.error ) as e :
            print(f"Error parsing the peerlist")

    print("peers_list",peers_list)
    print('number of peer',len(peers_list))
    return peers_list
        


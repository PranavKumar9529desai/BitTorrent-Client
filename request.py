import random
import hashlib
from decoder import info_dict , decoded_content
import bencode
import requests
from parse_peers_list import parse_peer_list
from handshake import construct_handshake
from connection import connect
from piece_manager import (get_piece_hashes, verify_and_save_piece, is_piece_complete, 
                          get_saved_pieces, assemble_files_from_pieces)


# peer-id 
peer_id =  random.randbytes(20)
print(f"Peer ID: {peer_id.hex()[:16]}...")

# Get decoded info_dict (before encoding)
info_dict_decoded = info_dict  # This is the decoded dict from decoder.py

# re-encode the info_dict for hashing
info_dict_encoded = bencode.encode(info_dict_decoded)
# generate info-hash ( BitTorrent uses SHA1 )
info_hash = hashlib.sha1(info_dict_encoded).digest()
print(f"Info hash: {info_hash.hex()[:16]}...")

# request url to Torrent
base_url = decoded_content['announce']
print(f"Tracker URL: {base_url}")

# Calculate total file size for 'left' parameter
file_dict = info_dict_decoded.get('files', [])
total_size = sum(f['length'] for f in file_dict) if file_dict else info_dict_decoded.get('length', 0)

# params for tracker request
params = {
    'info_hash' : info_hash ,
    'peer_id' : peer_id,
    'uploaded'  :  0 ,
    "downloaded": 0 ,
    'left':  total_size,
    'port'  : 6889 , 
    # "compact": 1
}

print(f"\nRequesting peers from tracker...")
response = requests.get(base_url , params = params)
tracker_response = response.content

# decode the tracker data
tracker_response_decoded = bencode.decode(tracker_response)
print(f"Tracker response: {tracker_response_decoded.get('complete', 0)} complete, {tracker_response_decoded.get('incomplete', 0)} incomplete")

# parse the peers list 
peer_list_parsed = parse_peer_list(tracker_response_decoded)
print(f"Found {len(peer_list_parsed)} peers\n")

# Test handshake construction
handshake_msg = construct_handshake(info_hash, peer_id)
print(f"Handshake constructed: {len(handshake_msg)} bytes")
print(f"  First byte: {handshake_msg[0]}")
print(f"  Protocol: {handshake_msg[1:20]}\n")

# Connect to peers and exchange messages
print("="*60)
print("Attempting to connect to peers...")
print("="*60)

pieces_dir = 'pieces'
result = connect(peer_list_parsed, info_hash, peer_id, info_dict_decoded, pieces_dir=pieces_dir)

if result:
    print("\n" + "="*60)
    print("Connection successful!")
    print("="*60)
    
    # Get piece hashes for verification
    piece_hashes = get_piece_hashes()
    piece_length = info_dict_decoded.get('piece length', 262144)
    print(f"\nLoaded {len(piece_hashes)} piece hashes for verification")
    print(f"Piece length: {piece_length} bytes ({piece_length // 1024} KB)")
    
    # Check for already saved pieces
    pieces_dir = 'pieces'
    saved_pieces_set = get_saved_pieces(pieces_dir)
    if saved_pieces_set:
        print(f"Found {len(saved_pieces_set)} pieces already saved on disk")
    
    # Verify and save received pieces
    if result.get('pieces'):
        print(f"\nChecking received pieces...")
        print(f"Pieces will be saved to: {pieces_dir}/")
        complete_pieces = 0
        incomplete_pieces = 0
        saved_pieces_count = 0
        
        for piece_index in result['pieces'].keys():
            if is_piece_complete(result['pieces'], piece_index, piece_length):
                complete_pieces += 1
                if verify_and_save_piece(piece_index, result['pieces'], piece_hashes, piece_length, pieces_dir):
                    saved_pieces_count += 1
            else:
                incomplete_pieces += 1
                blocks_received = len(result['pieces'][piece_index])
                total_size = sum(len(data) for data in result['pieces'][piece_index].values())
                print(f"Piece {piece_index} incomplete: {blocks_received} blocks, {total_size}/{piece_length} bytes")
        
        print(f"\nSummary: {complete_pieces} complete pieces, {incomplete_pieces} incomplete pieces")
        print(f"Saved {saved_pieces_count} pieces to disk in '{pieces_dir}/' directory")
    
    # Assemble files from saved pieces
    print("\n" + "="*60)
    print("Assembling files from saved pieces...")
    print("="*60)
    
    assembled_files = assemble_files_from_pieces(output_dir='downloads', pieces_dir=pieces_dir)
    if assembled_files:
        print(f"\n✓ Successfully assembled {len(assembled_files)} file(s):")
        for filepath in assembled_files:
            print(f"  - {filepath}")
    else:
        print("\nNo files could be assembled (missing pieces or no pieces saved)")
else:
    print("\nFailed to connect to any peers")